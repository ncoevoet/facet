# Test fixtures — building a photos table that can actually fail

Consult before writing a test that needs photo rows. Every rule here comes from a
fixture that made a real test stop testing without turning red.

## Never hand-roll `CREATE TABLE photos`

```python
# WRONG — the test still passes, it just stops testing
conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT, aggregate REAL)")
```

`api/db_helpers.build_photo_select_columns` composes its SELECT at query time from
`PHOTO_BASE_COLS ∪ (PHOTO_OPTIONAL_COLS ∩ the columns this database actually has)`. A
fixture missing a column therefore makes the endpoint **legitimately** omit that field,
and any assertion about it passes for the wrong reason.

```python
from db.schema import init_database
init_database(db_path)          # the real schema, all 50 optional columns
```

Three suites had done it the wrong way. One omitted 39 of 50 optional columns, so no
gallery test could see a serialisation regression on `caption`, `gps_latitude`, any
`form_*` facet, `narrative_moment` or the whole extended-IQA block. Two more raised
`sqlite3.OperationalError: no such column` the moment a query reached for `date_taken`
or `sequence_kind` — the lucky failure mode, because at least it was loud.

## Prefer the shared seeder to a fourth private copy

`tests/conftest.py` provides:

- `seed_photos_prefix` — factory: insert arbitrary rows (column sets may differ per
  row), every registered prefix is deleted on teardown
- `seeded_photos` — a small ready-made set built on that factory

Both write into the **shared session database** behind `DB_PATH`, so rows are visible to
`client` / `edition_client` / `regular_client` / `superadmin_client` without building a
second app. Cleanup is a path-prefix `DELETE`, which is why every seeded path needs a
distinctive prefix (`/apicontract/`, `/immichhook/`, …).

Do not open your own connection and hand-roll insert + teardown; at one point three
copies of that idiom existed against the same database.

## Wire types: what the API really sends

Assert against these, not against what the TypeScript declares — the declaration has
been wrong twice.

| stored as | arrives as | why |
|---|---|---|
| `INTEGER` flag (`is_blink`, `is_burst_lead`, …) | `0` / `1` | SQLite has no boolean type. The client coerces at ingest, deliberately, rather than changing the wire |
| `TEXT` holding a number (`shutter_speed`) | `"0.0125"` | TEXT affinity stringifies the float the scanner wrote |
| nullable `REAL` (`aggregate`) | `null` for an unscored row | the column has no default |
| flag columns for favourite / rejected | usually `null` | the per-user values live in `user_preferences`; the `photos` columns are only the single-user fallback |

`null` is a real state, not a synonym for false. Preserve it: folding it to `false`
turns "never evaluated" into "evaluated and negative", and for `is_favorite` that is
almost every row in a real library.

## BLOB columns

`thumbnail`, `clip_embedding`, `caption_embedding`, `face_embedding`, `histogram_data`
are BLOBs, and SQLite will accept a `str` into them without complaint — a stub that
"works" until something tries to decode it. Write real bytes:

- thumbnails: a small real JPEG via PIL
- embeddings: `np.ndarray.astype(np.float32).tobytes()`, consistent dimension
- histograms: `utils.histogram.pack_histogram(luma, r, g, b)` — 2048 bytes, uint16

**Give every row distinct bytes.** A fixture where six rows shared one JPEG made a
cross-user pixel leak — Bob's face crop served for Alice's — indistinguishable from
correct behaviour, in the suite whose whole purpose was per-user isolation.

## Sequence sets

A set's identity is the **pair** `(sequence_kind, sequence_group_id)`. The bracket and
panorama passes share the id column and each renumber from 1, so a fixture with a
bracket at `group_id=1` and a panorama at `group_id=1` is the case that catches code
grouping by id alone. Include it whenever you touch sequence logic.

A bracket's representative is `sequence_ev_offset = 0`; a panorama's is
`is_sequence_lead = 1`, and the detector marks the **middle** frame in capture order. A
three-frame fixture cannot tell "first survivor" from "middle survivor" — use five.
