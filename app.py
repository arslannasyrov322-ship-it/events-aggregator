import os
import threading
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, HTTPException

from provider import EventsPaginator, EventsProviderClient


def daily_sync():
    while True:
        print("плановая синхронизация")
        try:
            sync_events()
        except (requests.RequestException, psycopg2.Error, ValueError) as error:
            print("синхронизация не удалась", error)
        time.sleep(24 * 60 * 60)

@asynccontextmanager
async def lifespan(app):
    worker = threading.Thread(target=daily_sync, daemon=True)
    worker.start()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/api/health")
def health():
    return {"status": "ok"}

import psycopg2


def sync_events():
    key = os.environ["EVENTS_API_KEY"]
    client = EventsProviderClient(key)
    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
    cur = conn.cursor()
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS event_time text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS place_id text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS place_name text ")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS address text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS registration_deadline text")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS number_of_visitors integer")
    cur.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS seats_pattern text")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            id integer PRIMARY KEY,
            last_changed_at text
        )
    """)
    cur.execute("SELECT last_changed_at FROM sync_state WHERE id = 1")
    row = cur.fetchone()
    changed_at = "2000-01-01"
    if row is not None and row[0]:
        changed_at = row[0]
    total = 0
    latest = changed_at
    for event in EventsPaginator(client, changed_at):
        place = event.get("place") or {}
        stamp = event.get("changed_at") or ""
        latest = max(latest, stamp)
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
                event.get("number_of_visitors"),
                place.get("seats_pattern"),
            ),
        )
        total = total + 1
            
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

@app.post("/api/sync/trigger")
def sync_trigger():
    total = sync_events()
    return {"status": "ok", "count": total}


@app.get("/api/notes")
def notes():
    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
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

    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
    cur = conn.cursor()
    cur.execute("INSERT INTO notes (message) VALUES (%s)", (message,))
    conn.commit()
    cur.close()
    conn.close()
    return {"message": message}
@app.get("/api/events")
def events(page: int = 1, page_size: int = 20, date_from: str | None = None):
    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
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
    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
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
    response = requests.get(
        f"http://events-provider.dev-2.python-labs.ru/api/events/{event_id}/seats",
        headers={"x-api-key": key},

    )
    if response.status_code !=200:
        raise HTTPException(status_code=502, detail="места сейчас недоступны")

    data = response.json()
    result = {
        "event_id": event_id,
        "available_seats": data["seats"],
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

    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
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
    conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
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



    