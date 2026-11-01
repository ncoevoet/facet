"""Actual authorized auto-cull preview/apply and label-state boundaries."""
from tests.test_auto_cull import _db, _post


def test_default_preserves_existing_rating_and_previews_exact_labels(edition_client):
    conn = _db()
    conn.execute("UPDATE photos SET star_rating=5, is_favorite=1 WHERE path='/g1c.jpg'")
    conn.commit()
    body = {'group_by': 'burst', 'strictness': 100}
    preview, _ = _post(edition_client, conn, body)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data['existing_labels_count'] == data['preserved_labels_count'] == 1
    assert data['existing_labels'] == [{
        'path': '/g1c.jpg', 'star_rating': 5, 'is_favorite': True,
        'is_rejected': False, 'is_kept': False, 'proposed': 'unchanged',
    }]
    assert all('/g1c.jpg' not in row['keep_paths'] + row['reject_paths'] for row in data['preview'])
    applied, _ = _post(edition_client, conn, {
        **body, 'dry_run': False, 'expected_digest': data['plan_digest'],
        'expected_state_digest': data['decision_state_digest'],
    })
    assert applied.status_code == 200, applied.text
    assert tuple(conn.execute("SELECT star_rating,is_favorite,is_rejected,burst_reviewed FROM photos WHERE path='/g1c.jpg'").fetchone()) == (5, 1, 0, 0)
    # Positive branch: undecided photos were really processed.
    assert conn.execute("SELECT is_rejected FROM photos WHERE path='/g1b.jpg'").fetchone()[0] == 1


def test_explicit_replace_previews_overwrite_and_applies_only_unchanged_state(edition_client):
    conn = _db()
    conn.execute("UPDATE photos SET star_rating=5 WHERE path='/g1c.jpg'")
    conn.commit()
    body = {'group_by': 'burst', 'strictness': 100, 'decision_policy': 'replace'}
    preview, _ = _post(edition_client, conn, body)
    data = preview.json()
    assert data['preserved_labels_count'] == 0
    assert data['existing_labels'][0]['proposed'] == 'reject'
    apply = {**body, 'dry_run': False, 'expected_digest': data['plan_digest'],
             'expected_state_digest': data['decision_state_digest']}
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/g1c.jpg'")
    conn.commit()
    refused, retrain = _post(edition_client, conn, apply)
    assert refused.status_code == 412, refused.text
    retrain.assert_not_called()
    assert conn.execute("SELECT count(*) FROM photos WHERE burst_reviewed=1 OR is_rejected=1").fetchone()[0] == 0
    assert conn.execute("SELECT star_rating FROM photos WHERE path='/g1c.jpg'").fetchone()[0] == 4
    refreshed, _ = _post(edition_client, conn, body)
    data = refreshed.json()
    accepted, _ = _post(edition_client, conn, {
        **body, 'dry_run': False, 'expected_digest': data['plan_digest'],
        'expected_state_digest': data['decision_state_digest'],
    })
    assert accepted.status_code == 200, accepted.text
    assert tuple(conn.execute("SELECT star_rating,is_rejected FROM photos WHERE path='/g1c.jpg'").fetchone()) == (4, 1)


def test_policy_changes_the_shared_plan_digest(edition_client):
    conn = _db()
    preserve, _ = _post(edition_client, conn, {'group_by': 'burst'})
    replace, _ = _post(edition_client, conn, {'group_by': 'burst', 'decision_policy': 'replace'})
    assert preserve.status_code == replace.status_code == 200
    assert preserve.json()['plan_digest'] != replace.json()['plan_digest']
    assert conn.execute('SELECT count(*) FROM comparisons').fetchone()[0] == 0


def test_change_then_restore_still_invalidates_the_preview(edition_client):
    conn = _db()
    body = {'group_by': 'burst', 'decision_policy': 'replace'}
    preview, _ = _post(edition_client, conn, body)
    data = preview.json()
    conn.execute("UPDATE photos SET star_rating=5 WHERE path='/g1c.jpg'")
    conn.execute("UPDATE photos SET star_rating=0 WHERE path='/g1c.jpg'")
    conn.commit()
    response, retrain = _post(edition_client, conn, {
        **body, 'dry_run': False, 'expected_digest': data['plan_digest'],
        'expected_state_digest': data['decision_state_digest'],
    })
    assert response.status_code == 412, response.text
    assert conn.execute('SELECT count(*) FROM photos WHERE burst_reviewed=1 OR is_rejected=1').fetchone()[0] == 0
    retrain.assert_not_called()


def test_existing_reject_is_disclosed_and_only_reconsidered_by_replace(edition_client):
    conn = _db()
    conn.execute("UPDATE photos SET is_rejected=1 WHERE path='/g1a.jpg'")
    conn.commit()
    base = {'group_by': 'burst', 'strictness': 100}
    preserve, _ = _post(edition_client, conn, base)
    assert preserve.status_code == 200, preserve.text
    assert preserve.json()['existing_labels_count'] == 1
    assert preserve.json()['existing_labels'][0]['proposed'] == 'unchanged'
    assert all('/g1a.jpg' not in row['keep_paths'] + row['reject_paths'] for row in preserve.json()['preview'])
    replace, _ = _post(edition_client, conn, {**base, 'decision_policy': 'replace'})
    data = replace.json()
    assert data['existing_labels'][0]['is_rejected'] is True
    assert data['existing_labels'][0]['proposed'] == 'keep'
    applied, _ = _post(edition_client, conn, {
        **base, 'decision_policy': 'replace', 'dry_run': False,
        'expected_digest': data['plan_digest'], 'expected_state_digest': data['decision_state_digest'],
    })
    assert applied.status_code == 200, applied.text
    assert tuple(conn.execute("SELECT is_rejected,is_kept FROM photos WHERE path='/g1a.jpg'").fetchone()) == (0, 1)


def test_decision_preview_keeps_edition_authorization(regular_client):
    conn = _db()
    response, _ = _post(regular_client, conn, {'decision_policy': 'replace'})
    assert response.status_code == 403


def test_history_refusal_rolls_back_entire_automation(edition_client, monkeypatch):
    from api import organization_capture
    original = organization_capture.record

    def refuse_compound(conn, actor, kind, scope, before):
        if before:
            raise ValueError('history cannot represent this operation')
        return original(conn, actor, kind, scope, before)

    monkeypatch.setattr(organization_capture, 'record', refuse_compound)
    conn = _db()
    response, retrain = _post(edition_client, conn, {'group_by': 'burst', 'dry_run': False})
    assert response.status_code == 422, response.text
    assert conn.execute('SELECT count(*) FROM photos WHERE is_kept=1 OR is_rejected=1 OR burst_reviewed=1').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM comparisons').fetchone()[0] == 0
    retrain.assert_not_called()


def test_changed_highlights_eligibility_requires_a_new_preview(edition_client, monkeypatch):
    from api.routers import burst_culling
    config = {**burst_culling._get_auto_cull_config(), 'highlights_min': 100}
    monkeypatch.setattr(burst_culling, '_get_auto_cull_config', lambda: config)
    conn = _db()
    body = {'group_by': 'burst', 'strictness': 100, 'highlights_album': 'R15 Highlights'}
    preview, _ = _post(edition_client, conn, body)
    data = preview.json()
    assert data['highlights_added'] == 0
    config['highlights_min'] = 0
    response, retrain = _post(edition_client, conn, {
        **body, 'dry_run': False, 'expected_digest': data['plan_digest'],
        'expected_state_digest': data['decision_state_digest'],
    })
    assert response.status_code == 412, response.text
    assert conn.execute('SELECT count(*) FROM albums').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM photos WHERE is_rejected=1 OR is_kept=1').fetchone()[0] == 0
    retrain.assert_not_called()
