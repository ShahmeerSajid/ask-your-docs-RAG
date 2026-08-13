"""
ingest.py

Reads every document in ./documents (PDF, TXT, MD), splits them into
overlapping chunks, embeds them with OpenAI, and persists a FAISS index
to ./faiss_index so main.py can load it at query time.

Run this whenever you add or change files in ./documents:

    python ingest.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

DOCUMENTS_DIR = Path(__file__).parent / "documents"
INDEX_DIR = Path(__file__).parent / "faiss_index"

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 150))
# Local embedding model -- runs on your machine, no API key or network call needed.
# Google's hosted embedding endpoint has an ongoing, intermittent server-side bug
# (confirmed by multiple developers), so embeddings run locally instead; Gemini is
# still used for the chat/generation half in rag_chain.py, which has been reliable.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

LOADER_BY_SUFFIX = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
}


def load_documents():
    if not DOCUMENTS_DIR.exists():
        print(f"Documents folder not found: {DOCUMENTS_DIR}")
        sys.exit(1)

    docs = []
    files = [f for f in DOCUMENTS_DIR.iterdir() if f.is_file()]

    if not files:
        print(f"No files found in {DOCUMENTS_DIR}. Add PDFs, .txt, or .md files and re-run.")
        sys.exit(1)

    for file_path in files:
        loader_cls = LOADER_BY_SUFFIX.get(file_path.suffix.lower())
        if loader_cls is None:
            print(f"  Skipping unsupported file type: {file_path.name}")
            continue

        print(f"  Loading {file_path.name}")
        try:
            if loader_cls is TextLoader:
                loader = loader_cls(str(file_path), encoding="utf-8")
            else:
                loader = loader_cls(str(file_path))
            loaded = loader.load()
            for d in loaded:
                d.metadata["source"] = file_path.name
            docs.extend(loaded)
        except Exception as e:
            print(f"  Failed to load {file_path.name}: {e}")

    return docs


def build_index():
    print(f"Reading documents from {DOCUMENTS_DIR} ...")
    docs = load_documents()
    print(f"Loaded {len(docs)} raw document(s)/page(s).")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}).")

    print(f"Embedding chunks locally with '{EMBEDDING_MODEL}' (first run downloads "
          f"the model, ~90MB) ...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vectorstore = FAISS.from_documents(chunks, embeddings)

    INDEX_DIR.mkdir(exist_ok=True)
    vectorstore.save_local(str(INDEX_DIR))
    print(f"FAISS index saved to {INDEX_DIR}")


def add_file_to_index(file_path: Path):
    """
    Embed a single new file and add it to the existing FAISS index (or create one
    if none exists yet). Used by the /upload endpoint so a new document doesn't
    require re-embedding every previously-ingested file.
    """
    loader_cls = LOADER_BY_SUFFIX.get(file_path.suffix.lower())
    if loader_cls is None:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")

    if loader_cls is TextLoader:
        loader = loader_cls(str(file_path), encoding="utf-8")
    else:
        loader = loader_cls(str(file_path))
    docs = loader.load()
    for d in docs:
        d.metadata["source"] = file_path.name

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)

    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    if INDEX_DIR.exists() and any(INDEX_DIR.iterdir()):
        vectorstore = FAISS.load_local(
            str(INDEX_DIR), embeddings, allow_dangerous_deserialization=True
        )
        vectorstore.add_documents(chunks)
    else:
        vectorstore = FAISS.from_documents(chunks, embeddings)

    INDEX_DIR.mkdir(exist_ok=True)
    vectorstore.save_local(str(INDEX_DIR))
    return len(chunks)


if __name__ == "__main__":
    build_index()
