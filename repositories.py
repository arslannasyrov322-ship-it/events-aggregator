import psycopg2

from db import open_db


def _card(row, with_pattern: bool) -> dict:
    place = {
        "id": row[5],
        "name": row[6],
        "city": row[2],
        "address": row[7],
    }
    if with_pattern:
        place["seats_pattern"] = row[10]
    return {
        "id": row[0],
        "name": row[1],
        "event_time": row[4],
        "registration_deadline": row[8],
        "number_of_visitors": row[9],
        "status": row[3],
        "place": place,
    }


class EventRepository:
    def count(self, date_from: str | None) -> int:
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
        cur.close()
        conn.close()
        return count

    def list_events(self, page: int, page_size: int, date_from: str | None) -> list:
        conn = open_db()
        cur = conn.cursor()
        offset = (page - 1) * page_size
        columns = (
            "id, name, city, status, event_time, place_id, place_name, "
            "address, registration_deadline, number_of_visitors"
        )
        if date_from:
            cur.execute(
                f"""
                SELECT {columns}
                FROM events
                WHERE event_time >= %s
                ORDER BY event_time NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (date_from, page_size, offset),
            )
        else:
            cur.execute(
                f"""
                SELECT {columns}
                FROM events
                ORDER BY event_time NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (page_size, offset),
            )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [_card(row, with_pattern=False) for row in rows]

    def get(self, event_id: str) -> dict | None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, city, status, event_time, place_id, place_name,
                   address, registration_deadline, number_of_visitors,
                   seats_pattern
            FROM events
            WHERE id = %s
            """,
            (event_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        return _card(row, with_pattern=True)

    def status(self, event_id: str) -> str | None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute("SELECT status FROM events WHERE id = %s", (event_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        return row[0]

    def is_empty(self) -> bool:
        return self.count(None) == 0

    def changed_at(self) -> str:
        if self.is_empty():
            return "2000-01-01"
        conn = open_db()
        cur = conn.cursor()
        cur.execute("SELECT last_changed_at FROM sync_state WHERE id = 1")
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None or not row[0]:
            return "2000-01-01"
        return row[0]

    def save_changed_at(self, day: str) -> None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO sync_state (id, last_changed_at)
            VALUES (1, %s)
            ON CONFLICT (id) DO UPDATE
            SET last_changed_at = EXCLUDED.last_changed_at
            """,
            (day,),
        )
        conn.commit()
        cur.close()
        conn.close()

    def upsert(self, event: dict) -> None:
        place = event.get("place") or {}
        visitors = event.get("number_of_visitors")
        if visitors is not None:
            try:
                visitors = int(visitors)
            except (TypeError, ValueError):
                visitors = None
        conn = open_db()
        cur = conn.cursor()
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
            conn.commit()
        except psycopg2.Error:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()


class TicketRepository:
    def event_id(self, ticket_id: str) -> str | None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT event_id FROM tickets WHERE ticket_id = %s",
            (ticket_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        return row[0]

    def save(self, ticket_id: str, event_id: str) -> None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tickets (ticket_id, event_id) VALUES (%s, %s)",
            (ticket_id, event_id),
        )
        conn.commit()
        cur.close()
        conn.close()

    def delete(self, ticket_id: str) -> None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM tickets WHERE ticket_id = %s", (ticket_id,))
        conn.commit()
        cur.close()
        conn.close()
