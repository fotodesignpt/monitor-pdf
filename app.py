import streamlit as st
import fitz
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
from PIL import Image
import imagehash
from io import BytesIO
from urllib.parse import urljoin

DB_FILE = "local.db"

# ---------------- DB ----------------
def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS pdfs")
    cur.execute("DROP TABLE IF EXISTS pdf_images")
    cur.execute("DROP TABLE IF EXISTS sites")
    cur.execute("DROP TABLE IF EXISTS matches")

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

    conn.commit()
    conn.close()

# reset automático (evita todos os erros antigos)
if "init" not in st.session_state:
    init_db()
    st.session_state.init = True

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

# ---------------- SITE ----------------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def extract_site_images(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        imgs = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                imgs.append(urljoin(url, src))

        return list(set(imgs))
    except:
        return []

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
        for img_url in extract_site_images(site_url):
            site_img = download_image(img_url)
            if site_img is None:
                continue

            site_hash = get_hash(site_img)
            if not site_hash:
                continue

            for pdf, ref, pdf_hash in pdf_images:
                try:
                    diff = imagehash.hex_to_hash(pdf_hash) - imagehash.hex_to_hash(site_hash)

                    if diff < 8:
                        cur.execute("SELECT 1 FROM matches WHERE image_ref=? AND image_url=?", (ref, img_url))
                        if not cur.fetchone():
                            cur.execute("""
                            INSERT INTO matches VALUES (?,?,?,?,?,?)
                            """, (pdf, ref, site_url, img_url, diff, datetime.now().isoformat()))
                except:
                    continue

    conn.commit()
    conn.close()

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["Upload", "Miniaturas", "Resultados", "Gestão"])

# -------- Upload --------
if menu == "Upload":
    st.title("Upload PDFs e Sites")

    conn = get_conn()
    cur = conn.cursor()

    uploaded_pdfs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        for pdf_file in uploaded_pdfs:
            pdf_bytes = pdf_file.read()
            name = pdf_file.name

            cur.execute("INSERT OR IGNORE INTO pdfs VALUES (?,?)", (name, pdf_bytes))

            for ref, h, img_bytes in extract_pdf_images(pdf_bytes, name):
                cur.execute("INSERT OR IGNORE INTO pdf_images VALUES (?,?,?,?)", (name, ref, h, img_bytes))

            st.success(f"OK: {name}")

        conn.commit()

    sites = st.text_area("Sites (1 por linha)")

    if st.button("Guardar sites"):
        for url in sites.split("\n"):
            url = url.strip()
            if url:
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)", (url,))
        conn.commit()
        st.success("Sites guardados")

    if st.button("Pesquisar agora"):
        run_check()
        st.success("Pesquisa concluída")

    st.subheader("PDFs carregados")
    cur.execute("SELECT name FROM pdfs")
    st.write(cur.fetchall())

    st.subheader("Sites carregados")
    cur.execute("SELECT url FROM sites")
    st.write(cur.fetchall())

    conn.close()

# -------- Miniaturas --------
elif menu == "Miniaturas":
    st.title("Miniaturas")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT pdf, ref, image FROM pdf_images")
    rows = cur.fetchall()

    cols = st.columns(5)
    i = 0
    for pdf, ref, img_bytes in rows:
        img = Image.open(BytesIO(img_bytes))
        cols[i % 5].image(img, caption=ref)
        i += 1

    conn.close()

# -------- Resultados --------
elif menu == "Resultados":
    st.title("Resultados")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM matches ORDER BY date DESC")
    rows = cur.fetchall()

    if rows:
        for r in rows:
            st.write(r)
    else:
        st.write("Sem resultados")

    conn.close()

# -------- Gestão --------
elif menu == "Gestão":
    st.title("Gestão")

    conn = get_conn()
    cur = conn.cursor()

    st.subheader("Apagar PDFs")
    cur.execute("SELECT name FROM pdfs")
    pdfs = [r[0] for r in cur.fetchall()]

    for pdf in pdfs:
        if st.button(f"Apagar {pdf}"):
            cur.execute("DELETE FROM pdfs WHERE name=?", (pdf,))
            cur.execute("DELETE FROM pdf_images WHERE pdf=?", (pdf,))
            conn.commit()
            st.experimental_rerun()

    st.subheader("Apagar Sites")
    cur.execute("SELECT url FROM sites")
    sites = [r[0] for r in cur.fetchall()]

    for s in sites:
        if st.button(f"Apagar {s}"):
            cur.execute("DELETE FROM sites WHERE url=?", (s,))
            conn.commit()
            st.experimental_rerun()

    conn.close()
