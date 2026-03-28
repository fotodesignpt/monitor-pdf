python
import streamlit as st
import fitz  # PyMuPDF
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler

# Conexão à base de dados Supabase
DB_HOST = st.secrets.get("DB_HOST", "YOUR_DB_HOST")
DB_NAME = st.secrets.get("DB_NAME", "postgres")
DB_USER = st.secrets.get("DB_USER", "postgres")
DB_PASS = st.secrets.get("DB_PASS", "")
DB_PORT = st.secrets.get("DB_PORT", "5432")

def get_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT
    )

# Função simples de "comparação"
def simple_compare(pdf_texts, site_texts):
    matches = []
    for pdf_name, pdf_content in pdf_texts.items():
        for site_name, site_content in site_texts.items():
            if pdf_content.strip()[:20] in site_content:
                matches.append((pdf_name, site_name, 0.95, datetime.now()))
    return matches

# Funções de PDF e Sites
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

# Função principal de verificação
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
            "INSERT INTO matches (pdf, site, similarity, date) VALUES (%s,%s,%s,%s)",
            (pdf_name, site_name, sim, date),
        )
    conn.commit()
    cur.close()
    conn.close()

# Scheduler para rodar 2x/dia
scheduler = BackgroundScheduler()
scheduler.add_job(run_check, "interval", hours=12)
scheduler.start()

# Streamlit interface
st.title("Monitor de PDFs e Sites")

st.subheader("Carregar PDF")
uploaded_pdf = st.file_uploader("Escolha um PDF", type=["pdf"])
if uploaded_pdf is not None:
    with open(uploaded_pdf.name, "wb") as f:
        f.write(uploaded_pdf.getbuffer())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO pdfs (path) VALUES (%s)", (uploaded_pdf.name,))
    conn.commit()
    cur.close()
    conn.close()
    st.success("PDF carregado!")

st.subheader("Adicionar Site")
site_url = st.text_input("Endereço do site")
if st.button("Adicionar site") and site_url:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO sites (url) VALUES (%s)", (site_url,))
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
