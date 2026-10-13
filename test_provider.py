from unittest.mock import Mock, patch

from provider import EventsPaginator, EventsProviderClient


def test_register_returns_ticket():
    client = EventsProviderClient("ключ-для-теста")
    fake = Mock()
    fake.status_code = 200
    fake.json.return_value = {"ticket_id": "abc"}

    with patch("provider.requests.post", return_value=fake):
        response = client.register("event-1", "Арслан", "Насыров", "a@b.c", "A1")

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "abc"


def test_paginator_yields_events():
    client = Mock()
    page = Mock()
    page.status_code = 200
    page.text = "ok"
    page.json.return_value = {
        "results": [{"id": "1", "name": "Форум"}],
        "next": None,
    }
    client.get_page.return_value = page

    events = list(EventsPaginator(client, "2000-01-01"))

    assert len(events) == 1
    assert events[0]["name"] == "Форум"

def test_unregister_calls_provider():
    client = EventsProviderClient("ключ-для-теста")
    fake = Mock()
    fake.status_code = 200
    fake.json.return_value = {"success": True}

    with patch("provider.requests.delete", return_value=fake):
        response = client.unregister("event-1", "ticket-1")

    assert response.status_code == 200
    assert response.json()["success"] is True


