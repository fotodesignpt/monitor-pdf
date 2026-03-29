def init_db(reset=False):
    conn = get_conn()
    cur = conn.cursor()

    if reset:
        cur.execute("DROP TABLE IF EXISTS pdfs")
        cur.execute("DROP TABLE IF EXISTS pdf_images")
        cur.execute("DROP TABLE IF EXISTS sites")
        cur.execute("DROP TABLE IF EXISTS matches")

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (name TEXT PRIMARY KEY, data BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (url TEXT PRIMARY KEY)")

    cur.execute("""CREATE TABLE IF NOT EXISTS pdf_images (
        pdf TEXT,
        ref TEXT PRIMARY KEY,
        hash TEXT,
        image BLOB
    )""")

    cur.execute("""CREATE TABLE IF NOT EXISTS matches (
        pdf TEXT,
        image_ref TEXT,
        site TEXT,
        image_url TEXT,
        similarity INTEGER,
        date TEXT
    )""")

    conn.commit()
    conn.close()
