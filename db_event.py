import psycopg2

conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        name text,
        city text,
        status text
    
    )
""")
cur.execute(
    "INSERT INTO events (name, city, status) VALUES (%s, %s, %s)",
    ("Конференция по Python", "Уфа", "published"),
)
conn.commit()

cur.close()
conn.close()
print("событие записано")