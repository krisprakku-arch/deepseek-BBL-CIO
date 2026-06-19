import os
import re
from typing import List, Dict, Any
from langchain_community.document_loaders import PyPDFLoader, TextLoader, UnstructuredWordDocumentLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

# ---------- Configuration ----------
DOCUMENTS_PATH = "documents"
VECTOR_DB_PATH = "chroma_db"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# ---------- Loaders ----------
def load_documents(doc_path: str) -> List[Document]:
    """โหลดเอกสารทั้งหมดจากโฟลเดอร์"""
    docs = []
    for filename in os.listdir(doc_path):
        filepath = os.path.join(doc_path, filename)
        if filename.endswith(".pdf"):
            loader = PyPDFLoader(filepath)
        elif filename.endswith(".txt"):
            loader = TextLoader(filepath, encoding="utf-8")
        elif filename.endswith(".docx"):
            loader = UnstructuredWordDocumentLoader(filepath)
        else:
            continue
        try:
            docs.extend(loader.load())
            print(f"✅ โหลด {filename} สำเร็จ")
        except Exception as e:
            print(f"❌ โหลด {filename} ล้มเหลว: {e}")
    return docs

def chunk_documents(docs: List[Document]) -> List[Document]:
    """แบ่งเอกสารเป็น chunks"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
        length_function=len
    )
    return splitter.split_documents(docs)

# ---------- Embedding & Vector Store ----------
def create_vector_store():
    """สร้าง Chroma DB จากเอกสารในโฟลเดอร์ documents"""
    print("📂 กำลังโหลดเอกสาร...")
    docs = load_documents(DOCUMENTS_PATH)
    if not docs:
        print("❌ ไม่พบเอกสารในโฟลเดอร์ documents")
        return None
    
    print("✂️ กำลังแบ่งเอกสารเป็น chunks...")
    chunks = chunk_documents(docs)
    print(f"✅ ได้ทั้งหมด {len(chunks)} chunks")
    
    print("🧠 กำลังสร้าง embeddings...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    
    print("💾 กำลังสร้าง Vector Store...")
    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=VECTOR_DB_PATH
    )
    vector_store.persist()
    print("✅ Vector Store สร้างสำเร็จ!")
    return vector_store

def load_vector_store():
    """โหลด Vector Store ที่มีอยู่"""
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    return Chroma(persist_directory=VECTOR_DB_PATH, embedding_function=embeddings)

def search_vector_store(query: str, top_k: int = 3):
    """ค้นหาข้อมูลจาก Vector Store"""
    vector_store = load_vector_store()
    results = vector_store.similarity_search(query, k=top_k)
    return results

# ---------- RAG Answer (ใช้เอกสารของคุณ) ----------
def get_rag_answer(question: str) -> str:
    """ค้นหาเอกสารที่เกี่ยวข้องและสร้างคำตอบ"""
    try:
        docs = search_vector_store(question, top_k=3)
        if not docs:
            return None
        
        context = "\n\n".join([d.page_content for d in docs])
        sources = list(set([d.metadata.get("source", "ไม่ระบุ") for d in docs]))
        
        # สร้าง prompt สำหรับ LLM (จะใช้ใน orchestrator แทน)
        return {
            "context": context,
            "sources": sources,
            "docs": docs
        }
    except Exception as e:
        print(f"RAG error: {e}")
        return None

# ---------- Web Search (Tavily) ----------
def web_search(query: str) -> str:
    """ค้นหาข้อมูลจากอินเทอร์เน็ต (ถ้ามี Tavily API)"""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    
    try:
        tool = TavilySearchResults(api_key=api_key, max_results=3)
        results = tool.invoke(query)
        if results:
            return results
    except Exception as e:
        print(f"Web search error: {e}")
    return None

# ---------- Main (สร้าง Vector Store) ----------
if __name__ == "__main__":
    # ใช้สำหรับสร้าง Vector Store ครั้งแรก
    if os.path.exists(VECTOR_DB_PATH):
        print("⚠️ Vector Store มีอยู่แล้ว ถ้าต้องการสร้างใหม่ ให้ลบโฟลเดอร์ chroma_db ก่อน")
    else:
        create_vector_store()
