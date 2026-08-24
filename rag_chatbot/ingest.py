"""
ingest.py

Reads every document in ./documents (PDF, TXT, MD), splits them into
overlapping chunks, embeds them with Gemini, and upserts them into your
Pinecone index so main.py can query it at retrieval time.

Unlike FAISS, Pinecone is a persistent hosted store -- there's no local index
folder to save/load. You must create the index once yourself first, in the
Pinecone dashboard or API, with dimension=3072 (matches gemini-embedding-001's
default output) and metric=cosine.

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
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()

DOCUMENTS_DIR = Path(__file__).parent / "documents"

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 150))
# Gemini's hosted embeddings. Note: gemini-embedding-001 defaults to 3072
# dimensions -- your Pinecone index must be created with dimension=3072 to match.
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "ask-your-docs")

LOADER_BY_SUFFIX = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
}

# Gemini's embedding endpoint has an occasional intermittent 500 error (known
# issue, not specific to this app) -- retry with backoff instead of failing outright.
_embed_retry = retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)


def _get_vectorstore() -> PineconeVectorStore:
    if not os.getenv("PINECONE_API_KEY"):
        print("ERROR: PINECONE_API_KEY not set. Add it to .env.")
        sys.exit(1)
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)
    embeddings = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)
    return PineconeVectorStore(index=index, embedding=embeddings)


@_embed_retry
def _upsert(vectorstore: PineconeVectorStore, chunks):
    return vectorstore.add_documents(chunks)


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
    """Full rebuild: clears the Pinecone index, then re-embeds everything in
    ./documents. Use this if you've removed or edited a file (Pinecone has no
    concept of "this chunk is stale" -- a full clear+rebuild is the simple,
    correct way to handle deletions/edits)."""
    print(f"Reading documents from {DOCUMENTS_DIR} ...")
    docs = load_documents()
    print(f"Loaded {len(docs)} raw document(s)/page(s).")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(docs)
    print(f"Split into {len(chunks)} chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}).")

    vectorstore = _get_vectorstore()

    print("Clearing existing vectors in Pinecone index...")
    try:
        vectorstore.index.delete(delete_all=True)
    except Exception:
        pass  # index is already empty -- Pinecone errors on delete_all against an empty index

    print(f"Embedding and upserting {len(chunks)} chunks with '{EMBEDDING_MODEL}' ...")
    _upsert(vectorstore, chunks)
    print(f"Done. Vectors are stored in Pinecone index '{PINECONE_INDEX_NAME}'.")


def add_file_to_index(file_path: Path):
    """
    Embed a single new file and upsert it into the existing Pinecone index.
    Used by the /upload endpoint so a new document doesn't require re-embedding
    every previously-ingested file.
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

    vectorstore = _get_vectorstore()
    _upsert(vectorstore, chunks)
    return len(chunks)


def list_documents() -> list[dict]:
    """
    Returns [{"filename": str, "chunks": int}, ...] for every distinct source file
    currently in the Pinecone index. Pinecone has no native "list distinct metadata
    values" call, so this pages through every vector ID (index.list()) and fetches
    metadata in batches, tallying by the `source` field set during ingest/upload.
    Fine for a personal-scale index (hundreds-low thousands of chunks); would need
    a different approach (e.g. tracking filenames in a separate small DB) at
    much larger scale.
    """
    if not os.getenv("PINECONE_API_KEY"):
        raise RuntimeError("PINECONE_API_KEY not set.")
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)

    counts: dict[str, int] = {}
    for id_batch in index.list():
        if not id_batch:
            continue
        fetched = index.fetch(ids=id_batch)
        for vec in fetched.vectors.values():
            source = (vec.metadata or {}).get("source", "unknown")
            counts[source] = counts.get(source, 0) + 1

    return [
        {"filename": name, "chunks": count}
        for name, count in sorted(counts.items())
    ]


def delete_document(filename: str) -> None:
    """
    Remove every chunk that came from a specific file, identified by the
    `source` metadata field set during ingest/upload. Pinecone serverless
    supports delete-by-metadata-filter (a newer capability -- older serverless
    indexes didn't have this).
    """
    if not os.getenv("PINECONE_API_KEY"):
        raise RuntimeError("PINECONE_API_KEY not set.")
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    index = pc.Index(PINECONE_INDEX_NAME)
    index.delete(filter={"source": {"$eq": filename}})


if __name__ == "__main__":
    build_index()
