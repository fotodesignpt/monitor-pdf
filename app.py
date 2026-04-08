import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sqlite3
import pandas as pd
from PIL import Image
from io import BytesIO
from urllib.parse import urljoin
import fitz
import base64
import openai

DB = "final_pro.db"

def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS pdfs (name TEXT PRIMARY KEY, data BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS sites (url TEXT PRIMARY KEY)")
    cur.execute("CREATE TABLE IF NOT EXISTS images (ref TEXT PRIMARY KEY, pdf TEXT, embedding TEXT, img BLOB)")
    cur.execute("CREATE TABLE IF NOT EXISTS matches (ref TEXT, site TEXT, page_url TEXT, image_url TEXT, score REAL, date TEXT)")

    conn.commit()
    conn.close()

init_db()

# -------- EMBEDDING --------
def get_embedding(img_bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode()
        res = openai.Embedding.create(
            model="text-embedding-3-large",
            input=b64
        )
        return res["data"][0]["embedding"]
    except:
        return None

def similarity(a, b):
    return sum(x*y for x,y in zip(a,b))

# -------- EXTRAIR DATA DA PÁGINA --------
def extract_date(soup):
    try:
        t = soup.find("time")
        if t and t.get("datetime"):
            return datetime.fromisoformat(t.get("datetime"))
    except:
        pass

    try:
        meta = soup.find("meta", {"property": "article:published_time"})
        if meta:
            return datetime.fromisoformat(meta.get("content"))
    except:
        pass

    return None

# -------- PDF --------
def process_pdf(pdf_bytes, name):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = []

    for i, page in enumerate(doc):
        pix = page.get_pixmap()
        img_bytes = pix.tobytes("png")

        emb = get_embedding(img_bytes)
        if emb:
            out.append((f"{name}_{i}", name, str(emb), img_bytes))

    return out

# -------- CRAWL COM FILTRO DATA --------
def crawl(site, start_date, end_date):
    visited=set()
    queue=[site]
    imgs=[]

    while queue and len(visited)<100:
        url=queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        try:
            r=requests.get(url,timeout=10)
            soup=BeautifulSoup(r.text,"html.parser")

            page_date = extract_date(soup)

            if start_date and end_date:
                if not page_date:
                    continue
                if not (start_date <= page_date.date() <= end_date):
                    continue

            for im in soup.find_all("img"):
                src=im.get("src")
                if src:
                    imgs.append((url,urljoin(url,src)))

            for a in soup.find_all("a"):
                href=a.get("href")
                if href:
                    full=urljoin(url,href)
                    if site in full:
                        queue.append(full)

        except:
            pass

    return imgs

def download(url):
    try:
        return requests.get(url,timeout=10).content
    except:
        return None

# -------- SEARCH --------
def run(selected_sites, start_date, end_date):
    conn=get_conn()
    cur=conn.cursor()

    cur.execute("SELECT ref,embedding FROM images")
    pdfs=cur.fetchall()

    for site in selected_sites:
        for page,img in crawl(site, start_date, end_date):
            data=download(img)
            if not data:
                continue

            emb2=get_embedding(data)
            if not emb2:
                continue

            for ref,emb in pdfs:
                emb1=eval(emb)
                score=similarity(emb1,emb2)

                if score>0.85:
                    cur.execute("SELECT 1 FROM matches WHERE ref=? AND image_url=?", (ref,img))
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO matches VALUES (?,?,?,?,?,?)",
                            (ref,site,page,img,score,datetime.now().isoformat())
                        )

    conn.commit()
    conn.close()
    st.success("Pesquisa concluída")

# -------- UI --------
st.set_page_config(layout="wide")
menu=st.sidebar.radio("Menu",["Upload","Controlo","Miniaturas","Resultados"])

# -------- UPLOAD --------
if menu=="Upload":
    conn=get_conn()
    cur=conn.cursor()

    files=st.file_uploader("PDFs", type=["pdf"], accept_multiple_files=True)
    if files:
        for f in files:
            data=f.read()
            cur.execute("INSERT OR IGNORE INTO pdfs VALUES (?,?)",(f.name,data))
            rows=process_pdf(data,f.name)
            for r in rows:
                cur.execute("INSERT OR IGNORE INTO images VALUES (?,?,?,?)",r)
        conn.commit()
        st.success("PDFs processados")

    urls=st.text_area("Sites (1 por linha)")
    if st.button("Guardar sites"):
        for u in urls.split("\n"):
            if u.strip():
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)",(u.strip(),))
        conn.commit()

    sites=pd.read_sql_query("SELECT url FROM sites",conn)
    selected=st.multiselect("Escolher sites", sites["url"])

    st.subheader("Intervalo de datas da pesquisa")
    start=st.date_input("Data início", value=None)
    end=st.date_input("Data fim", value=None)

    if st.button("Limpar datas"):
        start=None
        end=None

    if st.button("🔍 Pesquisar agora"):
        run(selected, start, end)

# -------- CONTROLO --------
elif menu=="Controlo":
    conn=get_conn()
    cur=conn.cursor()

    st.dataframe(pd.read_sql_query("SELECT * FROM pdfs",conn))
    st.dataframe(pd.read_sql_query("SELECT * FROM sites",conn))

    if st.button("Apagar PDFs"):
        cur.execute("DELETE FROM pdfs")
        cur.execute("DELETE FROM images")
        conn.commit()

    if st.button("Apagar Sites"):
        cur.execute("DELETE FROM sites")
        conn.commit()

    if st.button("Limpar Resultados"):
        cur.execute("DELETE FROM matches")
        conn.commit()

# -------- MINIATURAS --------
elif menu=="Miniaturas":
    conn=get_conn()
    cur=conn.cursor()
    cur.execute("SELECT ref,img FROM images")
    rows=cur.fetchall()

    cols=st.columns(5)
    for i,(r,img) in enumerate(rows):
        cols[i%5].image(Image.open(BytesIO(img)),caption=r)

# -------- RESULTADOS --------
elif menu=="Resultados":
    conn=get_conn()
    df=pd.read_sql_query("SELECT * FROM matches ORDER BY date DESC",conn)
    st.dataframe(df)
