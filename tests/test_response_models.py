"""Guards on the response models the API declares.

``response_model`` FILTERS: a field the model does not declare is a field
stripped from the response, and the caller sees a perfectly valid 200 that is
silently missing data. Nothing else in the suite can see that -- the endpoint
still answers, the status is still 200, and every assertion written against the
fields that survived still passes.

So the model that stands for a photo row has to be a superset of every column
``build_photo_select_columns`` can put in the SELECT list, and that list is
composed at query time from the DB's actual columns. This pins the superset
property against the column lists themselves rather than against a copy.
"""

from __future__ import annotations

from api.db_helpers import PHOTO_BASE_COLS, PHOTO_OPTIONAL_COLS
from api.models.gallery import Photo

# Keys the handlers compute and attach to a row rather than selecting. The
# first four ride on every photo row; the last three are conditional on the
# request's sort or filter, which is why they are optional on the model.
COMPUTED_EXTRAS = {
    'sequence_override',
    'sequence_override_pending',
    'date_formatted',
    'tags_list',
    'persons',
    'unassigned_faces',
    'top_picks_score',
    'learned_score',
    'similarity',
}


def test_photo_model_covers_every_emittable_column():
    """No column can be added to the SELECT list and dropped from the wire."""
    emittable = set(PHOTO_BASE_COLS) | set(PHOTO_OPTIONAL_COLS) | COMPUTED_EXTRAS
    missing = emittable - set(Photo.model_fields)
    assert not missing, (
        f"Photo would strip {len(missing)} field(s) from every photo response: "
        f"{sorted(missing)}"
    )


def test_photo_flag_fields_are_ints_not_bools():
    """SQLite has no boolean, and the client reads the difference.

    Declaring a flag ``bool`` makes Pydantic coerce 0/1 to false/true, which
    silently retypes the wire and breaks ``normalisePhotoFlags`` plus the
    ``sqlite_boolean`` exceptions in ``tests/test_api_contract.py``.
    """
    for field in ('is_favorite', 'is_rejected', 'is_monochrome', 'is_blink', 'is_burst_lead'):
        assert Photo.model_fields[field].annotation is not bool
        assert 'int' in str(Photo.model_fields[field].annotation)


def test_shutter_speed_is_declared_as_the_text_column_it_is():
    """``shutter_speed`` is TEXT and reads back as a string like '0.0125'.

    Declared ``float`` it would be coerced to a number, changing the wire for
    every photo that has one.
    """
    assert 'str' in str(Photo.model_fields['shutter_speed'].annotation)


def test_only_path_is_required():
    """A required field the handler omits is a 500, not an omission.

    Every other field is genuinely absent on some real row -- an optional
    column the DB has not migrated, a score no pass has computed yet -- so
    requiring any of them would turn a normal row into a failed request.
    """
    required = {name for name, f in Photo.model_fields.items() if f.is_required()}
    assert required == {'path'}
