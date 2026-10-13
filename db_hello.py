import psycopg2

conn = psycopg2.connect("host=localhost port=5432 dbname=events user=postgres password=postgres")
cur = conn.cursor()
cur.execute("SELECT current_database()")
print(cur.fetchone()[0])
cur.close()
conn.close()
