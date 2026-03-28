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

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT)")
    cur.execute("""CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf TEXT,
        image_ref TEXT,
        site TEXT,
        page_url TEXT,
        image_url TEXT,
        similarity INTEGER,
        date TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS pdf_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf TEXT,
        image_path TEXT,
        ref TEXT,
        hash TEXT
    )""")
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_FILE)

init_db()

def get_hash(img):
    return str(imagehash.phash(img))

def extract_pdf_images(file_path, pdf_name, max_width=400):
    doc = fitz.open(file_path)
    results = []
    for i, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n >= 5:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.width > max_width:
                scale = max_width / pix.width
                pix = fitz.Pixmap(pix, 0, scale, scale)
            ref = f"{pdf_name}_p{i+1}_img{img_index+1}"
            path = os.path.join(IMG_FOLDER, f"{ref}.png")
            pix.save(path)
            img_pil = Image.open(path)
            h = get_hash(img_pil)
            results.append((path, ref, h))
    return results

def extract_site_images(url):
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        imgs = [img.get("src") for img in soup.find_all("img") if img.get("src")]
        return imgs
    except:
        return []

def download_image(url):
    try:
        r = requests.get(url, timeout=10)
        return Image.open(BytesIO(r.content))
    except:
        return None

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
                diff = imagehash.hex_to_hash(pdf_hash) - imagehash.hex_to_hash(site_hash)
                if diff < 10:
                    cur.execute("""INSERT INTO matches 
                        (pdf, image_ref, site, page_url, image_url, similarity, date)
                        VALUES (?,?,?,?,?,?,?)""",
                        (pdf, ref, site_url, site_url, img_url, diff, datetime.now().isoformat()))

    conn.commit()
    conn.close()

scheduler = BackgroundScheduler()
scheduler.add_job(run_check, "interval", hours=6)
scheduler.start()

st.set_page_config(layout="wide")
menu = st.sidebar.selectbox("Menu", ["📥 Upload PDFs", "🖼️ Miniaturas", "📊 Resultados"])

if menu == "📥 Upload PDFs":
    st.title("Carregar PDFs")
    uploaded_pdfs = st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)

    if uploaded_pdfs:
        conn = get_conn()
        cur = conn.cursor()

        for pdf_file in uploaded_pdfs:
            save_path = os.path.join(PDF_FOLDER, pdf_file.name)
            with open(save_path, "wb") as f:
                f.write(pdf_file.getbuffer())

            cur.execute("INSERT INTO pdfs (path) VALUES (?)", (save_path,))
            images = extract_pdf_images(save_path, os.path.splitext(pdf_file.name)[0])

            for path, ref, h in images:
                cur.execute("INSERT INTO pdf_images (pdf, image_path, ref, hash) VALUES (?,?,?,?)",
                            (pdf_file.name, path, ref, h))

        conn.commit()
        conn.close()
        st.success("PDFs carregados")

    st.subheader("Adicionar sites")
    sites = st.text_area("URLs")
    if st.button("Guardar sites"):
        conn = get_conn()
        cur = conn.cursor()
        for url in sites.split("\n"):
            if url.strip():
                cur.execute("INSERT INTO sites (url) VALUES (?)", (url.strip(),))
        conn.commit()
        conn.close()
        st.success("Sites guardados")

elif menu == "🖼️ Miniaturas":
    st.title("Miniaturas")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pdf, image_path FROM pdf_images")
    rows = cur.fetchall()
    conn.close()

    current = ""
    for pdf, path in rows:
        if pdf != current:
            st.subheader(pdf)
            current = pdf
        st.image(path, width=120)

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
        **Imagem ref:** {r[1]}  
        **Site:** {r[2]}  
        **Página:** {r[3]}  
        **Imagem:** {r[4]}  
        **Diferença:** {r[5]}  
        **Data:** {r[6]}  
        ---
        """)
