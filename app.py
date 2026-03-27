import streamlit as st
import requests
from bs4 import BeautifulSoup
import fitz
from PIL import Image
import torch
import open_clip
from urllib.parse import urljoin
from sklearn.metrics.pairwise import cosine_similarity
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import os
import psycopg2

# ---------------- DB ----------------
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    database=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASS"),
    port=os.getenv("DB_PORT")
)
c = conn.cursor()

# ---------------- UI ----------------
st.title("🤖 Monitor Automático de Imagens")

# ADD PDFs
st.header("📄 PDFs")
pdf_files = st.file_uploader("Upload PDFs", type="pdf", accept_multiple_files=True)

if pdf_files:
    for file in pdf_files:
        path = f"data_{file.name}"
        with open(path, "wb") as f:
            f.write(file.read())
        c.execute("INSERT INTO pdfs (path) VALUES (%s)", (path,))
    conn.commit()
    st.success("PDFs guardados!")

# ADD SITES
st.header("🌐 Sites")
url = st.text_input("URL")

if st.button("Adicionar site"):
    c.execute("INSERT INTO sites (url) VALUES (%s)", (url,))
    conn.commit()
    st.success("Site guardado!")

# ---------------- CLIP ----------------
model, _, preprocess = open_clip.create_model_and_transforms(
    'ViT-B-32', pretrained='openai'
)
model.eval()

def get_embedding(path):
    image = preprocess(Image.open(path)).unsqueeze(0)
    with torch.no_grad():
        emb = model.encode_image(image)
    return emb / emb.norm(dim=-1, keepdim=True)

# ---------------- PDF ----------------
def extract_pdf_images(path):
    doc = fitz.open(path)
    paths = []
    for page_index in range(len(doc)):
        for img_index, img in enumerate(doc[page_index].get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            name = f"{path}_{page_index}_{img_index}.png"
            with open(name, "wb") as f:
                f.write(image_bytes)
            paths.append(name)
    return paths

# ---------------- WEB ----------------
def extract_web_images(url):
    try:
        response = requests.get(url, timeout=10)
    except:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    paths = []
    for i, img in enumerate(soup.find_all("img")[:5]):
        src = img.get("src")
        if not src:
            continue
        full_url = urljoin(url, src)
        try:
            img_data = requests.get(full_url).content
            name = f"web_{i}.png"
            with open(name, "wb") as f:
                f.write(img_data)
            paths.append(name)
        except:
            pass
    return paths

# ---------------- CORE ----------------
def run_monitoring():
    c.execute("SELECT path FROM pdfs")
    pdfs = [row[0] for row in c.fetchall()]
    c.execute("SELECT url FROM sites")
    sites = [row[0] for row in c.fetchall()]
    for pdf in pdfs:
        pdf_imgs = extract_pdf_images(pdf)
        for site in sites:
            web_imgs = extract_web_images(site)
            pdf_embs = [(p, get_embedding(p)) for p in pdf_imgs]
            web_embs = [(w, get_embedding(w)) for w in web_imgs]
            for p, pe in pdf_embs:
                for w, we in web_embs:
                    sim = cosine_similarity(pe.numpy(), we.numpy())[0][0]
                    if sim > 0.9:
                        c.execute(
                            "INSERT INTO matches (pdf, site, similarity, date) VALUES (%s,%s,%s,%s)",
                            (p, site, sim, datetime.datetime.now())
                        )
    conn.commit()
    print("✔ Monitorização automática concluída")

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(run_monitoring, 'cron', hour='9,21')
scheduler.start()

# ---------------- HISTÓRICO ----------------
st.header("📊 Resultados encontrados")
c.execute("SELECT * FROM matches ORDER BY date DESC")
rows = c.fetchall()
for row in rows:
    st.write(f"📄 {row[1]} | 🌐 {row[2]} | 🔥 {row[3]:.2f} | ⏰ {row[4]}")