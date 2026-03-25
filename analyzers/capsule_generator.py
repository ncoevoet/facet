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
11. Seeded Discovery — seed-based exploration via time, similarity, person, tag, location, mood
12. Progress — "Your Photography is Improving" from quarterly score trends
13. Color Palette — "Color of the Month" from saturation/monochrome profiles
14. Rare Pairs — infrequent person pairs in high-scoring photos
"""

import hashlib
import json
import logging
import math
import random
import time
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

from utils.date_utils import parse_date as _parse_date
from utils.embedding import bytes_to_normalized_embedding, filter_uniform_embeddings
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


def _parse_tags(tags_str):
    """Parse a tags string (JSON array or comma-separated) into a list of clean tag strings."""
    if not tags_str:
        return []
    try:
        tag_list = json.loads(tags_str) if tags_str.startswith("[") else tags_str.split(",")
        return [t.strip().strip('"') for t in tag_list if t.strip().strip('"')]
    except (json.JSONDecodeError, AttributeError):
        return []


def _count_tags(photos):
    """Count tag occurrences across a list of photo rows. Returns defaultdict[str, int]."""
    tag_counts = defaultdict(int)
    for photo in photos:
        for tag in _parse_tags(photo["tags"] or ""):
            tag_counts[tag] += 1
    return tag_counts


def _pick_cover_photo(paths, capsule_id, top_n=5, freshness_seconds=86400, capsule_config=None):
    """Pick a cover photo from top candidates with configurable rotation."""
    if not paths:
        return ""
    candidates = paths[:min(top_n, len(paths))]
    if capsule_config and capsule_config.get("_shuffle"):
        rng = random.Random()
    else:
        rotation_seed = int(time.time() // freshness_seconds)
        rng = random.Random(f"{rotation_seed}:{capsule_id}")
    return rng.choice(candidates)


def _init_geocode_cache(conn):
    """Ensure location_names table exists (for databases not yet migrated)."""
    conn.execute("""CREATE TABLE IF NOT EXISTS location_names (
        lat_grid REAL NOT NULL,
        lon_grid REAL NOT NULL,
        city TEXT,
        region TEXT,
        country TEXT,
        display_name TEXT,
        PRIMARY KEY (lat_grid, lon_grid)
    )""")


def geocode_grid(conn, lat, lon, grid_resolution=0.1):
    """Look up or compute a place name for a grid cell. Caches in location_names table.

    Args:
        conn: SQLite connection
        lat: Latitude
        lon: Longitude
        grid_resolution: Grid cell size in degrees (~11km at 0.1°)

    Returns:
        str: Display name like "Paris, France" or "" if unavailable
    """
    lat_grid = round(lat / grid_resolution) * grid_resolution
    lon_grid = round(lon / grid_resolution) * grid_resolution

    # Check cache first
    row = conn.execute(
        "SELECT display_name FROM location_names WHERE lat_grid = ? AND lon_grid = ?",
        [lat_grid, lon_grid],
    ).fetchone()
    if row:
        return row["display_name"] or ""

    # Compute and cache
    try:
        from analyzers.reverse_geocode import reverse_geocode
        name = reverse_geocode(lat_grid, lon_grid)
    except (ImportError, Exception):
        name = ""

    try:
        conn.execute(
            "INSERT OR IGNORE INTO location_names (lat_grid, lon_grid, display_name) VALUES (?, ?, ?)",
            [lat_grid, lon_grid, name],
        )
        conn.commit()
    except Exception:
        pass  # Cache write failure is non-fatal

    return name


def _geocode_centroid(conn, photos):
    """Compute centroid of GPS coordinates and return a place name.

    Args:
        conn: SQLite connection
        photos: List of rows with gps_latitude/gps_longitude

    Returns:
        str: Place name for the centroid, or ""
    """
    lats = [p["gps_latitude"] for p in photos if p["gps_latitude"] is not None]
    lons = [p["gps_longitude"] for p in photos if p["gps_longitude"] is not None]
    if not lats:
        return ""
    return geocode_grid(conn, sum(lats) / len(lats), sum(lons) / len(lons))


def _mmr_select(conn, paths, max_photos, lambda_weight=0.5):
    """Select diverse photos using Maximal Marginal Relevance.

    MMR = λ * quality - (1-λ) * max_cosine_sim(candidate, selected_set)
    Starts with the highest-quality photo, then greedily adds the best MMR candidate.
    """
    if len(paths) <= max_photos:
        return paths

    placeholders = ",".join(["?"] * len(paths))
    rows = conn.execute(
        f"SELECT path, clip_embedding, aggregate FROM photos WHERE path IN ({placeholders})",
        paths,
    ).fetchall()

    path_data = {r["path"]: r for r in rows}

    emb_paths = []
    emb_list = []
    scores = []
    no_emb_paths = []

    for p in paths:
        data = path_data.get(p)
        if data and data["clip_embedding"]:
            emb = bytes_to_normalized_embedding(data["clip_embedding"])
            if emb is not None:
                emb_paths.append(p)
                emb_list.append(emb)
                scores.append(data["aggregate"] or 0)
                continue
        no_emb_paths.append(p)

    if not emb_list:
        return paths[:max_photos]

    # Filter to uniform embedding dimension (CLIP 768 vs SigLIP 1152)
    combined = list(zip(emb_paths, scores))
    emb_list, combined = filter_uniform_embeddings(emb_list, combined)
    if not emb_list:
        return paths[:max_photos]
    emb_paths, scores = zip(*combined)
    emb_paths, scores = list(emb_paths), list(scores)

    emb_matrix = np.stack(emb_list)

    min_score = min(scores)
    max_score = max(scores)
    score_range = max_score - min_score if max_score > min_score else 1.0
    norm_scores = [(s - min_score) / score_range for s in scores]

    n_select = min(max_photos, len(emb_paths))
    selected_indices = []
    remaining = set(range(len(emb_paths)))

    # Start with highest quality
    best_idx = max(remaining, key=lambda i: norm_scores[i])
    selected_indices.append(best_idx)
    remaining.discard(best_idx)

    while len(selected_indices) < n_select and remaining:
        selected_embs = emb_matrix[selected_indices]
        best_mmr = -float('inf')
        best_candidate = None

        for i in remaining:
            quality = norm_scores[i]
            sims = emb_matrix[i] @ selected_embs.T
            max_sim = float(np.max(sims))
            mmr = lambda_weight * quality - (1 - lambda_weight) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_candidate = i

        if best_candidate is not None:
            selected_indices.append(best_candidate)
            remaining.discard(best_candidate)
        else:
            break

    result = [emb_paths[i] for i in selected_indices]
    result.extend(no_emb_paths[:max_photos - len(result)])
    return result


def generate_all_capsules(conn, config=None, user_id=None, date_from=None, date_to=None, shuffle=False):
    """Generate all capsule types and return a combined list.

    Args:
        conn: SQLite connection
        config: Full scoring_config dict
        user_id: Optional user ID for visibility filtering
        date_from: Optional ISO date string (YYYY-MM-DD) for start of range
        date_to: Optional ISO date string (YYYY-MM-DD) for end of range

    Returns:
        list[dict] with keys: type, id, title, subtitle, cover_photo_path,
        photo_count, icon, params
    """
    if config is None:
        config = {}
    capsule_config = {**config.get("capsules", {}), "_shuffle": shuffle}
    min_aggregate = capsule_config.get("min_aggregate", 6.0)

    # Initialize geocoding cache if enabled
    if capsule_config.get("reverse_geocoding", True):
        _init_geocode_cache(conn)

    from api.db_helpers import get_visibility_clause, to_exif_date, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL
    vis_sql, vis_params = get_visibility_clause(user_id)
    vis_params = list(vis_params)
    vis_sql += f" AND {HIDE_BURSTS_SQL} AND {HIDE_DUPLICATES_SQL}"
    if date_from:
        vis_sql += " AND date_taken >= ?"
        vis_params.append(to_exif_date(date_from))
    if date_to:
        vis_sql += " AND date_taken <= ?"
        vis_params.append(to_exif_date(date_to) + " 23:59:59")
    vis = (vis_sql, vis_params)

    capsules = []
    seen_ids = set()

    # Map generator function names to config keys for enable/disable
    _GEN_CONFIG_KEYS = {
        "_generate_journeys": "journey",
        "_generate_faces_of": "faces_of",
        "_generate_seasonal": "seasonal",
        "_generate_golden": "golden",
        "_generate_color_story": "color_story",
        "_generate_this_week": "this_week_years_ago",
        "_generate_location": "location",
        "_generate_person_pairs": "person_pairs",
        "_generate_seeded": "seeded",
        "_generate_progress": "progress",
        "_generate_color_palette": "color_palette",
        "_generate_rare_pairs": "rare_pair",
        "_generate_favorites_by_period": "favorites",
    }

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
        _generate_seeded,
        _generate_progress,
        _generate_color_palette,
        _generate_rare_pairs,
        _generate_favorites_by_period,
    ]

    disabled = set(capsule_config.get("disabled_generators", []))

    for gen in generators:
        cfg_key = _GEN_CONFIG_KEYS.get(gen.__name__, "")
        if cfg_key in disabled:
            logger.debug("Skipping disabled generator: %s", gen.__name__)
            continue
        t0 = time.time()
        try:
            for c in gen(conn, capsule_config, min_aggregate, vis, user_id):
                if c["id"] not in seen_ids:
                    seen_ids.add(c["id"])
                    capsules.append(c)
        except Exception:
            logger.exception("Failed to generate capsules from %s", gen.__name__)
        elapsed = time.time() - t0
        logger.info("  %s: %d capsules in %.1fs", gen.__name__, len(capsules), elapsed)

    # Generic dimension-based capsules (single + cross-dimensional)
    if "dimensions" not in disabled:
        t0 = time.time()
        try:
            for c in _generate_dimension_capsules(conn, capsule_config, min_aggregate, vis, user_id):
                if c["id"] not in seen_ids:
                    seen_ids.add(c["id"])
                    capsules.append(c)
        except Exception:
            logger.exception("Failed to generate dimension capsules")
        logger.info("  _generate_dimension_capsules: %d total in %.1fs", len(capsules), time.time() - t0)

    # Apply MMR diversity to each capsule's photos
    t0 = time.time()
    max_photos = capsule_config.get("max_photos_per_capsule", 40)
    mmr_lambda = capsule_config.get("mmr_lambda", 0.5)
    freshness_seconds = capsule_config.get("freshness_hours", 24) * 3600
    for c in capsules:
        paths = c.get("params", {}).get("paths", [])
        if len(paths) > 5:
            c["params"]["paths"] = _mmr_select(conn, paths, max_photos, mmr_lambda)
            c["photo_count"] = len(c["params"]["paths"])
            c["cover_photo_path"] = _pick_cover_photo(c["params"]["paths"], c["id"],
                                                       freshness_seconds=freshness_seconds,
                                                       capsule_config=capsule_config)
    logger.info("  MMR diversity pass: %.1fs for %d capsules", time.time() - t0, len(capsules))

    # Global dedup: remove capsules whose photos overlap >80% unique with a prior capsule
    max_overlap = capsule_config.get("max_photo_overlap", 0.2)
    capsules = _deduplicate_capsules(capsules, max_overlap)

    # Sort: interleave types, prioritize specialized generators over dimension combos
    capsules = _sort_capsules(capsules, shuffle=shuffle)

    return capsules


# Priority tiers for capsule type sorting (lower = shown first)
_TYPE_PRIORITY = {
    "journey": 0, "faces_of": 0, "golden": 0, "this_week": 0,
    "seeded": 1, "person_pair": 1, "rare_pair": 1, "color_story": 1,
    "progress": 1, "color_palette": 1, "location": 1,
    "seasonal": 2, "year": 2, "category": 2, "star_rating": 2, "favorites": 2,
    "month": 3, "camera": 3, "lens": 3, "composition": 3,
    "focal_range": 3, "time_of_day": 3,
    "tag": 3, "day_of_week": 3, "week": 4,
}


def _sort_capsules(capsules, shuffle=False):
    """Sort capsules: interleave types so no long runs of the same type, prioritize interesting ones."""
    # Assign priority (default 5 for cross-dimensional combos)
    for c in capsules:
        c["_priority"] = _TYPE_PRIORITY.get(c["type"], 5)

    # Group by type
    by_type = defaultdict(list)
    for c in capsules:
        by_type[c["type"]].append(c)

    # Shuffle within each type group when refreshing
    if shuffle:
        for items in by_type.values():
            random.shuffle(items)

    # Round-robin interleave: take one from each type in priority order, repeat
    sorted_types = sorted(by_type.keys(), key=lambda t: _TYPE_PRIORITY.get(t, 5))
    result = []
    queues = {t: list(by_type[t]) for t in sorted_types}

    while any(queues.values()):
        for t in sorted_types:
            if queues.get(t):
                result.append(queues[t].pop(0))

    # Clean up internal key
    for c in result:
        c.pop("_priority", None)

    return result


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

    geo_enabled = capsule_config.get("reverse_geocoding", True)

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

        photo_paths = [p["path"] for p in trip[:max_photos]]

        # Reverse geocode trip centroid for destination name
        destination = _geocode_centroid(conn, trip) if geo_enabled else ""

        if destination:
            title_key = "capsules.journey_title_destination"
            title_params = {"destination": destination, "date": title_date}
            title = f"Journey to {destination} \u2014 {title_date}"
        else:
            title_key = "capsules.journey_title"
            title_params = {"date": title_date}
            title = f"Journey \u2014 {title_date}"

        capsules.append({
            "type": "journey",
            "id": f"journey_{trip_id}",
            "title_key": title_key,
            "title_params": title_params,
            "title": title,
            "subtitle": f"{len(photo_paths)} photos",
            "cover_photo_path": _pick_cover_photo(photo_paths, f"journey_{trip_id}", capsule_config=capsule_config),
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
    vis_sql += (" AND (ph.is_burst_lead = 1 OR ph.is_burst_lead IS NULL)"
                " AND (ph.is_duplicate_lead = 1 OR ph.is_duplicate_lead IS NULL"
                " OR ph.duplicate_group_id IS NULL)")

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
            "cover_photo_path": _pick_cover_photo(unique_paths, f"faces_{pid}", capsule_config=capsule_config),
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

        paths = [p["path"] for p in photos]
        cid = f"seasonal_{capsule_id}"
        capsules.append({
            "type": "seasonal",
            "id": cid,
            "title_key": "capsules.seasonal_title",
            "title_params": {"season": season, "year": str(year)},
            "title": f"{season_title} {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, cid, capsule_config=capsule_config),
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
        "cover_photo_path": _pick_cover_photo(paths, "golden", capsule_config=capsule_config),
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

    # Filter to uniform embedding dimension (CLIP 768 vs SigLIP 1152)
    embeddings, valid_photos = filter_uniform_embeddings(embeddings, valid_photos)

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
        cid = _stable_id("color", *paths[:3])
        full_id = f"color_{cid}"

        capsules.append({
            "type": "color_story",
            "id": full_id,
            "title_key": "capsules.color_story_title",
            "title_params": {"name": name},
            "title": name,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
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
           WHERE strftime('%m-%d', {_ISO_DATE}) IN ({placeholders})
             AND CAST(strftime('%Y', {_ISO_DATE}) AS INTEGER) < ?
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

        capsules.append({
            "type": "this_week",
            "id": f"thisweek_{year}",
            "title_key": "capsules.this_week_title",
            "title_params": {"year": str(year)},
            "title": f"This Week in {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, f"thisweek_{year}", capsule_config=capsule_config),
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
        # Reverse geocode grid cell center, fallback to coordinates
        geo_enabled = capsule_config.get("reverse_geocoding", True)
        place_name = geocode_grid(conn, lat, lon) if geo_enabled else ""
        title = place_name or f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}"
        cid = _stable_id("loc", f"{lat:.2f}", f"{lon:.2f}")
        full_id = f"loc_{cid}"
        capsules.append({
            "type": "location",
            "id": full_id,
            "title_key": "capsules.location_title",
            "title_params": {"location": title},
            "title": title,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
            "photo_count": len(paths),
            "icon": "location_on",
            "params": {"paths": paths},
        })

    return capsules


def _fetch_person_pairs(conn, min_score, vis_sql, vis_params, max_photos):
    """Query person pairs co-appearing in photos. Returns {(pid1,pid2): (name1, name2, [paths])}."""
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
           ORDER BY ph.aggregate DESC
           LIMIT 10000""",
        [min_score] + vis_params,
    ).fetchall()

    groups = defaultdict(list)
    pair_names = {}
    for r in rows:
        key = (r["pid1"], r["pid2"])
        pair_names[key] = (r["name1"], r["name2"])
        if len(groups[key]) < max_photos:
            groups[key].append(r["photo_path"])

    return {k: (pair_names[k][0], pair_names[k][1], list(dict.fromkeys(v)))
            for k, v in groups.items()}


def _generate_person_pairs(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate capsules for pairs of named persons appearing together."""
    cfg = capsule_config.get("person_pairs", {})
    min_photos = cfg.get("min_photos", 8)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    from api.db_helpers import get_visibility_clause
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='ph')
    vis_sql += (" AND (ph.is_burst_lead = 1 OR ph.is_burst_lead IS NULL)"
                " AND (ph.is_duplicate_lead = 1 OR ph.is_duplicate_lead IS NULL"
                " OR ph.duplicate_group_id IS NULL)")

    pairs = _fetch_person_pairs(conn, min_aggregate, vis_sql, vis_params, max_photos)

    capsules = []
    for (pid1, pid2), (name1, name2, unique_paths) in pairs.items():
        if len(unique_paths) < min_photos:
            continue

        cid = _stable_id("pair", str(pid1), str(pid2))
        full_id = f"pair_{cid}"
        capsules.append({
            "type": "person_pair",
            "id": full_id,
            "title_key": "capsules.person_pair_title",
            "title_params": {"name1": name1, "name2": name2},
            "title": f"{name1} & {name2}",
            "subtitle": f"{len(unique_paths)} photos",
            "cover_photo_path": _pick_cover_photo(unique_paths, full_id, capsule_config=capsule_config),
            "photo_count": len(unique_paths),
            "icon": "group",
            "params": {"paths": unique_paths},
        })

    return capsules


def _generate_seeded(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate seed-based discovery capsules — stable within a time window."""
    cfg = capsule_config.get("seeded", {})
    num_seeds = cfg.get("num_seeds", 10)
    min_photos = cfg.get("min_photos", 8)
    seed_lifetime_minutes = cfg.get("seed_lifetime_minutes", 1440)
    time_window_days = cfg.get("time_window_days", 7)
    embedding_threshold = cfg.get("embedding_threshold", 0.7)
    location_radius_km = cfg.get("location_radius_km", 30)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    # Align seed lifetime to freshness if not explicitly configured
    freshness_hours = capsule_config.get("freshness_hours", 24)
    if "seed_lifetime_minutes" not in cfg:
        seed_lifetime_minutes = freshness_hours * 60

    # Local RNG with time-bucketed seed for stability (avoids mutating global state)
    if capsule_config.get("_shuffle"):
        rng = random.Random()
    else:
        rng = random.Random(int(time.time() // (seed_lifetime_minutes * 60)))

    # Fetch candidate high-scoring photos
    rows = conn.execute(
        f"""SELECT path, date_taken, aggregate, gps_latitude, gps_longitude,
               mean_saturation, is_monochrome, clip_embedding, tags
           FROM photos
           WHERE aggregate >= ? AND {vis_sql}
           ORDER BY aggregate DESC
           LIMIT 2000""",
        [min_aggregate] + vis_params,
    ).fetchall()

    if not rows:
        return []

    # Pre-decode embeddings once for vectorized similarity (avoids per-seed reload)
    _emb_list = []
    _emb_indices = []  # maps emb_matrix row → rows index
    for ri, r in enumerate(rows):
        emb = bytes_to_normalized_embedding(r["clip_embedding"])
        if emb is not None:
            _emb_list.append(emb)
            _emb_indices.append(ri)
    # Filter to uniform embedding dimension (CLIP 768 vs SigLIP 1152)
    _emb_list, _emb_indices = filter_uniform_embeddings(_emb_list, _emb_indices)
    _emb_paths = [rows[i]["path"] for i in _emb_indices]
    emb_matrix = np.stack(_emb_list) if _emb_list else None

    # Pick seed indices deterministically
    seed_indices = rng.sample(range(len(rows)), min(num_seeds, len(rows)))

    capsules = []
    for idx in seed_indices:
        seed = rows[idx]
        seed_path = seed["path"]
        best_axis = None
        best_photos = []
        best_score = 0

        # --- Time neighborhood axis ---
        seed_dt = _parse_date(seed["date_taken"])
        if seed_dt:
            window_start = seed_dt - timedelta(days=time_window_days)
            window_end = seed_dt + timedelta(days=time_window_days)
            start_str = window_start.strftime("%Y:%m:%d %H:%M:%S")
            end_str = window_end.strftime("%Y:%m:%d %H:%M:%S")
            time_rows = conn.execute(
                f"""SELECT path, aggregate
                   FROM photos
                   WHERE date_taken BETWEEN ? AND ?
                     AND path != ? AND aggregate >= ? AND {vis_sql}
                   ORDER BY aggregate DESC
                   LIMIT ?""",
                [start_str, end_str, seed_path, min_aggregate] + vis_params + [max_photos],
            ).fetchall()
            if time_rows:
                avg_agg = sum(r["aggregate"] for r in time_rows) / len(time_rows)
                score = len(time_rows) * avg_agg
                if score > best_score:
                    best_score = score
                    best_photos = time_rows
                    if seed_dt:
                        title_date = seed_dt.strftime("%B %Y")
                    best_axis = ("time", {"date": title_date})

        # --- Visual similarity axis (vectorized, uses pre-loaded matrix) ---
        seed_emb = bytes_to_normalized_embedding(seed["clip_embedding"])
        if seed_emb is not None and emb_matrix is not None:
            sims = emb_matrix @ seed_emb  # vectorized cosine similarity
            mask = sims >= embedding_threshold
            similar_idx = np.where(mask)[0]
            if len(similar_idx) > 0:
                # Sort by similarity desc, take top max_photos, exclude seed
                order = np.argsort(-sims[similar_idx])[:max_photos + 1]
                similar = []
                for oi in order:
                    ri = _emb_indices[similar_idx[oi]]
                    r = rows[ri]
                    if r["path"] != seed_path:
                        similar.append(r)
                        if len(similar) >= max_photos:
                            break
                if similar:
                    avg_agg = sum(r["aggregate"] for r in similar) / len(similar)
                    score = len(similar) * avg_agg
                    if score > best_score:
                        best_score = score
                        best_photos = similar
                        best_axis = ("similar", {})

        # --- Same person axis ---
        person_rows = conn.execute(
            f"""SELECT DISTINCT f.photo_path AS path, p.aggregate
               FROM faces f
               JOIN photos p ON p.path = f.photo_path
               WHERE f.person_id IN (SELECT person_id FROM faces WHERE photo_path = ?)
                 AND f.photo_path != ?
                 AND p.aggregate >= ? AND {vis_sql}
               ORDER BY p.aggregate DESC
               LIMIT ?""",
            [seed_path, seed_path, min_aggregate] + vis_params + [max_photos],
        ).fetchall()
        if person_rows:
            # Get person name for title
            name_row = conn.execute(
                """SELECT p.name FROM persons p
                   JOIN faces f ON f.person_id = p.id
                   WHERE f.photo_path = ? AND p.name IS NOT NULL AND p.name != ''
                   LIMIT 1""",
                [seed_path],
            ).fetchone()
            avg_agg = sum(r["aggregate"] for r in person_rows) / len(person_rows)
            score = len(person_rows) * avg_agg
            if score > best_score:
                best_score = score
                best_photos = person_rows
                person_name = name_row["name"] if name_row else "Unknown"
                best_axis = ("person", {"name": person_name})

        # --- Same tags axis ---
        tag_list = _parse_tags(seed["tags"] or "")
        if tag_list:
            top_tag = tag_list[0]
            tag_rows = conn.execute(
                f"""SELECT DISTINCT pt.photo_path AS path, p.aggregate
                   FROM photo_tags pt
                   JOIN photos p ON p.path = pt.photo_path
                   WHERE pt.tag = ? AND pt.photo_path != ?
                     AND p.aggregate >= ? AND {vis_sql}
                   ORDER BY p.aggregate DESC
                   LIMIT ?""",
                [top_tag, seed_path, min_aggregate] + vis_params + [max_photos],
            ).fetchall()
            if tag_rows:
                avg_agg = sum(r["aggregate"] for r in tag_rows) / len(tag_rows)
                score = len(tag_rows) * avg_agg
                if score > best_score:
                    best_score = score
                    best_photos = tag_rows
                    best_axis = ("tag", {"tag": top_tag.title()})

        # --- Same location axis ---
        seed_lat = seed["gps_latitude"]
        seed_lon = seed["gps_longitude"]
        if seed_lat is not None and seed_lon is not None:
            # Rough bounding box
            deg_delta = location_radius_km / 111.0
            loc_rows = conn.execute(
                f"""SELECT path, aggregate, gps_latitude, gps_longitude
                   FROM photos
                   WHERE gps_latitude BETWEEN ? AND ?
                     AND gps_longitude BETWEEN ? AND ?
                     AND path != ? AND aggregate >= ? AND {vis_sql}
                   ORDER BY aggregate DESC
                   LIMIT ?""",
                [seed_lat - deg_delta, seed_lat + deg_delta,
                 seed_lon - deg_delta, seed_lon + deg_delta,
                 seed_path, min_aggregate] + vis_params + [max_photos * 2],
            ).fetchall()
            # Precise haversine filter
            nearby = [r for r in loc_rows
                      if _haversine_km(seed_lat, seed_lon, r["gps_latitude"], r["gps_longitude"]) <= location_radius_km]
            nearby = nearby[:max_photos]
            if nearby:
                avg_agg = sum(r["aggregate"] for r in nearby) / len(nearby)
                score = len(nearby) * avg_agg
                if score > best_score:
                    best_score = score
                    best_photos = nearby
                    # Reverse geocode seed location for title
                    geo_enabled = capsule_config.get("reverse_geocoding", True)
                    place = geocode_grid(conn, seed_lat, seed_lon) if geo_enabled else ""
                    best_axis = ("location", {"place": place} if place else {})

        # --- Color mood axis ---
        seed_sat = seed["mean_saturation"]
        seed_mono = seed["is_monochrome"]
        if seed_sat is not None:
            mood_rows = conn.execute(
                f"""SELECT path, aggregate
                   FROM photos
                   WHERE mean_saturation BETWEEN ? AND ?
                     AND is_monochrome = ?
                     AND path != ? AND aggregate >= ? AND {vis_sql}
                   ORDER BY aggregate DESC
                   LIMIT ?""",
                [seed_sat - 0.1, seed_sat + 0.1,
                 seed_mono or 0, seed_path, min_aggregate] + vis_params + [max_photos],
            ).fetchall()
            if mood_rows:
                avg_agg = sum(r["aggregate"] for r in mood_rows) / len(mood_rows)
                score = len(mood_rows) * avg_agg
                if score > best_score:
                    best_score = score
                    best_photos = mood_rows
                    best_axis = ("mood", {})

        # Build capsule from best axis
        if best_axis is None or len(best_photos) < min_photos:
            continue

        axis_type, axis_params = best_axis
        paths = [seed_path] + [r["path"] for r in best_photos if r["path"] != seed_path]
        paths = list(dict.fromkeys(paths))[:max_photos]

        title_key_map = {
            "time": "capsules.seeded_time_title",
            "similar": "capsules.seeded_similar_title",
            "person": "capsules.seeded_person_title",
            "tag": "capsules.seeded_tag_title",
            "location": "capsules.seeded_location_title",
            "mood": "capsules.seeded_mood_title",
        }
        title_map = {
            "time": f"Around {axis_params.get('date', '')}",
            "similar": "Visually Similar",
            "person": f"More of {axis_params.get('name', '')}",
            "tag": f"{axis_params.get('tag', '')} Collection",
            "location": f"Near {axis_params.get('place', '')}" if axis_params.get('place') else "Nearby Places",
            "mood": "Color Mood",
        }

        cid = _stable_id("seeded", axis_type, seed_path)
        full_id = f"seeded_{cid}"
        capsules.append({
            "type": "seeded",
            "id": full_id,
            "title_key": title_key_map[axis_type],
            "title_params": axis_params,
            "title": title_map[axis_type],
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
            "photo_count": len(paths),
            "icon": "auto_awesome",
            "params": {"paths": paths},
        })

    return capsules


def _generate_progress(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate 'Your Photography is Improving' capsule from quarterly score trends."""
    cfg = capsule_config.get("progress", {})
    min_improvement_pct = cfg.get("min_improvement_pct", 5)
    min_photos = cfg.get("min_photos", 10)
    period_months = cfg.get("period_months", 3)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    # Get average aggregate per quarter
    rows = conn.execute(
        f"""SELECT
               CAST(strftime('%Y', {_ISO_DATE}) AS INTEGER) AS yr,
               (CAST(strftime('%m', {_ISO_DATE}) AS INTEGER) - 1) / {period_months} AS qtr,
               AVG(aggregate) AS avg_agg,
               COUNT(*) AS cnt
           FROM photos
           WHERE aggregate IS NOT NULL AND date_taken IS NOT NULL AND {vis_sql}
           GROUP BY yr, qtr
           HAVING cnt >= ?
           ORDER BY yr ASC, qtr ASC""",
        vis_params + [min_photos],
    ).fetchall()

    if len(rows) < 2:
        return []

    # Check if most recent quarter improved over the previous
    recent = rows[-1]
    previous = rows[-2]
    if previous["avg_agg"] <= 0:
        return []

    improvement = (recent["avg_agg"] - previous["avg_agg"]) / previous["avg_agg"] * 100
    if improvement < min_improvement_pct:
        return []

    # Fetch best photos from the improving period
    recent_yr = recent["yr"]
    recent_qtr = recent["qtr"]
    month_start = recent_qtr * period_months + 1
    month_end = month_start + period_months

    best_photos = conn.execute(
        f"""SELECT path, aggregate
           FROM photos
           WHERE CAST(strftime('%Y', {_ISO_DATE}) AS INTEGER) = ?
             AND CAST(strftime('%m', {_ISO_DATE}) AS INTEGER) >= ?
             AND CAST(strftime('%m', {_ISO_DATE}) AS INTEGER) < ?
             AND aggregate IS NOT NULL AND {vis_sql}
           ORDER BY aggregate DESC
           LIMIT ?""",
        [recent_yr, month_start, month_end] + vis_params + [max_photos],
    ).fetchall()

    if len(best_photos) < min_photos:
        return []

    paths = [r["path"] for r in best_photos]
    cid = _stable_id("progress", str(recent_yr), str(recent_qtr))
    full_id = f"progress_{cid}"

    return [{
        "type": "progress",
        "id": full_id,
        "title_key": "capsules.progress_title",
        "title_params": {},
        "title": "Your Photography is Improving",
        "subtitle": f"{len(paths)} photos",
        "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
        "photo_count": len(paths),
        "icon": "trending_up",
        "params": {"paths": paths},
    }]


def _generate_color_palette(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate 'Color of the Month' capsules from saturation/monochrome profiles."""
    cfg = capsule_config.get("color_palette", {})
    min_photos = cfg.get("min_photos", 8)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    # Get monthly color profiles — fetch paths with GROUP_CONCAT to avoid per-month queries
    max_months = cfg.get("max_months", 24)
    rows = conn.execute(
        f"""SELECT month_key, avg_sat, mono_ratio, cnt, paths FROM (
            SELECT strftime('%Y-%m', {_ISO_DATE}) AS month_key,
                   AVG(mean_saturation) AS avg_sat,
                   AVG(CASE WHEN is_monochrome = 1 THEN 1.0 ELSE 0.0 END) AS mono_ratio,
                   COUNT(*) AS cnt,
                   GROUP_CONCAT(path, '||') AS paths
            FROM (
                SELECT path, mean_saturation, is_monochrome, date_taken
                FROM photos
                WHERE mean_saturation IS NOT NULL AND date_taken IS NOT NULL
                  AND aggregate >= ? AND {vis_sql}
                ORDER BY aggregate DESC
            )
            GROUP BY month_key
            HAVING cnt >= ?
            ORDER BY month_key DESC
            LIMIT ?
        )""",
        [min_aggregate] + vis_params + [min_photos, max_months],
    ).fetchall()

    capsules = []
    for row in rows:
        month_key = row["month_key"]
        avg_sat = row["avg_sat"]
        mono_ratio = row["mono_ratio"]

        # Determine mood
        if mono_ratio > 0.5:
            mood = "Monochrome"
        elif avg_sat > 0.5:
            mood = "Vibrant"
        elif avg_sat < 0.25:
            mood = "Muted"
        else:
            continue  # No distinctive profile

        paths = (row["paths"] or "").split("||")[:max_photos]
        if len(paths) < min_photos:
            continue
        cid = _stable_id("color_palette", month_key, mood)
        full_id = f"color_palette_{cid}"

        capsules.append({
            "type": "color_palette",
            "id": full_id,
            "title_key": "capsules.color_palette_title",
            "title_params": {"mood": mood, "date": month_key},
            "title": f"{mood} \u2014 {month_key}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
            "photo_count": len(paths),
            "icon": "palette",
            "params": {"paths": paths},
        })

    return capsules


def _generate_rare_pairs(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate 'Unexpected Together' capsules for rare person pairs."""
    cfg = capsule_config.get("rare_pair", {})
    max_shared_photos = cfg.get("max_shared_photos", 5)
    min_score = cfg.get("min_score", 7.0)
    min_photos = cfg.get("min_photos", 3)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    from api.db_helpers import get_visibility_clause
    vis_sql, vis_params = get_visibility_clause(user_id, table_alias='ph')
    vis_sql += (" AND (ph.is_burst_lead = 1 OR ph.is_burst_lead IS NULL)"
                " AND (ph.is_duplicate_lead = 1 OR ph.is_duplicate_lead IS NULL"
                " OR ph.duplicate_group_id IS NULL)")

    pairs = _fetch_person_pairs(conn, min_score, vis_sql, vis_params, max_photos)

    capsules = []
    for (pid1, pid2), (name1, name2, unique_paths) in pairs.items():
        if len(unique_paths) < min_photos or len(unique_paths) > max_shared_photos:
            continue

        cid = _stable_id("rare_pair", str(pid1), str(pid2))
        full_id = f"rare_pair_{cid}"
        capsules.append({
            "type": "rare_pair",
            "id": full_id,
            "title_key": "capsules.rare_pair_title",
            "title_params": {"name1": name1, "name2": name2},
            "title": f"{name1} & {name2} \u2014 Rare Moment",
            "subtitle": f"{len(unique_paths)} photos",
            "cover_photo_path": _pick_cover_photo(unique_paths, full_id, capsule_config=capsule_config),
            "photo_count": len(unique_paths),
            "icon": "people_outline",
            "params": {"paths": unique_paths},
        })

    return capsules


def _generate_favorites_by_period(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate 'Favorites of [Period]' capsules — favorited photos grouped by year and season."""
    cfg = capsule_config.get("favorites", {})
    min_photos = cfg.get("min_photos", 5)
    max_photos = capsule_config.get("max_photos_per_capsule", 40)

    vis_sql, vis_params = vis

    # Resolve is_favorite column based on multi-user mode
    from api.config import is_multi_user_enabled
    if user_id and is_multi_user_enabled():
        fav_join = "JOIN user_preferences up ON up.photo_path = photos.path AND up.user_id = ?"
        fav_filter = "up.is_favorite = 1"
        fav_params = [user_id]
    else:
        fav_join = ""
        fav_filter = "photos.is_favorite = 1"
        fav_params = []

    rows = conn.execute(
        f"""SELECT path, date_taken, aggregate
           FROM photos {fav_join}
           WHERE {fav_filter} AND date_taken IS NOT NULL AND {vis_sql}
           ORDER BY aggregate DESC""",
        fav_params + vis_params,
    ).fetchall()

    if not rows:
        return []

    # Group by year
    year_groups = defaultdict(list)
    # Group by season + year
    season_groups = defaultdict(list)

    for r in rows:
        dt = _parse_date(r["date_taken"])
        if not dt:
            continue
        year_groups[dt.year].append(r)
        season = _month_to_season(dt.month)
        year = dt.year if not (season == "winter" and dt.month == 12) else dt.year + 1
        season_groups[(season, year)].append(r)

    capsules = []

    # Yearly favorites
    for year in sorted(year_groups.keys(), reverse=True):
        photos = year_groups[year]
        if len(photos) < min_photos:
            continue

        paths = [p["path"] for p in photos[:max_photos]]
        cid = _stable_id("fav_year", str(year))
        full_id = f"fav_year_{cid}"
        capsules.append({
            "type": "favorites",
            "id": full_id,
            "title_key": "capsules.favorites_year_title",
            "title_params": {"year": str(year)},
            "title": f"Favorites of {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
            "photo_count": len(paths),
            "icon": "favorite",
            "params": {"paths": paths},
        })

    # Seasonal favorites (only when there are enough)
    for (season, year), photos in sorted(season_groups.items(), key=lambda x: (-x[0][1], x[0][0])):
        if len(photos) < min_photos:
            continue

        paths = [p["path"] for p in photos[:max_photos]]
        cid = _stable_id("fav_season", season, str(year))
        full_id = f"fav_season_{cid}"
        capsules.append({
            "type": "favorites",
            "id": full_id,
            "title_key": "capsules.favorites_season_title",
            "title_params": {"season": season, "year": str(year)},
            "title": f"Favorites — {season.title()} {year}",
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
            "photo_count": len(paths),
            "icon": "favorite",
            "params": {"paths": paths},
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
        group_rows = conn.execute(  # lgtm[py/sql-injection]
            f"""SELECT dim_val, dim_label, cnt, paths FROM (
                SELECT {expr} AS dim_val, {label_expr} AS dim_label,
                       COUNT(*) AS cnt,
                       GROUP_CONCAT(path, '||') AS paths
                FROM (
                    SELECT path, {expr}, {label_expr}
                    FROM photos {join}
                    WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                    ORDER BY {sort}
                )
                GROUP BY dim_val
                HAVING cnt >= ?
                ORDER BY cnt DESC
                LIMIT 20
            )""",
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

        paths = list(dict.fromkeys((gr["paths"] or "").split("||")[:max_photos]))
        if len(paths) < min_photos_score:
            continue

        cid = _stable_id(cfg_key, str(val))
        full_id = f"{cfg_key}_{cid}"
        title = f"{score_label}: {display}"
        capsules.append({
            "type": cfg_key,
            "id": full_id,
            "title_key": "capsules.score_per_dim_title",
            "title_params": {"score": score_label, "dimension": display},
            "title": title,
            "subtitle": f"{len(paths)} photos",
            "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
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
    "composition": {
        "sql_expr": "composition_pattern",
        "filter": "composition_pattern IS NOT NULL AND composition_pattern != ''",
        "icon": "grid_on",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.composition_title",
        "param_name": "pattern",
        "title_transform": lambda s: s.replace("_", " ").title(),
    },
    "focal_range": {
        "sql_expr": """CASE
            WHEN focal_length < 24 THEN 'ultra_wide'
            WHEN focal_length BETWEEN 24 AND 35 THEN 'wide'
            WHEN focal_length BETWEEN 36 AND 70 THEN 'normal'
            WHEN focal_length BETWEEN 71 AND 135 THEN 'portrait'
            WHEN focal_length BETWEEN 136 AND 300 THEN 'telephoto'
            WHEN focal_length > 300 THEN 'super_telephoto'
            END""",
        "filter": "focal_length IS NOT NULL AND focal_length > 0",
        "icon": "straighten",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.focal_range_title",
        "param_name": "range",
        "value_map": {
            "ultra_wide": "Ultra Wide (<24mm)",
            "wide": "Wide (24\u201335mm)",
            "normal": "Standard (36\u201370mm)",
            "portrait": "Portrait (71\u2013135mm)",
            "telephoto": "Telephoto (136\u2013300mm)",
            "super_telephoto": "Super Telephoto (300mm+)",
        },
    },
    "category": {
        "sql_expr": "category",
        "filter": "category IS NOT NULL AND category != ''",
        "icon": "category",
        "min_photos": 15,
        "title_tpl": "{value}",
        "title_key": "capsules.category_title",
        "param_name": "category",
        "title_transform": lambda s: s.replace("_", " ").title(),
    },
    "time_of_day": {
        "sql_expr": f"""CASE
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 5 AND 7 THEN 'golden_morning'
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 8 AND 10 THEN 'morning'
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 11 AND 14 THEN 'midday'
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 15 AND 17 THEN 'afternoon'
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 18 AND 20 THEN 'golden_evening'
            WHEN CAST(SUBSTR({_ISO_DATE}, 12, 2) AS INTEGER) BETWEEN 21 AND 23 THEN 'night'
            ELSE 'night'
            END""",
        "filter": "date_taken IS NOT NULL AND LENGTH(date_taken) > 10",
        "icon": "schedule",
        "min_photos": 15,
        "title_tpl": "Best of {value}",
        "title_key": "capsules.time_of_day_title",
        "param_name": "time",
        "value_map": {
            "golden_morning": "Golden Morning",
            "morning": "Morning Light",
            "midday": "Midday",
            "afternoon": "Afternoon",
            "golden_evening": "Golden Evening",
            "night": "Night",
        },
    },
    "star_rating": {
        "sql_expr": "star_rating",
        "filter": "star_rating IS NOT NULL AND star_rating > 0",
        "icon": "star",
        "min_photos": 10,
        "title_tpl": "{value}",
        "title_key": "capsules.star_rating_title",
        "param_name": "stars",
        "value_map": {
            5: "\u2605\u2605\u2605\u2605\u2605",
            4: "\u2605\u2605\u2605\u2605",
            3: "\u2605\u2605\u2605",
            2: "\u2605\u2605",
            1: "\u2605",
        },
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
    # Composition crosses
    ("composition", "camera"),
    ("composition", "year"),
    # Focal range crosses
    ("focal_range", "category"),
    ("focal_range", "year"),
    # Category crosses
    ("category", "year"),
    ("category", "camera"),
]


def _generate_dimension_capsules(conn, capsule_config, min_aggregate, vis, user_id):
    """Generate capsules from single dimensions and cross-dimensional combos.

    Uses GROUP_CONCAT to fetch paths in a single query per dimension (avoids
    one query per group value).  Respects a total capsule budget to avoid
    unbounded generation time on large databases.
    """
    from api.db_helpers import is_photo_tags_available
    has_tags = is_photo_tags_available()

    vis_sql, vis_params = vis
    max_photos = capsule_config.get("max_photos_per_capsule", 40)
    budget = capsule_config.get("max_dimension_capsules", 200)
    capsules = []

    def _budget_left():
        return len(capsules) < budget

    # --- Single-dimension capsules ---
    for dim_name, dim in _DIMENSIONS.items():
        if not _budget_left():
            break
        if dim.get("skip_single"):
            continue
        if dim.get("requires") == "photo_tags" and not has_tags:
            continue

        cfg = capsule_config.get(dim_name, {})
        min_photos = cfg.get("min_photos", dim.get("min_photos", 10))

        if dim.get("single_only"):
            sort = dim.get("sort_override", "aggregate DESC")
            extra_filter = f"AND {dim['filter']}" if dim.get("filter") else ""
            rows = conn.execute(  # lgtm[py/sql-injection]
                f"""SELECT path FROM photos
                   WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                   ORDER BY {sort} LIMIT ?""",
                [min_aggregate] + vis_params + [max_photos],
            ).fetchall()
            if len(rows) >= min_photos:
                paths = [r["path"] for r in rows]
                capsules.append({
                    "type": dim_name, "id": dim_name,
                    "title_key": dim["title_key"],
                    "title_params": {dim["param_name"]: dim["title_tpl"]},
                    "title": dim["title_tpl"],
                    "subtitle": f"{len(paths)} photos",
                    "cover_photo_path": _pick_cover_photo(paths, dim_name, capsule_config=capsule_config),
                    "photo_count": len(paths), "icon": dim["icon"],
                    "params": {"paths": paths},
                })
            continue

        # Grouped dimension — single query with GROUP_CONCAT for paths
        join = dim.get("join", "")
        sql_expr = dim["sql_expr"]
        label_expr = dim.get("label_expr", sql_expr)
        extra_filter = f"AND {dim['filter']}" if dim.get("filter") else ""
        junk_fn = dim.get("junk_filter")
        value_map = dim.get("value_map")
        title_transform = dim.get("title_transform")

        # Subquery: rank photos within each group by aggregate, take top N
        # GROUP_CONCAT on the top-ranked paths avoids per-group queries
        try:
            group_rows = conn.execute(  # lgtm[py/sql-injection]
                f"""SELECT dim_val, dim_label, cnt, paths FROM (
                    SELECT {sql_expr} AS dim_val, {label_expr} AS dim_label,
                           COUNT(*) AS cnt,
                           GROUP_CONCAT(path, '||') AS paths
                    FROM (
                        SELECT path, {sql_expr}, {label_expr}
                        FROM photos {join}
                        WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                        ORDER BY aggregate DESC
                    )
                    GROUP BY dim_val
                    HAVING cnt >= ?
                    ORDER BY cnt DESC
                    LIMIT 30
                )""",
                [min_aggregate] + vis_params + [min_photos],
            ).fetchall()
        except Exception:
            logger.debug("Single-dimension %s query failed", dim_name, exc_info=True)
            continue

        for gr in group_rows:
            if not _budget_left():
                break
            val = gr["dim_val"]
            label = gr["dim_label"]
            if val is None:
                continue
            if junk_fn and junk_fn(str(val)):
                continue

            display = value_map.get(val, label) if value_map else (str(label) if label else str(val))
            if title_transform:
                display = title_transform(display)

            paths = (gr["paths"] or "").split("||")[:max_photos]
            if len(paths) < min_photos:
                continue

            cid = _stable_id(dim_name, str(val))
            full_id = f"{dim_name}_{cid}"
            capsules.append({
                "type": dim_name, "id": full_id,
                "title_key": dim["title_key"],
                "title_params": {dim["param_name"]: display},
                "title": display,
                "subtitle": f"{len(paths)} photos",
                "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
                "photo_count": len(paths), "icon": dim["icon"],
                "params": {"paths": paths},
            })

    # --- Cross-dimensional capsules ---
    for dim_a_name, dim_b_name in _CROSS_DIMENSIONS:
        if not _budget_left():
            break
        dim_a = _DIMENSIONS.get(dim_a_name)
        dim_b = _DIMENSIONS.get(dim_b_name)
        if not dim_a or not dim_b:
            continue
        if (dim_a.get("requires") == "photo_tags" or dim_b.get("requires") == "photo_tags") and not has_tags:
            continue

        score_dim = dim_a if dim_a.get("is_score") else (dim_b if dim_b.get("is_score") else None)
        group_dim = dim_b if dim_a.get("is_score") else (dim_a if dim_b.get("is_score") else None)

        if score_dim and not group_dim:
            continue
        if score_dim:
            _generate_score_per_dim(
                conn, capsules, capsule_config, min_aggregate, vis_sql, vis_params,
                max_photos, has_tags, dim_a_name, dim_b_name, score_dim, group_dim,
            )
            continue

        if dim_a.get("single_only") or dim_b.get("single_only"):
            continue

        cfg_key = f"{dim_a_name}_{dim_b_name}"
        cfg = capsule_config.get(cfg_key, {})
        min_photos_cross = cfg.get("min_photos", max(dim_a.get("min_photos", 10), dim_b.get("min_photos", 10)) // 2)
        min_photos_cross = max(min_photos_cross, 5)

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
            group_rows = conn.execute(  # lgtm[py/sql-injection]
                f"""SELECT val_a, lbl_a, val_b, lbl_b, cnt, paths FROM (
                    SELECT {expr_a} AS val_a, {label_a} AS lbl_a,
                           {expr_b} AS val_b, {label_b} AS lbl_b,
                           COUNT(*) AS cnt,
                           GROUP_CONCAT(path, '||') AS paths
                    FROM (
                        SELECT path, {expr_a}, {label_a}, {expr_b}, {label_b}
                        FROM photos {join_clause}
                        WHERE aggregate >= ? {extra_filter} AND {vis_sql}
                        ORDER BY aggregate DESC
                    )
                    GROUP BY val_a, val_b
                    HAVING cnt >= ?
                    ORDER BY cnt DESC
                    LIMIT 20
                )""",
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
            if not _budget_left():
                break
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

            paths = list(dict.fromkeys((gr["paths"] or "").split("||")[:max_photos]))
            if len(paths) < min_photos_cross:
                continue

            cid = _stable_id(cfg_key, str(va), str(vb))
            full_id = f"{cfg_key}_{cid}"
            title = f"{disp_a} \u2014 {disp_b}"
            capsules.append({
                "type": cfg_key, "id": full_id,
                "title_key": "capsules.cross_title",
                "title_params": {"a": disp_a, "b": disp_b},
                "title": title,
                "subtitle": f"{len(paths)} photos",
                "cover_photo_path": _pick_cover_photo(paths, full_id, capsule_config=capsule_config),
                "photo_count": len(paths), "icon": dim_a["icon"],
                "params": {"paths": paths},
            })

    return capsules
