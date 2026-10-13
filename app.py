import os
import threading
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException

from provider import (
    EventsPaginator,
    EventsProviderClient,
    find_provider_base,
    provider_headers,
    provider_place,
    provider_url,
    session,
)


def daily_sync():
    while True:
        print("плановая синхронизация")
        try:
            sync_events()
        except (requests.RequestException, psycopg2.Error, ValueError, KeyError) as error:
            print("синхронизация не удалась", error)
        time.sleep(24 * 60 * 60)

@asynccontextmanager
async def lifespan(app):
    worker = threading.Thread(target=daily_sync, daemon=True)
    worker.start()
    yield

app = FastAPI(lifespan=lifespan)
sync_lock = threading.Lock()
last_sync_error = None
last_sync_count = 0

@app.get("/api/health")
def health():
    return {"status": "ok"}

import psycopg2


def get_connection():
    host = os.environ.get("POSTGRES_HOST")
    url = os.environ.get("POSTGRES_CONNECTION_STRING")
    if host:
        try:
            return psycopg2.connect(
                host=host,
                port=os.environ.get("POSTGRES_PORT", "5432"),
                dbname=os.environ.get("POSTGRES_DATABASE_NAME", "events"),
                user=os.environ.get("POSTGRES_USERNAME", "postgres"),
                password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
            )
        except psycopg2.Error:
            if not url:
                raise
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host="localhost",
        port="5432",
        dbname="events",
        user="postgres",
        password="postgres",
    )


def ensure_schema(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id text PRIMARY KEY,
            name text,
            city text,
            status text,
            event_time text,
            place_id text,
            place_name text,
            address text,
            registration_deadline text,
            number_of_visitors integer,
            seats_pattern text
        )
        """
    )
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS event_time text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS place_id text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS place_name text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS address text")
    cur.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS registration_deadline text"
    )
    cur.execute(
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS number_of_visitors integer"
    )
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS seats_pattern text")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            id integer PRIMARY KEY,
            last_changed_at text
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id text PRIMARY KEY,
            event_id text
        )
        """
    )
    cur.execute("CREATE TABLE IF NOT EXISTS notes (message text)")


def open_db():
    conn = get_connection()
    cur = conn.cursor()
    ensure_schema(cur)
    conn.commit()
    cur.close()
    return conn


def sync_events():
    if not sync_lock.acquire(blocking=False):
        return None
    try:
        return save_events()
    finally:
        sync_lock.release()


def save_events():
    key = os.environ["EVENTS_API_KEY"]
    first_page = find_provider_base(key)
    client = EventsProviderClient(key)
    conn = open_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    if cur.fetchone()[0] == 0:
        changed_at = "2000-01-01"
    else:
        cur.execute("SELECT last_changed_at FROM sync_state WHERE id = 1")
        row = cur.fetchone()
        changed_at = "2000-01-01"
        if row is not None and row[0]:
            changed_at = row[0]
    total = 0
    latest = changed_at
    if changed_at != "2000-01-01":
        first_page = None
    for event in EventsPaginator(client, changed_at, first_response=first_page):
        place = event.get("place") or {}
        stamp = event.get("changed_at") or ""
        latest = max(latest, stamp)
        visitors = event.get("number_of_visitors")
        if visitors is not None:
            try:
                visitors = int(visitors)
            except (TypeError, ValueError):
                visitors = None
        if not event.get("id"):
            continue
        try:
            cur.execute(
            """
            INSERT INTO events (
            id, name, city, status, event_time,
            place_id, place_name, address,
            registration_deadline, number_of_visitors, seats_pattern
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                city = EXCLUDED.city,
                status = EXCLUDED.status,
                event_time = EXCLUDED.event_time,
                place_id = EXCLUDED.place_id,
                place_name = EXCLUDED.place_name,
                address = EXCLUDED.address,
                registration_deadline = EXCLUDED.registration_deadline,
                number_of_visitors = EXCLUDED.number_of_visitors,
                seats_pattern = EXCLUDED.seats_pattern
            """,
            (
                event["id"],
                event["name"],
                place.get("city"),
                event["status"],
                event.get("event_time"),
                place.get("id"),
                place.get("name"),
                place.get("address"),
                event.get("registration_deadline"),
                visitors,
                place.get("seats_pattern"),
            ),
            )
        except psycopg2.Error:
            conn.rollback()
            continue
        total = total + 1
        conn.commit()

    day = latest[:10]
    cur.execute(
        """

        INSERT INTO sync_state (id, last_changed_at)
        VALUES (1,%s)
        ON CONFLICT (id) DO UPDATE
        SET last_changed_at = EXCLUDED.last_changed_at
        """,
        (day,),
    )
    conn.commit()
    cur.close()
    conn.close()
    return total

def run_sync():
    global last_sync_error, last_sync_count
    try:
        saved = sync_events()
    except (psycopg2.Error, requests.RequestException, KeyError, ValueError) as error:
        last_sync_error = str(error)
        print("синхронизация не удалась", error)
        return
    if saved is None:
        return
    last_sync_count = saved
    last_sync_error = None


@app.get("/api/sync/status")
def sync_status():
    return {
        "saved": last_sync_count,
        "error": last_sync_error,
        "has_key": bool(os.environ.get("EVENTS_API_KEY")),
        "has_events_url": bool(os.environ.get("EVENTS_API_URL")),
        "place": provider_place(),
    }


@app.post("/api/sync/trigger")
def sync_trigger():
    worker = threading.Thread(target=run_sync, daemon=True)
    worker.start()
    return {"status": "ok"}


@app.get("/api/notes")
def notes():
    conn = open_db()
    cur = conn.cursor()
    cur.execute("SELECT message FROM notes")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    messages = []
    for row in rows:
        messages.append(row[0])
    return {"notes": messages}

@app.post("/api/notes")
def add_note(note: dict):
    message = note.get("message")
    if message is None:
        return {"error": "нет текста"}

    conn = open_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO notes (message) VALUES (%s)", (message,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": message}
@app.get("/api/events")
def events(page: int = 1, page_size: int = 20, date_from: str | None = None):
    conn = open_db()
    cur = conn.cursor()

    if date_from:
        cur.execute(
            "SELECT COUNT(*) FROM events WHERE event_time >= %s",
            (date_from,),
        )
    else:
        cur.execute("SELECT COUNT(*) FROM events")
    count = cur.fetchone()[0]

    offset = (page - 1) * page_size
    if date_from:
        cur.execute(
            """
            SELECT id, name, city, status, event_time, place_id, place_name, address, registration_deadline, number_of_visitors
            FROM events
            WHERE event_time>= %s
            ORDER BY event_time NULLS LAST
            LIMIT %s OFFSET %s
            """,
            (date_from, page_size, offset),
        )
    else:
        cur.execute(
            """
            SELECT id, name, city, status, event_time, place_id, place_name, address, registration_deadline, number_of_visitors
            FROM events
            ORDER BY event_time NULLS LAST
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
   
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "name": row[1],
            "event_time": row[4],
            "registration_deadline": row[8],
            "number_of_visitors": row[9],
            "status": row[3],
            "place": {
                "id": row[5],
                "name": row[6],
                "city": row[2],
                "address": row[7],
            },
        })

    extra = ""
    if date_from:
        extra = f"&date_from={date_from}"

    next_page = None
    if page * page_size < count:
        next_page = f"http://127.0.0.1:8080/api/events?page={page + 1}&page_size={page_size}{extra}"

    previous_page = None
    if page > 1:
        previous_page= f"http://127.0.0.1:8080/api/events?page={page - 1}&page_size={page_size}{extra}"

    return {
        "count": count,
        "next": next_page,
        "previous": previous_page,
        "results": result,
    }
@app.get("/api/events/{event_id}")
def one_event(event_id: str):
    conn = open_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, city, status, event_time, place_id, place_name, address, registration_deadline, number_of_visitors, seats_pattern 
        FROM events 
        WHERE id = %s
        """,
        (event_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="событие не найдено")

    return {
        "id": row[0],
        "name": row[1],
        "event_time": row[4],
        "registration_deadline": row[8],
        "number_of_visitors": row[9],
        "status": row[3],
        "place": {
            "id": row[5],
            "name": row[6],
            "city": row[2],
            "address": row[7],
            "seats_pattern": row[10],
        },
    }
seat_cache = {}
@app.get("/api/events/{event_id}/seats")
def event_seats(event_id: str):
    now = time.time()
    saved = seat_cache.get(event_id)
    if saved is not None and now - saved["time"] < 30:
        return saved["data"]

    key = os.environ["EVENTS_API_KEY"]
    print("спрашиваю чужой сервис")
    response = session.get(
        provider_url(f"/api/events/{event_id}/seats/"),
        headers=provider_headers(key),
        timeout=60,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="места сейчас недоступны")

    data = response.json()
    seats = data.get("seats", [])
    if not isinstance(seats, list):
        seats = []
    result = {
        "event_id": event_id,
        "available_seats": seats,
    }
    seat_cache[event_id] = {"time": now, "data": result}
    return result

@app.post("/api/tickets", status_code=201)
def create_tickets(ticket: dict):
    for field in ("event_id", "first_name", "last_name", "email", "seat"):
        if not ticket.get(field):
            raise HTTPException(status_code=400, detail="не хватает " + field)
    if "@" not in ticket["email"]:
        raise HTTPException(status_code=400, detail="почта указана некорректно")

    conn = open_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM events WHERE id=%s", (ticket["event_id"],))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="событие не найдено")
    if row[0] != "published":
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="регистрация закрыта")

    client = EventsProviderClient(os.environ["EVENTS_API_KEY"])
    response = client.register(
        ticket["event_id"],
        ticket["first_name"],
        ticket["last_name"],
        ticket["email"],
        ticket["seat"],
    )    
    if response.status_code not in (200, 201):
        cur.close()
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="чужой код " + str(response.status_code) + " " + response.text[:180],
        )
    ticket_id = response.json()["ticket_id"]
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id text PRIMARY KEY,
            event_id text
        )
    """)
    cur.execute(
        "INSERT INTO tickets (ticket_id, event_id) VALUES (%s, %s)",
        (ticket_id, ticket["event_id"]),
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"ticket_id": ticket_id}

@app.delete("/api/tickets/{ticket_id}")
def delete_ticket(ticket_id: str):
    conn = open_db()
    cur = conn.cursor()
    cur.execute("SELECT event_id FROM tickets WHERE ticket_id = %s", (ticket_id,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="билет не найден")

    event_id = row[0]
    client = EventsProviderClient(os.environ["EVENTS_API_KEY"])
    response = client.unregister(event_id, ticket_id)
    if response.status_code not in(200,201):
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="не удалось отменить")

    cur.execute("DELETE FROM tickets WHERE ticket_id = %s", (ticket_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"success": True}



    