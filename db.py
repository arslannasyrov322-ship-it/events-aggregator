from urllib.parse import quote

import asyncpg

from config import get_settings

_pool: asyncpg.Pool | None = None


def database_dsn() -> str:
    settings = get_settings()
    if settings.postgres_host and settings.postgres_host != "localhost":
        user = quote(settings.postgres_username, safe="")
        password = quote(settings.postgres_password, safe="")
        database = quote(settings.postgres_database_name, safe="")
        return (
            f"postgresql://{user}:{password}@{settings.postgres_host}:"
            f"{settings.postgres_port}/{database}"
        )
    raw = settings.postgres_connection_string.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw:
        return raw
    return "postgresql://postgres:postgres@localhost:5432/events"


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        database_dsn(),
        min_size=1,
        max_size=10,
        statement_cache_size=0,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("пул базы ещё не создан")
    return _pool


async def ensure_schema() -> None:
    statements = (
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
        """,
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_time text",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS place_id text",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS place_name text",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS address text",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS registration_deadline text",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS number_of_visitors integer",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS seats_pattern text",
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            id integer PRIMARY KEY,
            last_changed_at text
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id text PRIMARY KEY,
            event_id text
        )
        """,
    )
    async with get_pool().acquire() as conn:
        for statement in statements:
            await conn.execute(statement)
