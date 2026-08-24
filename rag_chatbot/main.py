"""
main.py

FastAPI app exposing the RAG chatbot.

Endpoints:
    GET  /health          -> liveness check
    POST /query            -> ask a question (multi-turn, keyed by session_id)
    POST /upload            -> upload a new document; auto-embeds and adds it to the index
    POST /reindex            -> full rebuild of the Pinecone index from ./documents
    POST /reset-session       -> clear chat history for a session_id

Run locally:
    uvicorn main:app --reload
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pinecone import Pinecone

from rag_chain import answer_question, invalidate_vectorstore_cache, reset_session
from ingest import add_file_to_index, delete_document, list_documents, LOADER_BY_SUFFIX, PINECONE_INDEX_NAME

app = FastAPI(
    title="RAG Chatbot API",
    description="Ask questions over your own documents using LangChain + Pinecone + Gemini.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCUMENTS_DIR = Path(__file__).parent / "documents"


def _index_has_vectors() -> bool:
    """Checks Pinecone directly (not a local cache) so /health reflects reality
    even right after a fresh deploy where nothing's been loaded into memory yet."""
    try:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        stats = pc.Index(PINECONE_INDEX_NAME).describe_index_stats()
        return stats.get("total_vector_count", 0) > 0
    except Exception:
        return False


# ---------- Schemas ----------

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question to ask your documents.")
    session_id: str | None = Field(
        None, description="Pass the session_id from a previous response to continue that conversation."
    )


class SourceChunk(BaseModel):
    source: str
    page: int | None = None
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    session_id: str


class UploadResponse(BaseModel):
    filename: str
    chunks_added: int
    status: str


class DocumentInfo(BaseModel):
    filename: str
    chunks: int


# ---------- Endpoints ----------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "index_ready": _index_has_vectors(),
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    if not _index_has_vectors():
        raise HTTPException(
            status_code=400,
            detail="No index found. Add files to ./documents and run `python ingest.py`, "
            "or upload a file via /upload.",
        )

    session_id = request.session_id or str(uuid.uuid4())

    try:
        result = answer_question(request.question, session_id=session_id)
        return QueryResponse(
            answer=result["answer"],
            sources=result["sources"],
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in LOADER_BY_SUFFIX:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Supported: {list(LOADER_BY_SUFFIX)}",
        )

    DOCUMENTS_DIR.mkdir(exist_ok=True)
    dest_path = DOCUMENTS_DIR / file.filename

    try:
        with dest_path.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        file.file.close()

    try:
        chunks_added = add_file_to_index(dest_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to index '{file.filename}': {e}")

    # Drop the cached vectorstore/chain so the next /query call reflects the
    # newly-upserted vectors (Pinecone itself is already updated at this point).
    invalidate_vectorstore_cache()

    return UploadResponse(
        filename=file.filename,
        chunks_added=chunks_added,
        status="added to index",
    )


@app.post("/reindex")
def reindex():
    """Rebuild the Pinecone index from scratch using everything currently in ./documents."""
    try:
        from ingest import build_index

        build_index()
        invalidate_vectorstore_cache()
        return {"status": "reindexed"}
    except SystemExit:
        raise HTTPException(
            status_code=400,
            detail="Reindex failed. Check that ./documents has files and PINECONE_API_KEY/"
            "GOOGLE_API_KEY are set.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset-session")
def reset_session_endpoint(session_id: str):
    """Clear the conversation history for a given session_id (starts that chat fresh)."""
    reset_session(session_id)
    return {"status": "session reset", "session_id": session_id}


@app.get("/documents", response_model=list[DocumentInfo])
def list_documents_endpoint():
    """List every distinct file currently indexed, with its chunk count."""
    try:
        docs = list_documents()
        return [DocumentInfo(filename=d["filename"], chunks=d["chunks"]) for d in docs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents/{filename}")
def delete_document_endpoint(filename: str):
    """Remove every chunk from a specific uploaded file (matched by exact filename)."""
    try:
        delete_document(filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete '{filename}': {e}")

    invalidate_vectorstore_cache()
    return {"status": "deleted", "filename": filename}
