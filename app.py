import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import sqlite3
import pandas as pd
from PIL import Image
from io import BytesIO
from urllib.parse import urljoin
import fitz
import openai
import base64
import os

DB = "safe.db"

# -------- RESET TOTAL AUTOMÁTICO --------
def reset_db():
    if os.path.exists(DB):
        os.remove(DB)

def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("CREATE TABLE pdfs (name TEXT PRIMARY KEY, data BLOB)")
        cur.execute("CREATE TABLE sites (url TEXT PRIMARY KEY)")
        cur.execute("CREATE TABLE images (ref TEXT PRIMARY KEY, pdf TEXT, embedding TEXT, img BLOB)")
        cur.execute("CREATE TABLE matches (ref TEXT, site TEXT, page_url TEXT, image_url TEXT, score REAL, date TEXT)")

        conn.commit()
        conn.close()
    except:
        reset_db()
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("CREATE TABLE pdfs (name TEXT PRIMARY KEY, data BLOB)")
        cur.execute("CREATE TABLE sites (url TEXT PRIMARY KEY)")
        cur.execute("CREATE TABLE images (ref TEXT PRIMARY KEY, pdf TEXT, embedding TEXT, img BLOB)")
        cur.execute("CREATE TABLE matches (ref TEXT, site TEXT, page_url TEXT, image_url TEXT, score REAL, date TEXT)")

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

# -------- PDF --------
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
    except:
        pass

    return results

# -------- CRAWLER --------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def crawl(url):
    visited=set()
    queue=[url]
    imgs=[]

    while queue and len(visited)<100:
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

# -------- MATCH --------
def run(selected_sites=None, start=None, end=None):
    conn=get_conn()
    cur=conn.cursor()

    cur.execute("SELECT ref,embedding FROM images")
    pdf_imgs=cur.fetchall()

    if selected_sites:
        sites=[(s,) for s in selected_sites]
    else:
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
                    now=datetime.now()

                    if start and end:
                        if not(start<=now.date()<=end):
                            continue

                    cur.execute("SELECT 1 FROM matches WHERE ref=? AND image_url=?", (ref,img))
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO matches VALUES (?,?,?,?,?,?)",
                            (ref,site,page,img,score,now.isoformat())
                        )

    conn.commit()
    conn.close()

# -------- UI --------
st.set_page_config(layout="wide")
menu=st.sidebar.radio("Menu",["Upload","Miniaturas","Resultados"])

# UPLOAD
if menu=="Upload":
    st.title("Upload")

    conn=get_conn()
    cur=conn.cursor()

    files=st.file_uploader("PDFs",type=["pdf"],accept_multiple_files=True)

    if files:
        for f in files:
            data=f.read()
            cur.execute("INSERT OR IGNORE INTO pdfs VALUES (?,?)",(f.name,data))

            for row in process_pdf(data,f.name):
                cur.execute("INSERT OR IGNORE INTO images VALUES (?,?,?,?)",row)

        conn.commit()
        st.success("PDFs guardados")

    urls=st.text_area("Sites (1 por linha)")

    if st.button("Guardar sites"):
        for u in urls.split("\n"):
            if u.strip():
                cur.execute("INSERT OR IGNORE INTO sites VALUES (?)",(u.strip(),))
        conn.commit()

    st.subheader("Filtro de datas")

    col1,col2,col3=st.columns(3)

    start=col1.date_input("Data início")
    end=col2.date_input("Data fim")

    if col3.button("Limpar datas"):
        start=None
        end=None

    cur.execute("SELECT url FROM sites")
    all_sites=[s[0] for s in cur.fetchall()]

    selected=st.multiselect("Escolher sites",all_sites)

    if st.button("Forçar pesquisa"):
        run(selected,start,end)
        st.success("Pesquisa concluída")

# MINIATURAS
elif menu=="Miniaturas":
    conn=get_conn()
    cur=conn.cursor()
    cur.execute("SELECT ref,img FROM images")
    rows=cur.fetchall()

    cols=st.columns(5)
    for i,(r,img) in enumerate(rows):
        cols[i%5].image(Image.open(BytesIO(img)),caption=r)

# RESULTADOS
elif menu=="Resultados":
    conn=get_conn()
    df=pd.read_sql_query("SELECT * FROM matches ORDER BY date DESC",conn)
    st.dataframe(df)
