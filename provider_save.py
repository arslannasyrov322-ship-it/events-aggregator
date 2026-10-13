import os

import psycopg2
import requests

key = os.environ["EVENTS_API_KEY"]

conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
cur = conn.cursor()

cur.execute("DROP TABLE IF EXISTS events")
cur.execute("""
    CREATE TABLE events (
        id text PRIMARY KEY,
        name text,
        city text,
        status text
        )
    """)
conn.commit()

url = "http://events-provider.dev-2.python-labs.ru/api/events/"
params = {"changed_at": "2000-01-01"}

while url is not None:
    response = requests.get(url, params=params, headers={"x-api-key": key})
    data = response.json()
    for event in data["results"]:
        place = event.get("place") or {}
        cur.execute(
            "INSERT INTO events (id, name, city, status) VALUES (%s, %s, %s, %s)",
            (event["id"], event["name"], place.get("city"), event["status"]),
        )
    url = data["next"]
    params = None

conn.commit()
cur.execute("SELECT COUNT(*) FROM events")
print(cur.fetchall()[0])
cur.close()
conn.close()
