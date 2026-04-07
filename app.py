import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
from PIL import Image
import imagehash
from io import BytesIO
from urllib.parse import urljoin
from pdf2image import convert_from_bytes

DB = "data_v2.db"  # NOVA BASE (corrige problema antigo)
MAX_PAGES = 80     # MAIS PROFUNDO

# ---------------- DB ----------------
def get_conn():
    conn = sqlite3.connect(DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (name TEXT PRIMARY KEY, data BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (url TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS pdf_images (pdf TEXT, ref TEXT PRIMARY KEY, hash TEXT, image BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS matches (pdf TEXT, image_ref TEXT, site TEXT, image_url TEXT, similarity INTEGER, date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS system (key TEXT PRIMARY KEY, value TEXT)")

    conn.commit()
    conn.close()

init_db()

# ---------------- HASH MELHORADO ----------------
def get_hash(img):
    try:
        img = img.convert("L")  # grayscale
        img = img.resize((256, 256))  # normaliza
        return str(imagehash.phash(img))
    except:
        return None

# ---------------- PDF ----------------
def extract_pdf_images(pdf_bytes, pdf_name):
    images = []
    try:
        pages = convert_from_bytes(pdf_bytes, dpi=150)

        for i, page in enumerate(pages):
            buffer = BytesIO()
            page.save(buffer, format="PNG")
            img_bytes = buffer.getvalue()

            pil = Image.open(BytesIO(img_bytes))
            h = get_hash(pil)

            ref = f"{pdf_name}_page_{i+1}"

            if h:
                images.append((ref, h, img_bytes))
    except:
        pass

    return images

# ---------------- CRAWLER ----------------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def crawl_site(url):
    visited = set()
    to_visit = [url]
    images = []

    while to_visit and len(visited) < MAX_PAGES:
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
        img = Image.open(BytesIO(r.content))

        # ignora imagens muito pequenas (thumbnails)
        if img.size[0] < 120 or img.size[1] < 120:
            return None

        return img
    except:
        return None

# ---------------- MATCH MELHORADO ----------------
def run_check(selected_sites=None, start_date=None, end_date=None):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT pdf, ref, hash FROM pdf_images")
    pdf_images = cur.fetchall()

    if selected_sites:
        sites = [(s,) for s in selected_sites]
    else:
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

                    # MAIS TOLERANTE (ANTES ERA 12)
                    if diff < 18:
                        now = datetime.now()

                        if start_date and end_date:
                            if not (start_date <= now.date() <= end_date):
                                continue

                        cur.execute("SELECT 1 FROM matches WHERE image_ref=? AND image_url=?", (ref, img_url))

                        if not cur.fetchone():
                            cur.execute("""
                            INSERT INTO matches VALUES (?,?,?,?,?,?)
                            """, (pdf, ref, site_url, img_url, diff, now.isoformat()))
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
        last = datetime.fromisoformat(row[0])
    else:
        last = now - timedelta(hours=7)

    if (now - last).total_seconds() > 21600:
        run_check()
        cur.execute("INSERT OR REPLACE INTO system VALUES ('last_run',?)", (now.isoformat(),))
        conn.commit()

    conn.close()

auto_run()

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["Upload", "Resultados", "Miniaturas"])

# Upload
if menu == "Upload":
    st.title("📥 Upload")

    conn = get_conn()
    cur = conn.cursor()

    uploaded = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded:
        for pdf_file in uploaded:
            data = pdf_file.read()
            name = pdf_file.name

            cur.execute("INSERT OR IGNORE INTO pdfs VALUES (?,?)", (name, data))

            for ref, h, img in extract_pdf_images(data, name):
                cur.execute("INSERT OR IGNORE INTO pdf_images VALUES (?,?,?,?)", (name, ref, h, img))

        conn.commit()
        st.success("PDFs processados")

    sites = st.text_area("Sites (1 por linha)")

    if st.button("Guardar sites"):
        for url in sites.split("\n"):
            url = url.strip()
            if url:
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)", (url,))
        conn.commit()
        st.success("Sites guardados")

    if st.button("🔍 Forçar pesquisa"):
        run_check()
        st.success("Pesquisa concluída")

    conn.close()

# Resultados
elif menu == "Resultados":
    st.title("📊 Resultados")

    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM matches ORDER BY date DESC", conn)
    st.dataframe(df)
    conn.close()

# Miniaturas
elif menu == "Miniaturas":
    st.title("🖼️ Miniaturas")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT ref,image FROM pdf_images")
    rows = cur.fetchall()

    cols = st.columns(5)
    for i, (ref, img) in enumerate(rows):
        cols[i % 5].image(Image.open(BytesIO(img)), caption=ref)

    conn.close()
