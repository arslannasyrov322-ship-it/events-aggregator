import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from db import close_pool, ensure_schema, init_pool
from domain import (
    EventNotFound,
    ProviderRejected,
    RegistrationClosed,
    TicketNotFound,
)
from provider import close_http, init_http
from repositories import EventRepository, TicketRepository
from services import (
    EventQueryService,
    SeatService,
    SyncService,
    TicketService,
    run_sync_safely,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

events = EventRepository()
tickets = TicketRepository()
event_queries = EventQueryService(events)
sync_service = SyncService(events)
seat_service = SeatService(events)
ticket_service = TicketService(events, tickets)


async def daily_sync():
    while True:
        logger.info("плановая синхронизация")
        await run_sync_safely(sync_service)
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(app):
    await init_pool()
    await ensure_schema()
    await init_http()
    worker = asyncio.create_task(daily_sync())
    yield
    worker.cancel()
    await close_http()
    await close_pool()


app = FastAPI(lifespan=lifespan)


def _page_url(request: Request, page: int, page_size: int, date_from: str | None):
    url = request.url
    for name in ("page", "page_size", "date_from"):
        url = url.remove_query_params(name)
    url = url.include_query_params(page=page, page_size=page_size)
    if date_from:
        url = url.include_query_params(date_from=date_from)
    return str(url)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/sync/trigger")
async def sync_trigger():
    asyncio.create_task(run_sync_safely(sync_service))
    return {"status": "ok"}


@app.get("/api/events")
async def list_events(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    date_from: str | None = None,
):
    payload = await event_queries.list_events(page, page_size, date_from)
    count = payload["count"]
    next_page = None
    if page * page_size < count:
        next_page = _page_url(request, page + 1, page_size, date_from)
    previous_page = None
    if page > 1:
        previous_page = _page_url(request, page - 1, page_size, date_from)
    return {
        "count": count,
        "next": next_page,
        "previous": previous_page,
        "results": payload["results"],
    }


@app.get("/api/events/{event_id}")
async def one_event(event_id: str):
    try:
        return await event_queries.get_event(event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="событие не найдено") from None


@app.get("/api/events/{event_id}/seats")
async def event_seats(event_id: str):
    try:
        return await seat_service.available_seats(event_id)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="событие не найдено") from None
    except ProviderRejected:
        raise HTTPException(
            status_code=502, detail="места сейчас недоступны"
        ) from None


@app.post("/api/tickets", status_code=201)
async def create_tickets(ticket: dict):
    try:
        return await ticket_service.create(ticket)
    except EventNotFound:
        raise HTTPException(status_code=404, detail="событие не найдено") from None
    except RegistrationClosed:
        raise HTTPException(status_code=400, detail="регистрация закрыта") from None
    except ValueError as error:
        if str(error) == "email":
            detail = "почта указана некорректно"
        else:
            detail = "не хватает " + str(error)
        raise HTTPException(status_code=400, detail=detail) from None
    except ProviderRejected as error:
        raise HTTPException(
            status_code=400,
            detail="чужой код " + str(error.status_code) + " " + error.text,
        ) from None


@app.delete("/api/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str):
    try:
        return await ticket_service.cancel(ticket_id)
    except TicketNotFound:
        raise HTTPException(status_code=404, detail="билет не найден") from None
    except ProviderRejected:
        raise HTTPException(status_code=400, detail="не удалось отменить") from None
