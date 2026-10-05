import glob
import os

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from common import get_vectorstore, COLLECTION

load_dotenv()

KB_DIR = os.getenv("KB_DIR", "data/kb")

def load_kb() -> list[Document]:
    docs = []
    for path in sorted(glob.glob(os.path.join(KB_DIR, "*.md"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        docs.append(Document(page_content=text, metadata={"source": os.path.basename(path), "type": "olykube_kb"}))
    return docs

def main():
    os.makedirs(KB_DIR, exist_ok=True)
    docs = load_kb()
    print(f"Loaded {len(docs)} KB articles from {KB_DIR}")
    
    if not docs:
        print("Veritabanına eklenecek belge bulunamadı.")
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks")

    store = get_vectorstore()
    try:
        store.delete_collection()
    except Exception:
        pass
    
    store.create_collection()
    store.add_documents(chunks)
    print(f"Ingested {len(chunks)} chunks into pgvector collection '{COLLECTION}'.")

if __name__ == "__main__":
    main()