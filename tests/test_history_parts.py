import pytest

from db.organization_history import encode, split_parts


def test_receipt_parts_preserve_order_and_count_each_serialized_separator():
    changes = [{'path': 'é.jpg'}, {'path': 'b.jpg'}, {'path': 'c.jpg'}]
    pair_size = len(encode(changes[:2]).encode('utf-8'))
    parts = split_parts(changes, max_photos=10, max_bytes=pair_size)
    assert parts == [changes[:2], changes[2:]]
    assert all(len(encode(part).encode('utf-8')) <= pair_size for part in parts)
    assert split_parts(changes, max_photos=1, max_bytes=1000) == [[item] for item in changes]
    assert split_parts([], max_photos=1, max_bytes=1000) == []


def test_oversized_single_receipt_is_refused_before_returning_any_parts():
    with pytest.raises(ValueError, match='too large'):
        split_parts([{'path': 'ok'}, {'path': 'x' * 100}], max_photos=10, max_bytes=25)
