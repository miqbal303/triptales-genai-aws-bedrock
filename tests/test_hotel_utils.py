from unittest.mock import MagicMock
import json

import utils.hotel_utils as hotel_utils


def test_get_hotels_sorts_by_rating_and_limits_results(monkeypatch):
    response_data = {
        "data": [
            {
                "name": "Hotel A",
                "vicinity": "Street A",
                "rating": "3.8",
                "user_ratings_total": 100,
                "geometry": {"location": {"lat": 1, "lng": 2}},
            },
            {
                "name": "Hotel B",
                "vicinity": "Street B",
                "rating": "4.8",
                "user_ratings_total": 500,
                "geometry": {"location": {"lat": 3, "lng": 4}},
            },
            {
                "name": "Hotel C",
                "vicinity": "Street C",
                "rating": "4.2",
                "user_ratings_total": 200,
                "geometry": {"location": {"lat": 5, "lng": 6}},
            },
        ]
    }

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps(response_data).encode()

    fake_connection = MagicMock()
    fake_connection.getresponse.return_value = fake_response

    monkeypatch.setattr(
        hotel_utils.http.client,
        "HTTPSConnection",
        lambda *args, **kwargs: fake_connection,
    )

    hotels = hotel_utils.get_hotels_with_ratings(
        "New Delhi",
        max_results=2,
    )

    assert len(hotels) == 2
    assert hotels[0]["name"] == "Hotel B"
    assert hotels[0]["rating"] == 4.8
    assert hotels[1]["name"] == "Hotel C"


def test_get_hotels_returns_empty_list_on_api_error(monkeypatch):
    fake_connection = MagicMock()
    fake_connection.request.side_effect = RuntimeError("API unavailable")

    monkeypatch.setattr(
        hotel_utils.http.client,
        "HTTPSConnection",
        lambda *args, **kwargs: fake_connection,
    )

    hotels = hotel_utils.get_hotels_with_ratings("Paris")

    assert hotels == []