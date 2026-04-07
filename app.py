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
import openai
import base64
import os

DB = "final_pro.db"

# ---------------- DB ----------------
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

# ---------------- EMBEDDING ----------------
def get_embedding(img_bytes):
    try:
        b64 = base64.b64encode(img_bytes).decode()
        res = openai.Embedding.create(
            model="text-embedding-3-large",
            input=b64
        )
        return res["data"][0]["embedding"]
    except Exception as e:
        print("ERRO EMBEDDING:", e)
        return None

def similarity(a, b):
    return sum(x*y for x,y in zip(a,b))

# ---------------- PDF ----------------
def process_pdf(pdf_bytes, name):
    results = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for i, page in enumerate(doc):
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")

            emb = get_embedding(img_bytes)

            if emb:
                results.append((f"{name}_p{i}", name, str(emb), img_bytes))

        st.success(f"{name}: {len(results)} imagens extraídas")

    except Exception as e:
        st.error(f"Erro no PDF {name}: {e}")

    return results

# ---------------- CRAWLER ----------------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def crawl(url):
    visited=set()
    queue=[url]
    imgs=[]

    while queue and len(visited)<50:
        u=queue.pop(0)
        if u in visited:
            continue
        visited.add(u)

        try:
            r=requests.get(u,headers=HEADERS,timeout=10)
            soup=BeautifulSoup(r.text,"html.parser")

            for im in soup.find_all("img"):
                src=im.get("src")
                if src:
                    imgs.append((u,urljoin(u,src)))

            for a in soup.find_all("a"):
                href=a.get("href")
                if href:
                    full=urljoin(u,href)
                    if url in full:
                        queue.append(full)
        except:
            pass

    return imgs

def download(url):
    try:
        r=requests.get(url,headers=HEADERS,timeout=10)
        return r.content
    except:
        return None

# ---------------- MATCH ----------------
def run():
    conn=get_conn()
    cur=conn.cursor()

    cur.execute("SELECT ref,embedding FROM images")
    pdf_imgs=cur.fetchall()

    cur.execute("SELECT url FROM sites")
    sites=cur.fetchall()

    for (site,) in sites:
        for page,img in crawl(site):
            data=download(img)
            if not data:
                continue

            emb2=get_embedding(data)
            if not emb2:
                continue

            for ref,emb in pdf_imgs:
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

# ---------------- UI ----------------
st.set_page_config(layout="wide")
menu=st.sidebar.radio("Menu",["Upload","Controlo","Miniaturas","Resultados"])

# ---------------- UPLOAD ----------------
if menu=="Upload":
    st.title("Upload PDFs")

    conn=get_conn()
    cur=conn.cursor()

    files=st.file_uploader("Carregar PDFs", type=["pdf"], accept_multiple_files=True)

    if files:
        for f in files:
            data=f.read()
            cur.execute("INSERT OR IGNORE INTO pdfs VALUES (?,?)",(f.name,data))

            rows = process_pdf(data,f.name)

            for row in rows:
                cur.execute("INSERT OR IGNORE INTO images VALUES (?,?,?,?)",row)

        conn.commit()
        st.success("Upload completo")

    urls=st.text_area("Sites (1 por linha)")

    if st.button("Guardar sites"):
        for u in urls.split("\n"):
            if u.strip():
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)",(u.strip(),))
        conn.commit()
        st.success("Sites guardados")

    if st.button("🔍 Forçar pesquisa"):
        run()

# ---------------- CONTROLO ----------------
elif menu=="Controlo":
    st.title("Controlo do sistema")

    conn=get_conn()
    cur=conn.cursor()

    st.subheader("PDFs carregados")
    pdfs=pd.read_sql_query("SELECT name FROM pdfs",conn)
    st.dataframe(pdfs)

    if st.button("Apagar PDFs"):
        cur.execute("DELETE FROM pdfs")
        cur.execute("DELETE FROM images")
        conn.commit()
        st.success("PDFs apagados")

    st.subheader("Sites")
    sites=pd.read_sql_query("SELECT url FROM sites",conn)
    st.dataframe(sites)

    if st.button("Apagar sites"):
        cur.execute("DELETE FROM sites")
        conn.commit()
        st.success("Sites apagados")

    if st.button("Limpar resultados"):
        cur.execute("DELETE FROM matches")
        conn.commit()
        st.success("Resultados apagados")

# ---------------- MINIATURAS ----------------
elif menu=="Miniaturas":
    conn=get_conn()
    cur=conn.cursor()
    cur.execute("SELECT ref,img FROM images")
    rows=cur.fetchall()

    if not rows:
        st.warning("Sem miniaturas ainda — carrega PDFs")

    cols=st.columns(5)
    for i,(r,img) in enumerate(rows):
        cols[i%5].image(Image.open(BytesIO(img)),caption=r)

# ---------------- RESULTADOS ----------------
elif menu=="Resultados":
    conn=get_conn()
    df=pd.read_sql_query("SELECT * FROM matches ORDER BY date DESC",conn)

    if df.empty:
        st.warning("Sem resultados ainda")

    st.dataframe(df)
