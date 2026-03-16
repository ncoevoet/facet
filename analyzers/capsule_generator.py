"""Capsule generator — curated photo diaporamas grouped by theme.

Generates capsule types:
1. Journey — trips detected via GPS clustering + temporal gaps
2. Moments with [Person] — best photos of recognized persons
3. Seasonal Palette — photos grouped by season + year
4. Golden Collection — top 1% by aggregate score
5. Color Story — visually similar groups via CLIP embedding clustering
6. This Week, Years Ago — extended "On This Day" across ±3 days
7. Monthly Highlights — best photos of each month
8. Year in Review — best photos of each year
9. Camera Collection — best photos from each camera body
10. Tag Collection — best photos for each popular tag
"""

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from utils.date_utils import parse_date as _parse_date
from utils.embedding import bytes_to_normalized_embedding
from utils.union_find import UnionFind

logger = logging.getLogger("facet.capsules")

# SQLite expression to convert EXIF date (2025:11:23 17:07:24) to ISO format
_ISO_DATE = "REPLACE(SUBSTR(date_taken,1,10),':','-') || SUBSTR(date_taken,11)"

# Season definitions (meteorological)
_SEASONS = {
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
    "winter": (12, 1, 2),
}

_SEASON_ICONS = {
    "spring": "park",
    "summer": "wb_sunny",
    "autumn": "park",
    "winter": "ac_unit",
}


def _stable_id(*parts: str) -> str:
    """Generate a short stable ID from string parts."""
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _month_to_season(month: int) -> str:
    for season, months in _SEASONS.items():
        if month in months:
            return season
    return "spring"


def _haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km between two GPS points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _count_tags(photos):
    """Count tag occurrences across a list of photo rows. Returns defaultdict[str, int]."""
    tag_counts = defaultdict(int)
    for photo in photos:
        tags_str = photo["tags"] or ""
        if tags_str:
            try:
                tag_list = json.loads(tags_str) if tags_str.startswith("[") else tags_str.split(",")
                for tag in tag_list:
                    tag = tag.strip().strip('"')
                    if tag:
                        tag_counts[tag] += 1
            except (json.JSONDecodeError, AttributeError):
                pass
    return tag_counts


def generate_all_capsules(conn, config=None, user_id=None):
    """Generate all capsule types and return a combined list.

    Args:
        conn: SQLite connection
        config: Full scoring_config dict
        user_id: Optional user ID for visibility filtering

    Returns:
        list[dict] with keys: type, id, title, subtitle, cover_photo_path,
        photo_count, icon, params
    """
    if config is None:
        config = {}
    capsule_config = config.get("capsules", {})
    min_aggregate = capsule_config.get("min_aggregate", 6.0)

    from api.db_helpers import get_visibility_clause
    vis = get_visibility_clause(user_id)

    capsules = []
    seen_ids = set()

    # Specialized generators (unique algorithms)
    generators = [
        _generate_journeys,
        _generate_faces_of,
        _generate_seasonal,
        _generate_golden,
        _generate_color_story,
        _generate_this_week,
        _generate_location,
        _generate_person_pairs,
    ]

    for gen in generators:
        try:
            for c in gen(conn, capsule_config, min_aggregate, vis, user_id):
                if c["id"] not in seen_ids:
                    seen_ids.add(c["id"])
                    capsules.append(c)
        except Exception:
            logger.exception("Failed to generate capsules from %s", gen.__name__)

    # Generic dimension-based capsules (single + cross-dimensional)
    try:
        for c in _generate_dimension_capsules(conn, capsule_config, min_aggregate, vis, user_id):
            if c["id"] not in seen_ids:
                seen_ids.add(c["id"])
                capsules.append(c)
    except Exception:
        logger.exception("Failed to generate dimension capsules")

    # Global dedup: remove capsules whose photos overlap >60% with a prior capsule
    max_overlap = capsule_config.get("max_photo_overlap", 0.6)
    capsules = _deduplicate_capsules(capsules, max_overlap)

    return capsules


def _deduplicate_capsules(capsules, max_overlap=0.6):
    """Remove capsules whose photo set overlaps too much with a prior capsule."""
    kept = []
    kept_sets: list[set[str]] = []

    for c in capsules:
        paths = c.get("params", {}).get("paths", [])
        if not paths:
            kept.append(c)
            continue

        path_set = set(paths)
        # Check overlap with each already-kept capsule
        dominated = False
        for existing in kept_sets:
            overlap = len(path_set & existing)
            # Overlap relative to the smaller set
            min_size = min(len(path_set), len(existing))
            if min_size > 0 and overlap / min_size > max_overlap:
                dominated = True
                break

        if not dominated:
            kept.append(c)
            kept_sets.append(path_set)

    logger.info("Dedup: %d → %d capsules (removed %d with >%.0f%% overlap)",
                len(capsules), len(kept), len(capsules) - len(kept), max_overlap * 100)
    return kept


def _generate_journeys(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate Journey capsules from GPS data + temporal gaps."""
    cfg = capsule_config.get("journey", {})
    min_distance_km = cfg.get("min_distance_km", 50)
    min_photos = cfg.get("min_photos", 8)
    time_gap_hours = cfg.get("time_gap_hours", 24)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    # Find home location (most frequent 0.1° grid cell)
    home_row = conn.execute(
        f"""SELECT ROUND(gps_latitude, 1) AS lat_grid, ROUND(gps_longitude, 1) AS lon_grid,
               COUNT(*) AS cnt
           FROM photos
           WHERE gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL AND {vis_sql}
           GROUP BY lat_grid, lon_grid
           ORDER BY cnt DESC LIMIT 1""",
        vis_params,
    ).fetchone()

    if not home_row:
        return []

    home_lat = home_row["lat_grid"]
    home_lon = home_row["lon_grid"]

    # Pre-filter with SQL bounding box (~0.45° ≈ 50km at equator, conservative)
    deg_delta = min_distance_km / 111.0  # rough km-to-degree

    rows = conn.execute(
        f"""SELECT path, date_taken, gps_latitude, gps_longitude, aggregate
           FROM photos
           WHERE gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL
             AND aggregate >= ?
             AND date_taken IS NOT NULL
             AND (ABS(gps_latitude - ?) > ? OR ABS(gps_longitude - ?) > ?)
             AND {vis_sql}
           ORDER BY date_taken ASC""",
        [min_aggregate, home_lat, deg_delta * 0.7, home_lon, deg_delta * 0.7] + vis_params,
    ).fetchall()

    # Precise haversine filter
    away_photos = []
    for r in rows:
        dist = _haversine_km(home_lat, home_lon, r["gps_latitude"], r["gps_longitude"])
        if dist >= min_distance_km:
            away_photos.append(r)

    if not away_photos:
        return []

    # Split by temporal gaps
    trips = []
    current_trip = [away_photos[0]]
    for i in range(1, len(away_photos)):
        prev_date = _parse_date(away_photos[i - 1]["date_taken"])
        curr_date = _parse_date(away_photos[i]["date_taken"])
        if prev_date and curr_date:
            gap_hours = (curr_date - prev_date).total_seconds() / 3600
            if gap_hours > time_gap_hours:
                trips.append(current_trip)
                current_trip = []
        current_trip.append(away_photos[i])
    if current_trip:
        trips.append(current_trip)

    # Build trip list with dates first, then disambiguate titles
    raw_trips = []
    for trip in trips:
        if len(trip) < min_photos:
            continue

        dates = [_parse_date(p["date_taken"]) for p in trip]
        dates = [d for d in dates if d]
        if not dates:
            continue

        raw_trips.append((trip, min(dates), max(dates)))

    # Count trips per month to disambiguate titles
    month_counts = defaultdict(int)
    for _, start, _ in raw_trips:
        month_counts[start.strftime("%B %Y")] += 1

    capsules = []
    for trip, start_date, end_date in raw_trips:
        month_key = start_date.strftime("%B %Y")
        if month_counts[month_key] > 1:
            # Include day range for disambiguation
            if start_date.date() == end_date.date():
                title_date = f"{start_date.day} {month_key}"
            elif start_date.month == end_date.month:
                title_date = f"{start_date.day}\u2013{end_date.day} {month_key}"
            else:
                title_date = f"{start_date.strftime('%d %B')}\u2013{end_date.strftime('%d %B %Y')}"
        else:
            title_date = month_key
        trip_id = _stable_id("journey", start_date.isoformat())

        best = max(trip, key=lambda p: p["aggregate"] or 0)
        photo_paths = [p["path"] for p in trip[:max_photos]]

        capsules.append({
            "type": "journey",
            "id": f"journey_{trip_id}",
            "title_key": "capsules.journey_title",
            "title_params": {"date": title_date},
            "title": f"Journey \u2014 {title_date}",
            "subtitle": f"{len(photo_paths)} photos",
            "cover_photo_path": best["path"],
            "photo_count": len(photo_paths),
            "icon": "flight",
            "params": {"paths": photo_paths},
        })

    return capsules


def _generate_faces_of(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate Moments with [Person] capsules."""
    cfg = capsule_config.get("faces_of", {})
    min_photos = cfg.get("min_photos", 10)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    # Cannot use pre-computed `vis` here: photos table is aliased as `ph` in the JOIN
    from api.db_helpers import get_visibility_clause
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='ph')

    rows = conn.execute(
        f"""SELECT p.id, p.name, p.face_count,
               f.photo_path, ph.aggregate, ph.face_quality
           FROM persons p
           JOIN faces f ON f.person_id = p.id
           JOIN photos ph ON ph.path = f.photo_path
           WHERE p.name IS NOT NULL AND p.name != ''
             AND ph.aggregate >= ?
             AND {vis_sql}
           ORDER BY p.id, (COALESCE(ph.aggregate, 0) * 0.6 + COALESCE(ph.face_quality, 0) * 0.4) DESC""",
        [min_aggregate] + vis_params,
    ).fetchall()

    if not rows:
        return []

    # Group by person
    person_photos = defaultdict(list)
    person_names = {}
    for r in rows:
        pid = r["id"]
        person_names[pid] = r["name"]
        if len(person_photos[pid]) < max_photos:
            person_photos[pid].append(r["photo_path"])

    # Skip persons whose photo sets overlap >50% with an already-added capsule
    # (common when the same group photo appears for multiple persons)
    capsules = []
    used_path_sets: list[set[str]] = []
    for pid, paths in person_photos.items():
        unique_paths = list(dict.fromkeys(paths))  # deduplicate preserving order
        if len(unique_paths) < min_photos:
            continue

        path_set = set(unique_paths)
        if any(len(path_set & existing) > len(path_set) * 0.5 for existing in used_path_sets):
            continue
        used_path_sets.append(path_set)

        name = person_names[pid]
        capsules.append({
            "type": "faces_of",
            "id": f"faces_{pid}",
            "title_key": "capsules.faces_of_title",
            "title_params": {"name": name},
            "title": f"Moments with {name}",
            "subtitle": f"{len(unique_paths)} photos",
            "cover_photo_path": unique_paths[0],
            "photo_count": len(unique_paths),
            "icon": "face",
            "params": {"person_id": pid, "paths": unique_paths},
        })

    return capsules


def _generate_seasonal(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate Seasonal Palette capsules."""
    cfg = capsule_config.get("seasonal", {})
    min_photos = cfg.get("min_photos", 10)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    rows = conn.execute(
        f"""SELECT path, date_taken, aesthetic, aggregate
           FROM photos
           WHERE date_taken IS NOT NULL AND aggregate >= ? AND {vis_sql}
           ORDER BY aesthetic DESC""",
        [min_aggregate] + vis_params,
    ).fetchall()

    # Group by season + year
    groups = defaultdict(list)
    for r in rows:
        dt = _parse_date(r["date_taken"])
        if not dt:
            continue
        season = _month_to_season(dt.month)
        # Winter Dec belongs to next year's winter
        year = dt.year if not (season == "winter" and dt.month == 12) else dt.year + 1
        key = (season, year)
        if len(groups[key]) < max_photos:
            groups[key].append(r)

    capsules = []
    for (season, year), photos in sorted(groups.items(), key=lambda x: (-x[0][1], x[0][0])):
        if len(photos) < min_photos:
            continue

        season_title = season.title()
        capsule_id = _stable_id("seasonal", season, str(year))
        best = photos[0]  # already sorted by aesthetic DESC

        paths = [p["path"] for p in photos]
        capsules.append({
            "type": "seasonal",
            "id": f"seasonal_{capsule_id}",
            "title_key": "capsules.seasonal_title",
            "title_params": {"season": season, "year": str(year)},
            "title": f"{season_title} {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": best["path"],
            "photo_count": len(paths),
            "icon": _SEASON_ICONS.get(season, "park"),
            "params": {"paths": paths},
        })

    return capsules


def _generate_golden(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate the Golden Collection capsule (top 1%)."""
    cfg = capsule_config.get("golden", {})
    percentile = cfg.get("percentile", 99)
    max_photos = cfg.get("max_photos", 50)

    vis_sql, vis_params = vis

    total = conn.execute(
        f"SELECT COUNT(*) FROM photos WHERE aggregate IS NOT NULL AND {vis_sql}",
        vis_params,
    ).fetchone()[0]

    if total < 20:
        return []

    offset = max(1, round(total * (100 - percentile) / 100))

    threshold_row = conn.execute(
        f"""SELECT aggregate FROM photos
           WHERE aggregate IS NOT NULL AND {vis_sql}
           ORDER BY aggregate DESC
           LIMIT 1 OFFSET ?""",
        vis_params + [offset],
    ).fetchone()

    if not threshold_row:
        return []

    threshold = threshold_row["aggregate"]

    rows = conn.execute(
        f"""SELECT path, aggregate
           FROM photos
           WHERE aggregate >= ? AND {vis_sql}
           ORDER BY aggregate DESC
           LIMIT ?""",
        [threshold] + vis_params + [max_photos],
    ).fetchall()

    if not rows:
        return []

    paths = [r["path"] for r in rows]

    return [{
        "type": "golden",
        "id": "golden",
        "title_key": "capsules.golden_title",
        "title_params": {},
        "title": "Golden Collection",
        "subtitle": f"{len(paths)} photos",
        "cover_photo_path": paths[0],
        "photo_count": len(paths),
        "icon": "diamond",
        "params": {"paths": paths},
    }]


def _generate_color_story(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate Color Story capsules via embedding clustering."""
    cfg = capsule_config.get("color_story", {})
    embedding_threshold = cfg.get("embedding_threshold", 0.75)
    min_group_size = cfg.get("min_group_size", 8)
    max_groups = cfg.get("max_groups", 5)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    rows = conn.execute(
        f"""SELECT path, clip_embedding, tags, aggregate
           FROM photos
           WHERE clip_embedding IS NOT NULL AND aggregate >= ? AND {vis_sql}
           ORDER BY date_taken DESC
           LIMIT 5000""",
        [min_aggregate] + vis_params,
    ).fetchall()

    # Build embeddings
    valid_photos = []
    embeddings = []
    for r in rows:
        emb = bytes_to_normalized_embedding(r["clip_embedding"])
        if emb is not None:
            embeddings.append(emb)
            valid_photos.append(r)

    if len(embeddings) < min_group_size:
        return []

    # Cap for O(n^2) similarity
    if len(embeddings) > 2000:
        embeddings = embeddings[:2000]
        valid_photos = valid_photos[:2000]

    emb_matrix = np.stack(embeddings)
    n = len(emb_matrix)

    uf = UnionFind(n)
    sims = emb_matrix @ emb_matrix.T

    # Vectorized pair detection instead of Python double loop
    rows_idx, cols_idx = np.where(np.triu(sims >= embedding_threshold, k=1))
    for i, j in zip(rows_idx, cols_idx):
        uf.union(int(i), int(j))

    groups_map = defaultdict(list)
    for idx in range(n):
        groups_map[uf.find(idx)].append(idx)

    # Sort by group size desc, take top N
    sorted_groups = sorted(groups_map.values(), key=len, reverse=True)

    capsules = []
    for group_indices in sorted_groups[:max_groups]:
        if len(group_indices) < min_group_size:
            continue

        group_photos = [valid_photos[i] for i in group_indices[:max_photos]]

        tag_counts = _count_tags(group_photos)

        if tag_counts:
            top_tags = sorted(tag_counts, key=tag_counts.get, reverse=True)[:2]
            name = " & ".join(t.title() for t in top_tags)
        else:
            name = "Visual Story"

        paths = [p["path"] for p in group_photos]
        best = max(group_photos, key=lambda p: p["aggregate"] or 0)
        cid = _stable_id("color", *paths[:3])

        capsules.append({
            "type": "color_story",
            "id": f"color_{cid}",
            "title_key": "capsules.color_story_title",
            "title_params": {"name": name},
            "title": name,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": best["path"],
            "photo_count": len(paths),
            "icon": "palette",
            "params": {"paths": paths},
        })

    return capsules


def _generate_this_week(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate 'This Week, Years Ago' capsules."""
    cfg = capsule_config.get("this_week_years_ago", {})
    min_photos_per_year = cfg.get("min_photos_per_year", 3)
    max_photos = capsule_config.get("max_photos_per_capsule", 30)

    vis_sql, vis_params = vis

    today = date.today()
    current_year = today.year

    # Build day-of-year window (±3 days)
    window_days = []
    for delta in range(-3, 4):
        d = today + timedelta(days=delta)
        window_days.append(d.strftime("%m-%d"))

    placeholders = ",".join(["?"] * len(window_days))

    rows = conn.execute(
        f"""SELECT path, date_taken, aggregate
           FROM photos
           WHERE strftime('%m-%d', date_taken) IN ({placeholders})
             AND CAST(strftime('%Y', date_taken) AS INTEGER) < ?
             AND aggregate >= ?
             AND date_taken IS NOT NULL
             AND {vis_sql}
           ORDER BY aggregate DESC""",
        window_days + [current_year, min_aggregate] + vis_params,
    ).fetchall()

    # Group by year
    year_groups = defaultdict(list)
    for r in rows:
        dt = _parse_date(r["date_taken"])
        if dt:
            year_groups[dt.year].append(r)

    capsules = []
    for year in sorted(year_groups.keys(), reverse=True):
        photos = year_groups[year]
        if len(photos) < min_photos_per_year:
            continue

        photos = photos[:max_photos]
        paths = [p["path"] for p in photos]
        best = photos[0]  # already sorted by aggregate DESC

        capsules.append({
            "type": "this_week",
            "id": f"thisweek_{year}",
            "title_key": "capsules.this_week_title",
            "title_params": {"year": str(year)},
            "title": f"This Week in {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": best["path"],
            "photo_count": len(paths),
            "icon": "history",
            "params": {"paths": paths},
        })

    return capsules


def _is_junk_lens(lens):
    """Filter out junk EXIF lens values (numeric IDs, very short strings)."""
    if not lens or len(lens) < 4:
        return True
    stripped = lens.replace(":", "").replace("-", "").replace(" ", "").replace(".", "")
    if stripped.isdigit():
        return True
    return False


# NOTE: The individual generators below (_generate_monthly, _generate_yearly,
# _generate_camera, etc.) have been replaced by the generic dimension engine
# (_generate_dimension_capsules) at the bottom of this file.


def _generate_location(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate Location capsules — clusters of geotagged photos by area."""
    cfg = capsule_config.get("location", {})
    min_photos = cfg.get("min_photos", 10)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)
    grid_size = cfg.get("grid_degrees", 0.5)  # ~55km grid cells

    vis_sql, vis_params = vis

    # Group photos by grid cell
    rows = conn.execute(
        f"""SELECT ROUND(gps_latitude / ?, 0) * ? AS lat_grid,
               ROUND(gps_longitude / ?, 0) * ? AS lon_grid,
               COUNT(*) AS cnt
           FROM photos
           WHERE gps_latitude IS NOT NULL AND gps_longitude IS NOT NULL
             AND aggregate >= ? AND {vis_sql}
           GROUP BY lat_grid, lon_grid
           HAVING cnt >= ?
           ORDER BY cnt DESC
           LIMIT 50""",
        [grid_size, grid_size, grid_size, grid_size,
         min_aggregate] + vis_params + [min_photos],
    ).fetchall()

    capsules = []
    for loc in rows:
        lat = loc["lat_grid"]
        lon = loc["lon_grid"]

        photos = conn.execute(
            f"""SELECT path, aggregate
               FROM photos
               WHERE gps_latitude BETWEEN ? AND ?
                 AND gps_longitude BETWEEN ? AND ?
                 AND aggregate >= ? AND {vis_sql}
               ORDER BY aggregate DESC
               LIMIT ?""",
            [lat - grid_size / 2, lat + grid_size / 2,
             lon - grid_size / 2, lon + grid_size / 2,
             min_aggregate] + vis_params + [max_photos],
        ).fetchall()

        if len(photos) < min_photos:
            continue

        paths = [p["path"] for p in photos]
        # Title from coordinates (reverse geocoding deferred)
        title = f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"
        cid = _stable_id("loc", f"{lat:.2f}", f"{lon:.2f}")
        capsules.append({
            "type": "location",
            "id": f"loc_{cid}",
            "title_key": "capsules.location_title",
            "title_params": {"location": title},
            "title": title,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": paths[0],
            "photo_count": len(paths),
            "icon": "location_on",
            "params": {"paths": paths},
        })

    return capsules


def _generate_person_pairs(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate capsules for pairs of named persons appearing together."""
    cfg = capsule_config.get("person_pairs", {})
    min_photos = cfg.get("min_photos", 8)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    from api.db_helpers import get_visibility_clause
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='ph')

    # Find photo paths where 2+ named persons co-appear
    rows = conn.execute(
        f"""SELECT f1.photo_path, p1.id AS pid1, p1.name AS name1,
               p2.id AS pid2, p2.name AS name2, ph.aggregate
           FROM faces f1
           JOIN faces f2 ON f1.photo_path = f2.photo_path AND f1.person_id < f2.person_id
           JOIN persons p1 ON p1.id = f1.person_id
           JOIN persons p2 ON p2.id = f2.person_id
           JOIN photos ph ON ph.path = f1.photo_path
           WHERE p1.name IS NOT NULL AND p1.name != ''
             AND p2.name IS NOT NULL AND p2.name != ''
             AND ph.aggregate >= ?
             AND {vis_sql}
           ORDER BY ph.aggregate DESC""",
        [min_aggregate] + vis_params,
    ).fetchall()

    if not rows:
        return []

    # Group by person pair
    groups = defaultdict(list)
    pair_names = {}
    for r in rows:
        key = (r["pid1"], r["pid2"])
        pair_names[key] = (r["name1"], r["name2"])
        if len(groups[key]) < max_photos:
            groups[key].append(r["photo_path"])

    capsules = []
    for (pid1, pid2), paths in groups.items():
        unique_paths = list(dict.fromkeys(paths))
        if len(unique_paths) < min_photos:
            continue

        name1, name2 = pair_names[(pid1, pid2)]
        cid = _stable_id("pair", str(pid1), str(pid2))
        capsules.append({
            "type": "person_pair",
            "id": f"pair_{cid}",
            "title_key": "capsules.person_pair_title",
            "title_params": {"name1": name1, "name2": name2},
            "title": f"{name1} & {name2}",
            "subtitle": f"{len(unique_paths)} photos",
            "cover_photo_path": unique_paths[0],
            "photo_count": len(unique_paths),
            "icon": "group",
            "params": {"paths": unique_paths},
        })

    return capsules


def _generate_score_per_dim(conn, capsules, capsule_config, min_aggregate,
                            vis_sql, vis_params, max_photos, has_tags,
                            dim_a_name, dim_b_name, score_dim, group_dim):
    """Generate 'Best [Score] per [Dimension]' capsules."""
    if group_dim.get("requires") == "photo_tags" and not has_tags:
        return
    if not group_dim.get("sql_expr"):
        return

    cfg_key = f"{dim_a_name}_{dim_b_name}"
    cfg = capsule_config.get(cfg_key, {})
    min_photos_score = cfg.get("min_photos", max(group_dim.get("min_photos", 10) // 2, 5))

    join = group_dim.get("join", "")
    expr = group_dim["sql_expr"]
    label_expr = group_dim.get("label_expr", expr)
    sort = score_dim["sort_override"]
    score_label = score_dim.get("score_label", dim_a_name)

    filters = []
    if group_dim.get("filter"):
        filters.append(group_dim["filter"])
    if score_dim.get("filter"):
        filters.append(score_dim["filter"])
    extra_filter = ("AND " + " AND ".join(filters)) if filters else ""

    junk_fn = group_dim.get("junk_filter")
    value_map = group_dim.get("value_map")
    transform = group_dim.get("title_transform")

    try:
        group_rows = conn.execute(
            f"""SELECT {expr} AS dim_val, {label_expr} AS dim_label, COUNT(*) AS cnt
               FROM photos {join}
               WHERE aggregate >= ? {extra_filter} AND {vis_sql}
               GROUP BY dim_val
               HAVING cnt >= ?
               ORDER BY cnt DESC
               LIMIT 50""",
            [min_aggregate] + vis_params + [min_photos_score],
        ).fetchall()
    except Exception:
        logger.debug("Score-per-dim %s x %s query failed", dim_a_name, dim_b_name)
        return

    for gr in group_rows:
        val = gr["dim_val"]
        label = gr["dim_label"]
        if val is None:
            continue
        if junk_fn and junk_fn(str(val)):
            continue

        display = value_map.get(val, label) if value_map else (str(label) if label else str(val))
        if transform:
            display = transform(display)

        photos = conn.execute(
            f"""SELECT path
               FROM photos {join}
               WHERE {expr} = ? AND aggregate >= ? {extra_filter} AND {vis_sql}
               ORDER BY {sort}
               LIMIT ?""",
            [val, min_aggregate] + vis_params + [max_photos],
        ).fetchall()

        paths = list(dict.fromkeys(p["path"] for p in photos))
        if len(paths) < min_photos_score:
            continue

        cid = _stable_id(cfg_key, str(val))
        title = f"{score_label}: {display}"
        capsules.append({
            "type": cfg_key,
            "id": f"{cfg_key}_{cid}",
            "title_key": "capsules.score_per_dim_title",
            "title_params": {"score": score_label, "dimension": display},
            "title": title,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": paths[0],
            "photo_count": len(paths),
            "icon": score_dim["icon"],
            "params": {"paths": paths},
        })


# ============================================================
# Generic Dimension-Based Capsule Engine
# ============================================================
# Defines groupable dimensions and auto-generates capsules
# from single dimensions and cross-dimensional combinations.

_DIMENSIONS = {
    "year": {
        "sql_expr": f"strftime('%Y', {_ISO_DATE})",
        "icon": "event",
        "min_photos": 20,
        "title_tpl": "{value}",
        "title_key": "capsules.yearly_title",
        "param_name": "year",
    },
    "month": {
        "sql_expr": f"strftime('%Y-%m', {_ISO_DATE})",
        "icon": "calendar_month",
        "min_photos": 8,
        "title_tpl": "{value}",
        "title_key": "capsules.monthly_title",
        "param_name": "date",
    },
    "week": {
        "sql_expr": f"strftime('%Y-W%W', {_ISO_DATE})",
        "icon": "date_range",
        "min_photos": 8,
        "title_tpl": "{value}",
        "title_key": "capsules.week_title",
        "param_name": "week",
    },
    "season": {
        # Handled by _generate_seasonal (special month→season mapping)
        "skip_single": True,
    },
    "camera": {
        "sql_expr": "camera_model",
        "filter": "camera_model IS NOT NULL AND camera_model != ''",
        "icon": "photo_camera",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.camera_title",
        "param_name": "camera",
    },
    "lens": {
        "sql_expr": "lens_model",
        "filter": "lens_model IS NOT NULL AND lens_model != ''",
        "icon": "camera",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.lens_title",
        "param_name": "lens",
        "junk_filter": _is_junk_lens,
    },
    "tag": {
        # Tag dimension uses photo_tags join
        "join": "JOIN photo_tags pt ON pt.photo_path = photos.path",
        "sql_expr": "pt.tag",
        "icon": "label",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.tag_title",
        "param_name": "tag",
        "title_transform": str.title,
        "requires": "photo_tags",
    },
    "day_of_week": {
        "sql_expr": f"CAST(strftime('%w', {_ISO_DATE}) AS INTEGER)",
        "icon": "today",
        "min_photos": 15,
        "title_tpl": "Best of {value}s",
        "title_key": "capsules.day_of_week_title",
        "param_name": "day",
        "value_map": {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
                      4: "Thursday", 5: "Friday", 6: "Saturday"},
    },
    "person": {
        # Person dimension uses faces/persons join
        "join": "JOIN faces f ON f.photo_path = photos.path JOIN persons p ON p.id = f.person_id",
        "sql_expr": "p.id",
        "label_expr": "p.name",
        "filter": "p.name IS NOT NULL AND p.name != ''",
        "icon": "face",
        "min_photos": 10,
        "title_tpl": "{value}",
        "title_key": "capsules.faces_of_title",
        "param_name": "name",
        "skip_single": True,  # Handled by _generate_faces_of
    },
    "score_aesthetic": {
        "sort_override": "aesthetic DESC",
        "icon": "auto_awesome",
        "min_photos": 30,
        "title_tpl": "Best Aesthetic",
        "title_key": "capsules.best_aesthetic_title",
        "param_name": "metric",
        "single_only": True,
        "is_score": True,
        "score_label": "Aesthetic",
    },
    "score_iaa": {
        "sort_override": "aesthetic_iaa DESC",
        "filter": "aesthetic_iaa IS NOT NULL",
        "icon": "stars",
        "min_photos": 30,
        "title_tpl": "Best IAA Aesthetic",
        "title_key": "capsules.best_iaa_title",
        "param_name": "metric",
        "single_only": True,
        "is_score": True,
        "score_label": "IAA",
    },
    "score_composition": {
        "sort_override": "comp_score DESC",
        "filter": "comp_score IS NOT NULL",
        "icon": "grid_on",
        "min_photos": 30,
        "title_tpl": "Best Composition",
        "title_key": "capsules.best_composition_title",
        "param_name": "metric",
        "single_only": True,
        "is_score": True,
        "score_label": "Composition",
    },
    "score_sharpness": {
        "sort_override": "tech_sharpness DESC",
        "filter": "tech_sharpness IS NOT NULL",
        "icon": "center_focus_strong",
        "min_photos": 30,
        "title_tpl": "Sharpest Photos",
        "title_key": "capsules.best_sharpness_title",
        "param_name": "metric",
        "single_only": True,
        "is_score": True,
        "score_label": "Sharpness",
    },
    "score_face_quality": {
        "sort_override": "face_quality DESC",
        "filter": "face_quality IS NOT NULL AND face_quality > 0",
        "icon": "face_retouching_natural",
        "min_photos": 20,
        "title_tpl": "Best Face Quality",
        "title_key": "capsules.best_face_quality_title",
        "param_name": "metric",
        "single_only": True,
        "is_score": True,
        "score_label": "Face Quality",
    },
}

# Cross-dimensional combinations to generate.
# When one dimension has is_score=True, it acts as a sort override
# rather than a grouping dimension (e.g., "Best Aesthetic by Person").
_CROSS_DIMENSIONS = [
    # Grouping × Grouping
    ("camera", "year"),
    ("camera", "lens"),
    ("camera", "month"),
    ("lens", "year"),
    ("lens", "month"),
    ("tag", "year"),
    ("tag", "month"),
    ("person", "year"),
    ("person", "month"),
    ("person", "lens"),
    ("person", "camera"),
    ("person", "tag"),
    # Score × Grouping (best-of per dimension)
    ("score_aesthetic", "person"),
    ("score_aesthetic", "camera"),
    ("score_aesthetic", "year"),
    ("score_aesthetic", "lens"),
    ("score_iaa", "person"),
    ("score_composition", "person"),
    ("score_composition", "camera"),
    ("score_sharpness", "camera"),
    ("score_sharpness", "lens"),
    ("score_face_quality", "person"),
]


def _generate_dimension_capsules(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate capsules from single dimensions and cross-dimensional combos."""
    from api.db_helpers import is_photo_tags_available
    has_tags = is_photo_tags_available()

    vis_sql, vis_params = vis
    max_photos = capsule_config.get("max_photos_per_capsule", 40)
    capsules = []

    # --- Single-dimension capsules ---
    for dim_name, dim in _DIMENSIONS.items():
        if dim.get("skip_single"):
            continue
        if dim.get("requires") == "photo_tags" and not has_tags:
            continue

        cfg = capsule_config.get(dim_name, {})
        min_photos = cfg.get("min_photos", dim.get("min_photos", 10))

        if dim.get("single_only"):
            # Score-based capsules: just top N by a specific metric
            sort = dim.get("sort_override", "aggregate DESC")
            extra_filter = f"AND {dim['filter']}" if dim.get("filter") else ""
            rows = conn.execute(
                f"""SELECT path, aggregate
                   FROM photos
                   WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                   ORDER BY {sort}
                   LIMIT ?""",
                [min_aggregate] + vis_params + [max_photos],
            ).fetchall()
            if len(rows) >= min_photos:
                paths = [r["path"] for r in rows]
                capsules.append({
                    "type": dim_name,
                    "id": dim_name,
                    "title_key": dim["title_key"],
                    "title_params": {dim["param_name"]: dim["title_tpl"]},
                    "title": dim["title_tpl"],
                    "subtitle": f"{len(paths)} photos",
                    "cover_photo_path": paths[0],
                    "photo_count": len(paths),
                    "icon": dim["icon"],
                    "params": {"paths": paths},
                })
            continue

        # Grouped dimension
        join = dim.get("join", "")
        sql_expr = dim["sql_expr"]
        label_expr = dim.get("label_expr", sql_expr)
        extra_filter = f"AND {dim['filter']}" if dim.get("filter") else ""
        junk_fn = dim.get("junk_filter")
        value_map = dim.get("value_map")
        title_transform = dim.get("title_transform")

        group_rows = conn.execute(
            f"""SELECT {sql_expr} AS dim_val, {label_expr} AS dim_label, COUNT(*) AS cnt
               FROM photos {join}
               WHERE aggregate >= ? {extra_filter} AND {vis_sql}
               GROUP BY dim_val
               HAVING cnt >= ?
               ORDER BY cnt DESC
               LIMIT 100""",
            [min_aggregate] + vis_params + [min_photos],
        ).fetchall()

        for gr in group_rows:
            val = gr["dim_val"]
            label = gr["dim_label"]
            if val is None:
                continue
            if junk_fn and junk_fn(str(val)):
                continue

            display = value_map.get(val, label) if value_map else (str(label) if label else str(val))
            if title_transform:
                display = title_transform(display)

            photos = conn.execute(
                f"""SELECT path, aggregate
                   FROM photos {join}
                   WHERE {sql_expr} = ? AND aggregate >= ? {extra_filter} AND {vis_sql}
                   ORDER BY aggregate DESC
                   LIMIT ?""",
                [val, min_aggregate] + vis_params + [max_photos],
            ).fetchall()

            if len(photos) < min_photos:
                continue

            paths = [p["path"] for p in photos]
            cid = _stable_id(dim_name, str(val))
            capsules.append({
                "type": dim_name,
                "id": f"{dim_name}_{cid}",
                "title_key": dim["title_key"],
                "title_params": {dim["param_name"]: display},
                "title": display,
                "subtitle": f"{len(paths)} photos",
                "cover_photo_path": paths[0],
                "photo_count": len(paths),
                "icon": dim["icon"],
                "params": {"paths": paths},
            })

    # --- Cross-dimensional capsules ---
    for dim_a_name, dim_b_name in _CROSS_DIMENSIONS:
        dim_a = _DIMENSIONS.get(dim_a_name)
        dim_b = _DIMENSIONS.get(dim_b_name)
        if not dim_a or not dim_b:
            continue
        if (dim_a.get("requires") == "photo_tags" or dim_b.get("requires") == "photo_tags") and not has_tags:
            continue

        # When one dimension is a score metric, use it as sort override
        score_dim = dim_a if dim_a.get("is_score") else (dim_b if dim_b.get("is_score") else None)
        group_dim = dim_b if dim_a.get("is_score") else (dim_a if dim_b.get("is_score") else None)

        if score_dim and not group_dim:
            continue  # Both are scores — skip

        if score_dim:
            # Score × Grouping: group by one dim, sort by score metric
            _generate_score_per_dim(
                conn, capsules, capsule_config, min_aggregate, vis_sql, vis_params,
                max_photos, has_tags, dim_a_name, dim_b_name, score_dim, group_dim,
            )
            continue

        # Both are regular grouping dimensions — skip if either is single_only
        if dim_a.get("single_only") or dim_b.get("single_only"):
            continue

        cfg_key = f"{dim_a_name}_{dim_b_name}"
        cfg = capsule_config.get(cfg_key, {})
        min_photos_cross = cfg.get("min_photos", max(dim_a.get("min_photos", 10), dim_b.get("min_photos", 10)) // 2)
        min_photos_cross = max(min_photos_cross, 5)

        # Build combined query
        joins = set()
        if dim_a.get("join"):
            joins.add(dim_a["join"])
        if dim_b.get("join"):
            joins.add(dim_b["join"])
        join_clause = " ".join(joins)

        filters = []
        if dim_a.get("filter"):
            filters.append(dim_a["filter"])
        if dim_b.get("filter"):
            filters.append(dim_b["filter"])
        extra_filter = ("AND " + " AND ".join(filters)) if filters else ""

        expr_a = dim_a["sql_expr"]
        expr_b = dim_b["sql_expr"]
        label_a = dim_a.get("label_expr", expr_a)
        label_b = dim_b.get("label_expr", expr_b)

        try:
            group_rows = conn.execute(
                f"""SELECT {expr_a} AS val_a, {label_a} AS lbl_a,
                       {expr_b} AS val_b, {label_b} AS lbl_b,
                       COUNT(*) AS cnt
                   FROM photos {join_clause}
                   WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                   GROUP BY val_a, val_b
                   HAVING cnt >= ?
                   ORDER BY cnt DESC
                   LIMIT 100""",
                [min_aggregate] + vis_params + [min_photos_cross],
            ).fetchall()
        except Exception:
            logger.debug("Cross-dimension %s x %s query failed", dim_a_name, dim_b_name)
            continue

        junk_a = dim_a.get("junk_filter")
        junk_b = dim_b.get("junk_filter")
        value_map_a = dim_a.get("value_map")
        value_map_b = dim_b.get("value_map")
        transform_a = dim_a.get("title_transform")
        transform_b = dim_b.get("title_transform")

        for gr in group_rows:
            va, la = gr["val_a"], gr["lbl_a"]
            vb, lb = gr["val_b"], gr["lbl_b"]
            if va is None or vb is None:
                continue
            if junk_a and junk_a(str(va)):
                continue
            if junk_b and junk_b(str(vb)):
                continue

            disp_a = value_map_a.get(va, la) if value_map_a else (str(la) if la else str(va))
            disp_b = value_map_b.get(vb, lb) if value_map_b else (str(lb) if lb else str(vb))
            if transform_a:
                disp_a = transform_a(disp_a)
            if transform_b:
                disp_b = transform_b(disp_b)

            photos = conn.execute(
                f"""SELECT path, aggregate
                   FROM photos {join_clause}
                   WHERE {expr_a} = ? AND {expr_b} = ?
                     AND aggregate >= ? {extra_filter} AND {vis_sql}
                   ORDER BY aggregate DESC
                   LIMIT ?""",
                [va, vb, min_aggregate] + vis_params + [max_photos],
            ).fetchall()

            if len(photos) < min_photos_cross:
                continue

            paths = list(dict.fromkeys(p["path"] for p in photos))  # dedupe
            if len(paths) < min_photos_cross:
                continue

            cid = _stable_id(cfg_key, str(va), str(vb))
            title = f"{disp_a} \u2014 {disp_b}"
            capsules.append({
                "type": cfg_key,
                "id": f"{cfg_key}_{cid}",
                "title_key": "capsules.cross_title",
                "title_params": {"a": disp_a, "b": disp_b},
                "title": title,
                "subtitle": f"{len(paths)} photos",
                "cover_photo_path": paths[0],
                "photo_count": len(paths),
                "icon": dim_a["icon"],
                "params": {"paths": paths},
            })

    return capsules
