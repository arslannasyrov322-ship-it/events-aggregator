import psycopg2

conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS notes (message text)")
cur.execute("INSERT INTO notes (message) VALUES ('привет')")
conn.commit()

cur.execute("SELECT message FROM notes")
print(cur.fetchall())

cur.close()
conn.close()
