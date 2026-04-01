import streamlit as st
import fitz
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sqlite3
from PIL import Image
import imagehash
from io import BytesIO
from urllib.parse import urljoin
import pandas as pd

DB_FILE = "local.db"

# ---------------- DB ----------------
def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM pdfs LIMIT 1")
    except:
        cur.execute("DROP TABLE IF EXISTS pdfs")
        cur.execute("DROP TABLE IF EXISTS sites")
        cur.execute("DROP TABLE IF EXISTS pdf_images")
        cur.execute("DROP TABLE IF EXISTS matches")
        cur.execute("DROP TABLE IF EXISTS system")

        cur.execute("CREATE TABLE pdfs (name TEXT PRIMARY KEY, data BLOB)")
        cur.execute("CREATE TABLE sites (url TEXT PRIMARY KEY)")

        cur.execute("""CREATE TABLE pdf_images (
            pdf TEXT,
            ref TEXT PRIMARY KEY,
            hash TEXT,
            image BLOB
        )""")

        cur.execute("""CREATE TABLE matches (
            pdf TEXT,
            image_ref TEXT,
            site TEXT,
            image_url TEXT,
            similarity INTEGER,
            date TEXT
        )""")

        cur.execute("CREATE TABLE system (key TEXT PRIMARY KEY, value TEXT)")

    conn.commit()
    conn.close()

if "db_checked" not in st.session_state:
    init_db()
    st.session_state.db_checked = True

# ---------------- HASH ----------------
def get_hash(img):
    try:
        return str(imagehash.phash(img))
    except:
        return None

# ---------------- PDF ----------------
def extract_pdf_images(pdf_bytes, pdf_name):
    results = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    for i, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images(full=True)):
            try:
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)

                if pix.n >= 5:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                img_bytes = pix.tobytes("png")
                img_pil = Image.open(BytesIO(img_bytes))

                h = get_hash(img_pil)
                ref = f"{pdf_name}_p{i+1}_img{img_index+1}"

                if h:
                    results.append((ref, h, img_bytes))
            except:
                continue

    return results

# ---------------- CRAWLER ----------------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def crawl_site(url, max_pages=25):
    visited = set()
    to_visit = [url]
    images = []

    while to_visit and len(visited) < max_pages:
        current = to_visit.pop(0)

        if current in visited:
            continue

        visited.add(current)

        try:
            r = requests.get(current, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            for img in soup.find_all("img"):
                src = img.get("src")
                if src:
                    images.append(urljoin(current, src))

            for link in soup.find_all("a"):
                href = link.get("href")
                if href:
                    full = urljoin(current, href)
                    if url in full and full not in visited:
                        to_visit.append(full)

        except:
            continue

    return list(set(images))

def download_image(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return Image.open(BytesIO(r.content))
    except:
        return None

# ---------------- MATCH ----------------
def run_check():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT pdf, ref, hash FROM pdf_images")
    pdf_images = cur.fetchall()

    cur.execute("SELECT url FROM sites")
    sites = cur.fetchall()

    for (site_url,) in sites:
        for img_url in crawl_site(site_url):

            site_img = download_image(img_url)
            if site_img is None:
                continue

            site_hash = get_hash(site_img)
            if not site_hash:
                continue

            for pdf, ref, pdf_hash in pdf_images:
                try:
                    diff = imagehash.hex_to_hash(pdf_hash) - imagehash.hex_to_hash(site_hash)

                    if diff < 10:
                        cur.execute("SELECT 1 FROM matches WHERE image_ref=? AND image_url=?", (ref, img_url))
                        if not cur.fetchone():
                            cur.execute("""
                            INSERT INTO matches VALUES (?,?,?,?,?,?)
                            """, (pdf, ref, site_url, img_url, diff, datetime.now().isoformat()))
                except:
                    continue

    conn.commit()
    conn.close()

# ---------------- AUTO RUN ----------------
def auto_run():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT value FROM system WHERE key='last_run'")
    row = cur.fetchone()

    now = datetime.now()

    if row:
        last_run = datetime.fromisoformat(row[0])
    else:
        last_run = now - timedelta(hours=7)

    if (now - last_run).total_seconds() > 21600:
        run_check()
        cur.execute("INSERT OR REPLACE INTO system VALUES ('last_run', ?)", (now.isoformat(),))
        conn.commit()

    conn.close()

auto_run()

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["Dashboard", "Upload", "Miniaturas", "Resultados", "Gestão"])

# -------- Dashboard --------
if menu == "Dashboard":
    st.title("📊 Dashboard")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM pdfs")
    pdfs = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sites")
    sites = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM matches")
    matches = cur.fetchone()[0]

    st.metric("PDFs", pdfs)
    st.metric("Sites", sites)
    st.metric("Ocorrências", matches)

    cur.execute("SELECT date FROM matches")
    dates = [d[0][:10] for d in cur.fetchall()]

    if dates:
        df = pd.Series(dates).value_counts().sort_index()
        st.line_chart(df)

    conn.close()

# -------- Upload --------
elif menu == "Upload":
    st.title("📥 Upload")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT name FROM pdfs")
    st.write("PDFs:", [r[0] for r in cur.fetchall()])

    cur.execute("SELECT url FROM sites")
    st.write("Sites:", [r[0] for r in cur.fetchall()])

    uploaded_pdfs = st.file_uploader("Adicionar PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        for pdf_file in uploaded_pdfs:
            pdf_bytes = pdf_file.read()
            name = pdf_file.name

            cur.execute("INSERT OR IGNORE INTO pdfs (name, data) VALUES (?,?)", (name, pdf_bytes))

            for ref, h, img_bytes in extract_pdf_images(pdf_bytes, name):
                cur.execute("INSERT OR IGNORE INTO pdf_images VALUES (?,?,?,?)", (name, ref, h, img_bytes))

        conn.commit()
        st.success("PDFs carregados")

    sites = st.text_area("Sites")

    if st.button("Guardar sites"):
        for url in sites.split("\n"):
            url = url.strip()
            if url:
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)", (url,))
        conn.commit()
        st.success("Sites guardados")

    if st.button("🔍 Pesquisa manual"):
        run_check()
        st.success("OK")

    conn.close()

# -------- Miniaturas --------
elif menu == "Miniaturas":
    st.title("🖼️ Miniaturas")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT ref, image FROM pdf_images")
    rows = cur.fetchall()

    cols = st.columns(5)
    for i, (ref, img_bytes) in enumerate(rows):
        cols[i % 5].image(Image.open(BytesIO(img_bytes)), caption=ref)

    conn.close()

# -------- Resultados --------
elif menu == "Resultados":
    st.title("📊 Resultados")

    conn = get_conn()
    cur = conn.cursor()

    df = pd.read_sql_query("SELECT * FROM matches ORDER BY date DESC", conn)
    st.dataframe(df)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download CSV", csv, "resultados.csv")

    conn.close()

# -------- Gestão --------
elif menu == "Gestão":
    st.title("🗑️ Gestão")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT name FROM pdfs")
    for (pdf,) in cur.fetchall():
        if st.button(f"Apagar {pdf}"):
            cur.execute("DELETE FROM pdfs WHERE name=?", (pdf,))
            cur.execute("DELETE FROM pdf_images WHERE pdf=?", (pdf,))
            conn.commit()
            st.experimental_rerun()

    cur.execute("SELECT url FROM sites")
    for (s,) in cur.fetchall():
        if st.button(f"Apagar {s}"):
            cur.execute("DELETE FROM sites WHERE url=?", (s,))
            conn.commit()
            st.experimental_rerun()

    conn.close()
