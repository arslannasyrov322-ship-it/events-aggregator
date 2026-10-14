from db import get_pool

_LIST_COLUMNS = (
    "id, name, city, status, event_time, place_id, place_name, "
    "address, registration_deadline, number_of_visitors"
)


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
    async def count(self, date_from: str | None) -> int:
        async with get_pool().acquire() as conn:
            if date_from:
                value = await conn.fetchval(
                    "SELECT COUNT(*) FROM events WHERE event_time >= $1",
                    date_from,
                )
            else:
                value = await conn.fetchval("SELECT COUNT(*) FROM events")
        return int(value)

    async def list_events(
        self, page: int, page_size: int, date_from: str | None
    ) -> list:
        offset = (page - 1) * page_size
        async with get_pool().acquire() as conn:
            if date_from:
                rows = await conn.fetch(
                    f"""
                    SELECT {_LIST_COLUMNS}
                    FROM events
                    WHERE event_time >= $1
                    ORDER BY event_time NULLS LAST
                    LIMIT $2 OFFSET $3
                    """,
                    date_from,
                    page_size,
                    offset,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT {_LIST_COLUMNS}
                    FROM events
                    ORDER BY event_time NULLS LAST
                    LIMIT $1 OFFSET $2
                    """,
                    page_size,
                    offset,
                )
        return [_card(row, with_pattern=False) for row in rows]

    async def get(self, event_id: str) -> dict | None:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, city, status, event_time, place_id, place_name,
                       address, registration_deadline, number_of_visitors,
                       seats_pattern
                FROM events
                WHERE id = $1
                """,
                event_id,
            )
        if row is None:
            return None
        return _card(row, with_pattern=True)

    async def status(self, event_id: str) -> str | None:
        async with get_pool().acquire() as conn:
            return await conn.fetchval(
                "SELECT status FROM events WHERE id = $1",
                event_id,
            )

    async def is_empty(self) -> bool:
        return await self.count(None) == 0

    async def changed_at(self) -> str:
        if await self.is_empty():
            return "2000-01-01"
        async with get_pool().acquire() as conn:
            value = await conn.fetchval(
                "SELECT last_changed_at FROM sync_state WHERE id = 1"
            )
        if not value:
            return "2000-01-01"
        return value

    async def save_changed_at(self, day: str) -> None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO sync_state (id, last_changed_at)
                VALUES (1, $1)
                ON CONFLICT (id) DO UPDATE
                SET last_changed_at = EXCLUDED.last_changed_at
                """,
                day,
            )

    async def upsert(self, event: dict) -> None:
        place = event.get("place") or {}
        visitors = event.get("number_of_visitors")
        if visitors is not None:
            try:
                visitors = int(visitors)
            except (TypeError, ValueError):
                visitors = None
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (
                    id, name, city, status, event_time,
                    place_id, place_name, address,
                    registration_deadline, number_of_visitors, seats_pattern
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
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
            )


class TicketRepository:
    async def event_id(self, ticket_id: str) -> str | None:
        async with get_pool().acquire() as conn:
            return await conn.fetchval(
                "SELECT event_id FROM tickets WHERE ticket_id = $1",
                ticket_id,
            )

    async def save(self, ticket_id: str, event_id: str) -> None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "INSERT INTO tickets (ticket_id, event_id) VALUES ($1, $2)",
                ticket_id,
                event_id,
            )

    async def delete(self, ticket_id: str) -> None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "DELETE FROM tickets WHERE ticket_id = $1",
                ticket_id,
            )
