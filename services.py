import logging
import threading
import time

import psycopg2
import requests

from config import get_settings
from domain import (
    EventNotFound,
    EventStatus,
    ProviderRejected,
    RegistrationClosed,
    TicketNotFound,
)
from provider import EventsPaginator, EventsProviderClient
from repositories import EventRepository, TicketRepository

logger = logging.getLogger(__name__)


class EventQueryService:
    def __init__(self, events: EventRepository) -> None:
        self._events = events

    def list_events(self, page: int, page_size: int, date_from: str | None) -> dict:
        count = self._events.count(date_from)
        results = self._events.list_events(page, page_size, date_from)
        return {"count": count, "results": results}

    def get_event(self, event_id: str) -> dict:
        event = self._events.get(event_id)
        if event is None:
            raise EventNotFound
        return event


class SyncService:
    def __init__(self, events: EventRepository) -> None:
        self._events = events
        self._lock = threading.Lock()

    def run(self) -> int:
        if not self._lock.acquire(blocking=False):
            return 0
        try:
            return self._save()
        finally:
            self._lock.release()

    def _save(self) -> int:
        settings = get_settings()
        client = EventsProviderClient(settings.events_api_key)
        changed_at = self._events.changed_at()
        total = 0
        latest = changed_at
        for event in EventsPaginator(client, changed_at):
            if not event.get("id"):
                continue
            stamp = event.get("changed_at") or ""
            latest = max(latest, stamp)
            try:
                self._events.upsert(event)
            except psycopg2.Error:
                logger.exception("не удалось записать мероприятие %s", event.get("id"))
                continue
            total = total + 1
        day = (latest or changed_at)[:10]
        self._events.save_changed_at(day)
        return total


class SeatService:
    def __init__(self, events: EventRepository) -> None:
        self._events = events
        self._cache: dict = {}

    def available_seats(self, event_id: str) -> dict:
        now = time.time()
        saved = self._cache.get(event_id)
        if saved is not None and now - saved["time"] < 30:
            return saved["data"]
        if self._events.get(event_id) is None:
            raise EventNotFound
        settings = get_settings()
        client = EventsProviderClient(settings.events_api_key)
        response = client.seats(event_id)
        if response.status_code == 404:
            raise EventNotFound
        if response.status_code != 200:
            raise ProviderRejected(response.status_code, response.text[:180])
        data = response.json()
        seats = data.get("seats", [])
        if not isinstance(seats, list):
            seats = []
        result = {"event_id": event_id, "available_seats": seats}
        self._cache[event_id] = {"time": now, "data": result}
        return result


class TicketService:
    def __init__(self, events: EventRepository, tickets: TicketRepository) -> None:
        self._events = events
        self._tickets = tickets

    def create(self, ticket: dict) -> dict:
        for field in ("event_id", "first_name", "last_name", "email", "seat"):
            if not ticket.get(field):
                raise ValueError(field)
        if "@" not in ticket["email"]:
            raise ValueError("email")
        status = self._events.status(ticket["event_id"])
        if status is None:
            raise EventNotFound
        if status != EventStatus.PUBLISHED:
            raise RegistrationClosed
        settings = get_settings()
        client = EventsProviderClient(settings.events_api_key)
        response = client.register(
            ticket["event_id"],
            ticket["first_name"],
            ticket["last_name"],
            ticket["email"],
            ticket["seat"],
        )
        if response.status_code not in (200, 201):
            raise ProviderRejected(response.status_code, response.text[:180])
        ticket_id = response.json()["ticket_id"]
        self._tickets.save(ticket_id, ticket["event_id"])
        return {"ticket_id": ticket_id}

    def cancel(self, ticket_id: str) -> dict:
        event_id = self._tickets.event_id(ticket_id)
        if event_id is None:
            raise TicketNotFound
        settings = get_settings()
        client = EventsProviderClient(settings.events_api_key)
        response = client.unregister(event_id, ticket_id)
        if response.status_code not in (200, 201):
            raise ProviderRejected(response.status_code, response.text[:180])
        self._tickets.delete(ticket_id)
        return {"success": True}


def run_sync_safely(sync_service: SyncService) -> None:
    try:
        sync_service.run()
    except (requests.RequestException, psycopg2.Error, ValueError, KeyError):
        logger.exception("синхронизация не удалась")
