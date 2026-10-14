import psycopg2

from config import get_settings


def connect():
    settings = get_settings()
    if settings.postgres_host and settings.postgres_host != "localhost":
        try:
            return psycopg2.connect(
                host=settings.postgres_host,
                port=settings.postgres_port,
                dbname=settings.postgres_database_name,
                user=settings.postgres_username,
                password=settings.postgres_password,
            )
        except psycopg2.Error:
            if not settings.postgres_connection_string:
                raise
    if settings.postgres_connection_string:
        return psycopg2.connect(settings.postgres_connection_string)
    return psycopg2.connect(
        host="localhost",
        port="5432",
        dbname="events",
        user="postgres",
        password="postgres",
    )


def ensure_schema(cur) -> None:
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


def open_db():
    conn = connect()
    cur = conn.cursor()
    ensure_schema(cur)
    conn.commit()
    cur.close()
    return conn
