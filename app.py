import streamlit as st
import fitz
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
import os

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
    cur.execute("CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY AUTOINCREMENT, pdf TEXT, site TEXT, similarity REAL, date TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS pdf_images (id INTEGER PRIMARY KEY AUTOINCREMENT, pdf TEXT, image_path TEXT)")
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_FILE)

init_db()

def extract_pdf_text(file_path):
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def extract_pdf_images(file_path, pdf_name, max_width=600):
    doc = fitz.open(file_path)
    image_paths = []
    for i, page in enumerate(doc):
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n >= 5:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            scale = 1.0
            if pix.width > max_width:
                scale = max_width / pix.width
            if scale < 1.0:
                pix = fitz.Pixmap(pix, 0, scale, scale)
            img_path = os.path.join(IMG_FOLDER, f"{pdf_name}_p{i+1}_img{img_index+1}.png")
            pix.save(img_path)
            pix = None
            image_paths.append(img_path)
    return image_paths

def extract_site_text(url):
    try:
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text()
    except:
        return ""

def simple_compare(pdf_texts, site_texts):
    matches = []
    for pdf_name, pdf_content in pdf_texts.items():
        for site_name, site_content in site_texts.items():
            if pdf_content.strip()[:20] in site_content:
                matches.append((pdf_name, site_name, 0.95, datetime.now().isoformat()))
    return matches

def run_check():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM pdfs")
    pdf_rows = cur.fetchall()
    cur.execute("SELECT id, url FROM sites")
    site_rows = cur.fetchall()
    pdf_texts = {os.path.basename(row[1]): extract_pdf_text(row[1]) for row in pdf_rows}
    site_texts = {row[1]: extract_site_text(row[1]) for row in site_rows}
    matches = simple_compare(pdf_texts, site_texts)
    for pdf_name, site_name, sim, date in matches:
        cur.execute("INSERT INTO matches (pdf, site, similarity, date) VALUES (?,?,?,?)",
                    (pdf_name, site_name, sim, date))
    conn.commit()
    cur.close()
    conn.close()

scheduler = BackgroundScheduler()
scheduler.add_job(run_check, "interval", hours=6)
scheduler.start()

st.set_page_config(page_title="Monitor PDFs & Sites", layout="wide")
st.title("📄 Monitor de PDFs e Sites (Otimizado)")

st.subheader("📥 Carregar PDFs")
uploaded_pdfs = st.file_uploader("Escolha um ou mais PDFs", type=["pdf"], accept_multiple_files=True)
if uploaded_pdfs:
    conn = get_conn()
    cur = conn.cursor()
    for pdf_file in uploaded_pdfs:
        save_path = os.path.join(PDF_FOLDER, pdf_file.name)
        with open(save_path, "wb") as f:
            f.write(pdf_file.getbuffer())
        cur.execute("INSERT INTO pdfs (path) VALUES (?)", (save_path,))
        image_paths = extract_pdf_images(save_path, os.path.splitext(pdf_file.name)[0])
        for img_path in image_paths:
            cur.execute("INSERT INTO pdf_images (pdf, image_path) VALUES (?,?)", (pdf_file.name, img_path))
    conn.commit()
    cur.close()
    conn.close()
    st.success(f"{len(uploaded_pdfs)} PDFs carregados e miniaturas geradas!")

st.subheader("🌐 Adicionar Sites")
sites_input = st.text_area("Cole os URLs separados por vírgula ou linha")
if st.button("Adicionar sites") and sites_input:
    urls = [url.strip() for url in sites_input.replace("\n", ",").split(",") if url.strip()]
    conn = get_conn()
    cur = conn.cursor()
    for url in urls:
        cur.execute("INSERT INTO sites (url) VALUES (?)", (url,))
    conn.commit()
    cur.close()
    conn.close()
    st.success(f"{len(urls)} sites adicionados!")

st.subheader("📂 PDFs carregados e miniaturas")
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT pdf, image_path FROM pdf_images ORDER BY pdf")
rows = cur.fetchall()
cur.close()
conn.close()
current_pdf = ""
for row in rows:
    pdf_name, img_path = row
    if pdf_name != current_pdf:
        st.markdown(f"**{pdf_name}**")
        current_pdf = pdf_name
    st.image(img_path, width=150)

st.subheader("📊 Resultados encontrados")
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT pdf, site, similarity, date FROM matches ORDER BY date DESC")
rows = cur.fetchall()
cur.close()
conn.close()
for row in rows:
    st.write(f"PDF: {row[0]} | Site: {row[1]} | Similaridade: {row[2]} | Data: {row[3]}")
