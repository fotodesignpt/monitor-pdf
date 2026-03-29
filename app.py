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

# ---------------- DB ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (path TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (url TEXT UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS pdf_images (pdf TEXT, image_path TEXT, ref TEXT UNIQUE, hash TEXT)")
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
        if url.startswith("//"):
            url = "https:" + url
        r = requests.get(url, timeout=10)
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

                    if diff < 8:
                        cur.execute("""SELECT 1 FROM matches 
                                       WHERE image_ref=? AND image_url=?""",
                                    (ref, img_url))
                        if not cur.fetchone():
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
menu = st.sidebar.selectbox("Menu", ["Upload", "Miniaturas", "Resultados"])

# -------- Upload --------
if menu == "Upload":
    st.title("📥 PDFs e Sites")

    conn = get_conn()
    cur = conn.cursor()

    uploaded_pdfs = st.file_uploader("Carregar PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        for pdf_file in uploaded_pdfs:
            save_path = os.path.join(PDF_FOLDER, pdf_file.name)

            cur.execute("SELECT 1 FROM pdfs WHERE path=?", (save_path,))
            if cur.fetchone():
                continue

            with open(save_path, "wb") as f:
                f.write(pdf_file.getbuffer())

            cur.execute("INSERT INTO pdfs (path) VALUES (?)", (save_path,))

            images = extract_pdf_images(save_path, pdf_file.name)

            for path, ref, h in images:
                cur.execute("INSERT OR IGNORE INTO pdf_images VALUES (?,?,?,?)",
                            (pdf_file.name, path, ref, h))

        conn.commit()
        st.success("PDFs carregados")

    st.subheader("🌐 Sites")
    sites = st.text_area("URLs (uma por linha)")
    if st.button("Guardar sites"):
        for url in sites.split("\n"):
            url = url.strip()
            if url:
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)", (url,))
        conn.commit()
        st.success("Sites guardados")

    st.subheader("📂 PDFs na base de dados")
    cur.execute("SELECT path FROM pdfs")
    for row in cur.fetchall():
        st.write(row[0])

    st.subheader("🌍 Sites guardados")
    cur.execute("SELECT url FROM sites")
    for row in cur.fetchall():
        st.write(row[0])

    conn.close()

# -------- Miniaturas --------
elif menu == "Miniaturas":
    st.title("🖼️ Miniaturas")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT pdf FROM pdf_images")
    pdfs = [r[0] for r in cur.fetchall()]

    if pdfs:
        selected = st.selectbox("Escolher PDF", pdfs)

        cur.execute("SELECT image_path FROM pdf_images WHERE pdf=?", (selected,))
        rows = cur.fetchall()

        cols = st.columns(5)
        i = 0
        for (path,) in rows:
            if os.path.exists(path):
                cols[i % 5].image(path)
                i += 1
    else:
        st.write("Nenhum PDF processado ainda")

    conn.close()

# -------- Resultados --------
elif menu == "Resultados":
    st.title("📊 Resultados encontrados")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""SELECT pdf, image_ref, site, page_url, image_url, similarity, date 
                   FROM matches ORDER BY date DESC""")
    rows = cur.fetchall()

    if rows:
        for r in rows:
            st.markdown(f"""
            **PDF:** {r[0]}  
            **Imagem:** {r[1]}  
            **Site:** {r[2]}  
            **Página:** {r[3]}  
            **Imagem encontrada:** {r[4]}  
            **Similaridade:** {r[5]}  
            **Data:** {r[6]}  
            ---
            """)
    else:
        st.write("Ainda não há resultados")

    conn.close()
