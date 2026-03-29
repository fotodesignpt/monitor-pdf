import streamlit as st
import fitz
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
import os
from PIL import Image
import imagehash
from io import BytesIO
from urllib.parse import urljoin

DB_FILE = "local.db"
IMG_FOLDER = "images"
PDF_FOLDER = "pdfs"

os.makedirs(IMG_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)

# ---------------- DB ----------------
def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (path TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (url TEXT UNIQUE)")
    cur.execute("""CREATE TABLE IF NOT EXISTS pdf_images (
        pdf TEXT,
        image_path TEXT,
        ref TEXT UNIQUE,
        hash TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS matches (
        pdf TEXT,
        image_ref TEXT,
        site TEXT,
        page_url TEXT,
        image_url TEXT,
        similarity INTEGER,
        date TEXT
    )""")

    conn.commit()
    conn.close()

init_db()

# ---------------- HASH ----------------
def get_hash(img):
    try:
        return str(imagehash.phash(img))
    except:
        return None

# ---------------- PDF ----------------
def extract_pdf_images(file_path, pdf_name):
    results = []
    try:
        doc = fitz.open(file_path)

        for i, page in enumerate(doc):
            for img_index, img in enumerate(page.get_images(full=True)):
                try:
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)

                    if pix.n >= 5:
                        pix = fitz.Pixmap(fitz.csRGB, pix)

                    ref = f"{pdf_name}_p{i+1}_img{img_index+1}"
                    path = os.path.join(IMG_FOLDER, f"{ref}.png")

                    if not os.path.exists(path):
                        pix.save(path)

                    img_pil = Image.open(path)
                    h = get_hash(img_pil)

                    if h:
                        results.append((path, ref, h))
                except:
                    continue
    except Exception as e:
        st.error(f"Erro PDF {pdf_name}: {e}")

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

    cur.execute("SELECT pdf, image_path, ref, hash FROM pdf_images")
    pdf_images = cur.fetchall()

    cur.execute("SELECT url FROM sites")
    sites = cur.fetchall()

    for (site_url,) in sites:
        site_imgs = extract_site_images(site_url)

        for img_url in site_imgs:
            site_img = download_image(img_url)
            if site_img is None:
                continue

            site_hash = get_hash(site_img)
            if not site_hash:
                continue

            for pdf, path, ref, pdf_hash in pdf_images:
                try:
                    diff = imagehash.hex_to_hash(pdf_hash) - imagehash.hex_to_hash(site_hash)

                    if diff < 8:
                        cur.execute("SELECT 1 FROM matches WHERE image_ref=? AND image_url=?", (ref, img_url))

                        if not cur.fetchone():
                            cur.execute("""
                            INSERT INTO matches (pdf, image_ref, site, page_url, image_url, similarity, date)
                            VALUES (?,?,?,?,?,?,?)
                            """, (pdf, ref, site_url, site_url, img_url, diff, datetime.now().isoformat()))
                except:
                    continue

    conn.commit()
    conn.close()

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["Upload", "Miniaturas", "Resultados", "Debug"])

# -------- Upload --------
if menu == "Upload":
    st.title("PDFs e Sites")

    conn = get_conn()
    cur = conn.cursor()

    uploaded_pdfs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        for pdf_file in uploaded_pdfs:
            try:
                filename = pdf_file.name.replace(" ", "_")
                save_path = os.path.join(PDF_FOLDER, filename)

                with open(save_path, "wb") as f:
                    f.write(pdf_file.read())

                cur.execute("INSERT OR IGNORE INTO pdfs (path) VALUES (?)", (save_path,))

                images = extract_pdf_images(save_path, filename)

                for path, ref, h in images:
                    cur.execute("""
                    INSERT OR IGNORE INTO pdf_images (pdf, image_path, ref, hash)
                    VALUES (?,?,?,?)
                    """, (filename, path, ref, h))

                st.success(f"OK: {filename}")

            except Exception as e:
                st.error(f"Erro: {e}")

        conn.commit()
        conn.close()

    st.subheader("Sites")
    sites = st.text_area("URLs (1 por linha)")

    if st.button("Guardar sites"):
        conn = get_conn()
        cur = conn.cursor()
        for url in sites.split("\n"):
            url = url.strip()
            if url:
                cur.execute("INSERT OR IGNORE INTO sites (url) VALUES (?)", (url,))
        conn.commit()
        conn.close()
        st.success("Sites guardados")

    if st.button("Pesquisar agora"):
        run_check()
        st.success("Pesquisa concluída")

# -------- Miniaturas --------
elif menu == "Miniaturas":
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT pdf FROM pdf_images")
    pdfs = [r[0] for r in cur.fetchall()]

    if pdfs:
        selected = st.selectbox("PDF", pdfs)
        cur.execute("SELECT image_path FROM pdf_images WHERE pdf=?", (selected,))
        rows = cur.fetchall()

        cols = st.columns(5)
        i = 0
        for (path,) in rows:
            if os.path.exists(path):
                cols[i % 5].image(path)
                i += 1

    conn.close()

# -------- Resultados --------
elif menu == "Resultados":
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT pdf, image_ref, site, image_url, similarity, date FROM matches ORDER BY date DESC")
    for row in cur.fetchall():
        st.write(row)

    conn.close()

# -------- Debug --------
elif menu == "Debug":
    conn = get_conn()
    cur = conn.cursor()

    st.write("PDFs")
    cur.execute("SELECT * FROM pdfs")
    st.write(cur.fetchall())

    st.write("Sites")
    cur.execute("SELECT * FROM sites")
    st.write(cur.fetchall())

    st.write("Imagens")
    cur.execute("SELECT * FROM pdf_images LIMIT 20")
    st.write(cur.fetchall())

    conn.close()
