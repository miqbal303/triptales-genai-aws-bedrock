from unittest.mock import MagicMock
import base64

import utils.db_utils as db_utils


def test_make_query_hash_is_case_and_whitespace_insensitive():
    hash1 = db_utils.make_query_hash(
        " Paris ",
        5,
        50000,
        [" Food ", "Museums"],
        "2026-09-01",
    )

    hash2 = db_utils.make_query_hash(
        "paris",
        5,
        50000,
        ["museums", "food"],
        "2026-09-01",
    )

    assert hash1 == hash2
    assert len(hash1) == 64


def test_make_query_hash_changes_when_query_changes():
    hash1 = db_utils.make_query_hash(
        "Paris", 5, 50000, ["food"], "2026-09-01"
    )

    hash2 = db_utils.make_query_hash(
        "London", 5, 50000, ["food"], "2026-09-01"
    )

    assert hash1 != hash2


def test_get_cached_trip_returns_none_without_database(monkeypatch):
    monkeypatch.setattr(db_utils, "trips_collection", None)

    result = db_utils.get_cached_trip("some-query-hash")

    assert result is None


def test_cache_trip_converts_base64_images(monkeypatch):
    collection = MagicMock()
    collection.update_one.return_value.acknowledged = True

    monkeypatch.setattr(db_utils, "trips_collection", collection)

    raw_image = b"fake-image-bytes"
    encoded_image = base64.b64encode(raw_image).decode("utf-8")

    trip_data = {
        "destination": "Paris",
        "days": 3,
        "budget": 50000,
        "interests": ["Food"],
        "food_images": {
            "Croissant": encoded_image
        },
    }

    result = db_utils.cache_trip("abc123", trip_data)

    assert result is True
    collection.update_one.assert_called_once()

    update_document = collection.update_one.call_args.args[1]
    stored_image = update_document["$set"]["trip_data"]["food_images"]["Croissant"]

    assert bytes(stored_image) == raw_image