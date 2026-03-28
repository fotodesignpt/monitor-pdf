import streamlit as st
import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
import os

DB_FILE = "local.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS pdfs (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS sites (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS matches (id INTEGER PRIMARY KEY AUTOINCREMENT, pdf TEXT, site TEXT, similarity REAL, date TEXT)"
    )
    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_FILE)

init_db()

def simple_compare(pdf_texts, site_texts):
    matches = []
    for pdf_name, pdf_content in pdf_texts.items():
        for site_name, site_content in site_texts.items():
            if pdf_content.strip()[:20] in site_content:
                matches.append((pdf_name, site_name, 0.95, datetime.now().isoformat()))
    return matches

def extract_pdf_text(file):
    doc = fitz.open(file)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def extract_site_text(url):
    try:
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        return soup.get_text()
    except:
        return ""

def run_check():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, path FROM pdfs")
    pdf_rows = cur.fetchall()
    cur.execute("SELECT id, url FROM sites")
    site_rows = cur.fetchall()
    pdf_texts = {row[1]: extract_pdf_text(row[1]) for row in pdf_rows}
    site_texts = {row[1]: extract_site_text(row[1]) for row in site_rows}
    matches = simple_compare(pdf_texts, site_texts)
    for pdf_name, site_name, sim, date in matches:
        cur.execute(
            "INSERT INTO matches (pdf, site, similarity, date) VALUES (?,?,?,?)",
            (pdf_name, site_name, sim, date),
        )
    conn.commit()
    conn.close()

scheduler = BackgroundScheduler()
scheduler.add_job(run_check, "interval", hours=12)
scheduler.start()

st.title("Monitor de PDFs e Sites (SQLite local)")

st.subheader("Carregar PDF")
uploaded_pdf = st.file_uploader("Escolha um PDF", type=["pdf"])
if uploaded_pdf is not None:
    save_path = os.path.join(os.getcwd(), uploaded_pdf.name)
    with open(save_path, "wb") as f:
        f.write(uploaded_pdf.getbuffer())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO pdfs (path) VALUES (?)", (save_path,))
    conn.commit()
    cur.close()
    conn.close()
    st.success("PDF carregado!")

st.subheader("Adicionar Site")
site_url = st.text_input("Endereço do site")
if st.button("Adicionar site") and site_url:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO sites (url) VALUES (?)", (site_url,))
    conn.commit()
    cur.close()
    conn.close()
    st.success("Site adicionado!")

st.subheader("Resultados encontrados")
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT pdf, site, similarity, date FROM matches ORDER BY date DESC")
rows = cur.fetchall()
cur.close()
conn.close()
for row in rows:
    st.write(f"PDF: {row[0]} | Site: {row[1]} | Similaridade: {row[2]} | Data: {row[3]}")
