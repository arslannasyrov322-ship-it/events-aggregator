import asyncio
from unittest.mock import AsyncMock, Mock

from provider import EventsPaginator, EventsProviderClient


def test_register_returns_ticket():
    async def scenario():
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"ticket_id": "abc"}
        http = AsyncMock()
        http.post.return_value = response
        client = EventsProviderClient(
            "key-for-test",
            base_url="http://example.test",
            http=http,
        )
        result = await client.register("event-1", "Arslan", "Nasyrov", "a@b.c", "A1")
        assert result.status_code == 200
        assert result.json()["ticket_id"] == "abc"

    asyncio.run(scenario())


def test_paginator_yields_events():
    async def scenario():
        page = Mock()
        page.status_code = 200
        page.text = "ok"
        page.json.return_value = {
            "results": [{"id": "1", "name": "Форум"}],
            "next": None,
        }
        client = Mock()

        async def get_page(url, params=None):
            return page

        client.get_page = get_page
        events = [
            event
            async for event in EventsPaginator(
                client, "2000-01-01", base_url="http://example.test"
            )
        ]
        assert len(events) == 1
        assert events[0]["name"] == "Форум"

    asyncio.run(scenario())


def test_unregister_calls_provider():
    async def scenario():
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        http = AsyncMock()
        http.request.return_value = response
        client = EventsProviderClient(
            "key-for-test",
            base_url="http://example.test",
            http=http,
        )
        result = await client.unregister("event-1", "ticket-1")
        assert result.status_code == 200
        assert result.json()["success"] is True

    asyncio.run(scenario())
