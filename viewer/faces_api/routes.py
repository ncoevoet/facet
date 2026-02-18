from flask import request, jsonify, session
from viewer.faces_api import faces_api_bp
from viewer.config import invalidate_filter_cache, is_multi_user_enabled
from viewer.auth import require_edition, require_auth, get_session_user_id
from viewer.db_helpers import get_db_connection, update_person_face_count


@faces_api_bp.route('/api/person/<int:person_id>/faces')
def api_person_faces(person_id):
    """Get all faces belonging to a person."""
    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.photo_path, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
            FROM faces f
            LEFT JOIN photos p ON f.photo_path = p.path
            WHERE f.person_id = ?
            ORDER BY p.aggregate DESC
            LIMIT 36
        """, (person_id,)).fetchall()
        return jsonify({
            'faces': [dict(f) for f in faces]
        })
    finally:
        conn.close()


@faces_api_bp.route('/api/person/<int:person_id>/avatar', methods=['POST'])
@require_edition
def api_set_person_avatar(person_id):
    """Set a face as the representative avatar for a person."""
    data = request.get_json()
    face_id = data.get('face_id')

    if not face_id:
        return jsonify({'error': 'face_id required'}), 400

    conn = get_db_connection()
    try:
        # Verify face belongs to this person
        face = conn.execute("""
            SELECT id, face_thumbnail FROM faces WHERE id = ? AND person_id = ?
        """, (face_id, person_id)).fetchone()

        if not face:
            return jsonify({'error': 'Face not found or does not belong to this person'}), 404

        # Update person's representative face and copy thumbnail
        conn.execute("""
            UPDATE persons SET representative_face_id = ?, face_thumbnail = ?
            WHERE id = ?
        """, (face_id, face['face_thumbnail'], person_id))

        conn.commit()
        invalidate_filter_cache()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/faces')
def api_photo_faces():
    """Get all faces in a photo with their current person assignment."""
    photo_path = request.args.get('path')
    if not photo_path:
        return jsonify({'error': 'path required'}), 400

    conn = get_db_connection()
    try:
        faces = conn.execute("""
            SELECT f.id, f.face_index, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.person_id, p.name as person_name
            FROM faces f
            LEFT JOIN persons p ON f.person_id = p.id
            WHERE f.photo_path = ?
            ORDER BY f.face_index
        """, (photo_path,)).fetchall()
        return jsonify({
            'faces': [dict(f) for f in faces]
        })
    finally:
        conn.close()


@faces_api_bp.route('/api/face/<int:face_id>/assign', methods=['POST'])
@require_edition
def api_assign_face(face_id):
    """Assign a face to a person."""
    data = request.get_json()
    person_id = data.get('person_id')

    if person_id is None:
        return jsonify({'error': 'person_id required'}), 400

    conn = get_db_connection()
    try:
        # Get current person_id for the face
        face = conn.execute("SELECT person_id FROM faces WHERE id = ?", (face_id,)).fetchone()
        if not face:
            return jsonify({'error': 'Face not found'}), 404

        old_person_id = face['person_id']

        # Update face assignment
        conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (person_id, face_id))

        # Update face counts
        if old_person_id:
            update_person_face_count(conn, old_person_id)
        update_person_face_count(conn, person_id)

        conn.commit()
        invalidate_filter_cache()
        return jsonify({'success': True})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/assign_all_faces', methods=['POST'])
@require_edition
def api_assign_all_faces():
    """Assign all unassigned faces in a photo to a person."""
    data = request.get_json()
    photo_path = data.get('photo_path')
    person_id = data.get('person_id')

    if not photo_path or person_id is None:
        return jsonify({'error': 'photo_path and person_id required'}), 400

    conn = get_db_connection()
    try:
        # Get all unassigned faces in this photo
        faces = conn.execute("""
            SELECT id FROM faces WHERE photo_path = ? AND person_id IS NULL
        """, (photo_path,)).fetchall()

        if not faces:
            return jsonify({'error': 'No unassigned faces found'}), 404

        face_ids = [f['id'] for f in faces]

        # Assign all faces to the person
        placeholders = ','.join('?' * len(face_ids))
        conn.execute(f"""
            UPDATE faces SET person_id = ? WHERE id IN ({placeholders})
        """, [person_id] + face_ids)

        # Update person face count
        update_person_face_count(conn, person_id)

        conn.commit()
        invalidate_filter_cache()
        return jsonify({'success': True, 'assigned_count': len(face_ids)})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/unassign_person', methods=['POST'])
@require_edition
def api_unassign_person():
    """Unassign all faces of a specific person from a photo."""
    data = request.get_json()
    photo_path = data.get('photo_path')
    person_id = data.get('person_id')

    if not photo_path or not person_id:
        return jsonify({'error': 'Missing photo_path or person_id'}), 400

    conn = get_db_connection()
    try:
        # Get faces to unassign
        faces = conn.execute("""
            SELECT id FROM faces
            WHERE photo_path = ? AND person_id = ?
        """, (photo_path, person_id)).fetchall()

        if not faces:
            return jsonify({'error': 'No faces found'}), 404

        # Unassign faces
        conn.execute("""
            UPDATE faces SET person_id = NULL
            WHERE photo_path = ? AND person_id = ?
        """, (photo_path, person_id))

        # Update person's face count
        update_person_face_count(conn, person_id)

        # Check if person now has zero faces and should be deleted
        new_count = conn.execute(
            "SELECT face_count FROM persons WHERE id = ?",
            (person_id,)
        ).fetchone()

        person_deleted = False
        if new_count and new_count[0] == 0:
            conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))
            person_deleted = True

        conn.commit()
        invalidate_filter_cache()

        return jsonify({
            'success': True,
            'unassigned_count': len(faces),
            'person_deleted': person_deleted
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/set_rating', methods=['POST'])
@require_auth
def api_set_rating():
    """Set star rating (0-5) for a photo."""
    data = request.get_json()
    photo_path = data.get('photo_path')
    rating = data.get('rating')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400
    if rating is None or not isinstance(rating, int) or rating < 0 or rating > 5:
        return jsonify({'error': 'rating must be integer 0-5'}), 400

    user_id = get_session_user_id()
    conn = get_db_connection()
    try:
        if user_id and is_multi_user_enabled():
            conn.execute("""
                INSERT INTO user_preferences (user_id, photo_path, star_rating)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, photo_path) DO UPDATE SET star_rating = excluded.star_rating
            """, (user_id, photo_path, rating))
        else:
            conn.execute("UPDATE photos SET star_rating = ? WHERE path = ?", (rating, photo_path))
        conn.commit()
        return jsonify({'success': True, 'rating': rating})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/toggle_favorite', methods=['POST'])
@require_auth
def api_toggle_favorite():
    """Toggle favorite flag for a photo."""
    data = request.get_json()
    photo_path = data.get('photo_path')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400

    user_id = get_session_user_id()
    conn = get_db_connection()
    try:
        if user_id and is_multi_user_enabled():
            row = conn.execute(
                "SELECT is_favorite FROM user_preferences WHERE user_id = ? AND photo_path = ?",
                (user_id, photo_path)
            ).fetchone()
            current = row['is_favorite'] if row else 0
            new_value = 0 if current else 1
            if new_value == 1:
                conn.execute("""
                    INSERT INTO user_preferences (user_id, photo_path, is_favorite, is_rejected)
                    VALUES (?, ?, 1, 0)
                    ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 1, is_rejected = 0
                """, (user_id, photo_path))
            else:
                conn.execute("""
                    INSERT INTO user_preferences (user_id, photo_path, is_favorite)
                    VALUES (?, ?, 0)
                    ON CONFLICT(user_id, photo_path) DO UPDATE SET is_favorite = 0
                """, (user_id, photo_path))
        else:
            row = conn.execute("SELECT is_favorite FROM photos WHERE path = ?", (photo_path,)).fetchone()
            if not row:
                return jsonify({'error': 'Photo not found'}), 404
            new_value = 0 if row['is_favorite'] else 1
            if new_value == 1:
                conn.execute("UPDATE photos SET is_favorite = 1, is_rejected = 0 WHERE path = ?", (photo_path,))
            else:
                conn.execute("UPDATE photos SET is_favorite = 0 WHERE path = ?", (photo_path,))
        conn.commit()
        return jsonify({'success': True, 'is_favorite': new_value == 1, 'is_rejected': False if new_value == 1 else None})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@faces_api_bp.route('/api/photo/toggle_rejected', methods=['POST'])
@require_auth
def api_toggle_rejected():
    """Toggle rejected flag for a photo."""
    data = request.get_json()
    photo_path = data.get('photo_path')

    if not photo_path:
        return jsonify({'error': 'photo_path required'}), 400

    user_id = get_session_user_id()
    conn = get_db_connection()
    try:
        if user_id and is_multi_user_enabled():
            row = conn.execute(
                "SELECT is_rejected FROM user_preferences WHERE user_id = ? AND photo_path = ?",
                (user_id, photo_path)
            ).fetchone()
            current = row['is_rejected'] if row else 0
            new_value = 0 if current else 1
            if new_value == 1:
                conn.execute("""
                    INSERT INTO user_preferences (user_id, photo_path, is_rejected, star_rating, is_favorite)
                    VALUES (?, ?, 1, 0, 0)
                    ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 1, star_rating = 0, is_favorite = 0
                """, (user_id, photo_path))
            else:
                conn.execute("""
                    INSERT INTO user_preferences (user_id, photo_path, is_rejected)
                    VALUES (?, ?, 0)
                    ON CONFLICT(user_id, photo_path) DO UPDATE SET is_rejected = 0
                """, (user_id, photo_path))
        else:
            row = conn.execute("SELECT is_rejected FROM photos WHERE path = ?", (photo_path,)).fetchone()
            if not row:
                return jsonify({'error': 'Photo not found'}), 404
            new_value = 0 if row['is_rejected'] else 1
            if new_value == 1:
                conn.execute("UPDATE photos SET is_rejected = 1, star_rating = 0, is_favorite = 0 WHERE path = ?", (photo_path,))
            else:
                conn.execute("UPDATE photos SET is_rejected = 0 WHERE path = ?", (photo_path,))
        conn.commit()
        return jsonify({'success': True, 'is_rejected': new_value == 1, 'star_rating': 0 if new_value == 1 else None, 'is_favorite': False if new_value == 1 else None})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
