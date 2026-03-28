import streamlit as st
import fitz
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
import os
from PIL import Image
import imagehash
from io import BytesIO

DB_FILE = "local.db"
IMG_FOLDER = "images"
PDF_FOLDER = "pdfs"

os.makedirs(IMG_FOLDER, exist_ok=True)
os.makedirs(PDF_FOLDER, exist_ok=True)

# ---------------- DB SAFE INIT + MIGRATION ----------------
def safe_add_column(cur, table, column_def):
    col = column_def.split()[0]
    cur.execute(f"PRAGMA table_info({table})")
    cols = [c[1] for c in cur.fetchall()]
    if col not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS pdf_images (id INTEGER PRIMARY KEY AUTOINCREMENT, pdf TEXT, image_path TEXT UNIQUE, ref TEXT UNIQUE, hash TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY AUTOINCREMENT, pdf TEXT, image_ref TEXT, site TEXT, page_url TEXT, image_url TEXT, similarity INTEGER, date TEXT)")

    # MIGRATION SAFE
    safe_add_column(cur, "matches", "image_ref TEXT")
    safe_add_column(cur, "matches", "page_url TEXT")
    safe_add_column(cur, "matches", "image_url TEXT")
    safe_add_column(cur, "matches", "similarity INTEGER")
    safe_add_column(cur, "matches", "date TEXT")

    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_FILE)

init_db()

# ---------------- HASH ----------------
def get_hash(img):
    return str(imagehash.phash(img))

# ---------------- PDF ----------------
def extract_pdf_images(file_path, pdf_name):
    doc = fitz.open(file_path)
    results = []
    for i, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images(full=True)):
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

            results.append((path, ref, h))
    return results

# ---------------- SITE ----------------
def extract_site_images(url):
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        return list(set([img.get("src") for img in soup.find_all("img") if img.get("src")]))
    except:
        return []

def download_image(url):
    try:
        r = requests.get(url, timeout=10)
        return Image.open(BytesIO(r.content))
    except:
        return None

# ---------------- MATCH ENGINE ----------------
def run_check():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT pdf, image_path, ref, hash FROM pdf_images")
    pdf_images = cur.fetchall()

    cur.execute("SELECT url FROM sites")
    sites = cur.fetchall()

    for site in sites:
        site_url = site[0]
        site_imgs = extract_site_images(site_url)

        for img_url in site_imgs:
            site_img = download_image(img_url)
            if site_img is None:
                continue

            site_hash = get_hash(site_img)

            for pdf, path, ref, pdf_hash in pdf_images:
                try:
                    diff = imagehash.hex_to_hash(pdf_hash) - imagehash.hex_to_hash(site_hash)

                    if diff < 8:  # mais rigoroso
                        cur.execute("""SELECT 1 FROM matches 
                                       WHERE image_ref=? AND image_url=?""",
                                    (ref, img_url))
                        exists = cur.fetchone()

                        if not exists:
                            cur.execute("""INSERT INTO matches 
                                (pdf, image_ref, site, page_url, image_url, similarity, date)
                                VALUES (?,?,?,?,?,?,?)""",
                                (pdf, ref, site_url, site_url, img_url, diff, datetime.now().isoformat()))
                except:
                    continue

    conn.commit()
    conn.close()

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(run_check, "interval", hours=6)
scheduler.start()

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["📥 Upload PDFs", "🖼️ Miniaturas", "📊 Resultados"])

# -------- Upload --------
if menu == "📥 Upload PDFs":
    st.title("Carregar PDFs")
    uploaded_pdfs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        conn = get_conn()
        cur = conn.cursor()

        for pdf_file in uploaded_pdfs:
            save_path = os.path.join(PDF_FOLDER, pdf_file.name)

            # evitar duplicação de PDF
            cur.execute("SELECT 1 FROM pdfs WHERE path=?", (save_path,))
            if cur.fetchone():
                continue

            with open(save_path, "wb") as f:
                f.write(pdf_file.getbuffer())

            cur.execute("INSERT INTO pdfs (path) VALUES (?)", (save_path,))

            images = extract_pdf_images(save_path, os.path.splitext(pdf_file.name)[0])

            for path, ref, h in images:
                cur.execute("SELECT 1 FROM pdf_images WHERE ref=?", (ref,))
                if not cur.fetchone():
                    cur.execute("INSERT INTO pdf_images (pdf, image_path, ref, hash) VALUES (?,?,?,?)",
                                (pdf_file.name, path, ref, h))

        conn.commit()
        conn.close()
        st.success("PDFs processados (sem duplicados)")

    st.subheader("Adicionar sites")
    sites = st.text_area("URLs")
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

# -------- Miniaturas --------
elif menu == "🖼️ Miniaturas":
    st.title("Miniaturas")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT pdf FROM pdf_images")
    pdf_list = [row[0] for row in cur.fetchall()]

    if pdf_list:
        selected_pdf = st.selectbox("Selecionar PDF", pdf_list)
        cur.execute("SELECT image_path FROM pdf_images WHERE pdf=?", (selected_pdf,))
        rows = cur.fetchall()

        for (path,) in rows:
            if os.path.exists(path):
                st.image(path, width=120)

    st.subheader("📅 Pesquisas por data")
    cur.execute("SELECT DISTINCT date(date) FROM matches ORDER BY date DESC")
    dates = [row[0] for row in cur.fetchall()]

    if dates:
        selected_date = st.selectbox("Selecionar data", dates)

        cur.execute("SELECT pdf, image_ref, site, image_url FROM matches WHERE date(date)=?", (selected_date,))
        data_rows = cur.fetchall()

        text = ""
        for r in data_rows:
            line = f"{r[0]} | {r[1]} | {r[2]} | {r[3]}"
            st.write(line)
            text += line + "\n"

        st.download_button("Download", text, file_name=f"{selected_date}.txt")

    conn.close()

# -------- Resultados --------
elif menu == "📊 Resultados":
    st.title("Resultados")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pdf, image_ref, site, page_url, image_url, similarity, date FROM matches ORDER BY date DESC")
    rows = cur.fetchall()
    conn.close()

    for r in rows:
        st.markdown(f"""
        **PDF:** {r[0]}  
        **Imagem:** {r[1]}  
        **Site:** {r[2]}  
        **Página:** {r[3]}  
        **Imagem encontrada:** {r[4]}  
        **Diferença:** {r[5]}  
        **Data:** {r[6]}  
        ---
        """)
