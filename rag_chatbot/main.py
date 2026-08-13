"""
main.py

FastAPI app exposing the RAG chatbot.

Endpoints:
    GET  /health          -> liveness check
    POST /query            -> ask a question (multi-turn, keyed by session_id)
    POST /upload            -> upload a new document; auto-embeds and adds it to the index
    POST /reindex            -> full rebuild of the FAISS index from ./documents
    POST /reset-session       -> clear chat history for a session_id

Run locally:
    uvicorn main:app --reload
"""

import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import rag_chain
from rag_chain import answer_question, invalidate_vectorstore_cache, reset_session
from ingest import add_file_to_index, LOADER_BY_SUFFIX

app = FastAPI(
    title="RAG Chatbot API",
    description="Ask questions over your own documents using LangChain + FAISS + Gemini.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DOCUMENTS_DIR = Path(__file__).parent / "documents"
INDEX_DIR = Path(__file__).parent / "faiss_index"


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


# ---------- Endpoints ----------

@app.get("/health")
def health():
    return {
        "status": "ok",
        "index_ready": INDEX_DIR.exists() and any(INDEX_DIR.iterdir()),
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    if not (INDEX_DIR.exists() and any(INDEX_DIR.iterdir())):
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

    # The vectorstore/chain were built against the old index -- drop the cache so
    # the next /query call reloads the updated index from disk.
    invalidate_vectorstore_cache()

    return UploadResponse(
        filename=file.filename,
        chunks_added=chunks_added,
        status="added to index",
    )


@app.post("/reindex")
def reindex():
    """Rebuild the FAISS index from scratch using everything currently in ./documents."""
    try:
        from ingest import build_index

        build_index()
        invalidate_vectorstore_cache()
        return {"status": "reindexed"}
    except SystemExit:
        raise HTTPException(
            status_code=400,
            detail="Reindex failed. Check that ./documents has files and OPENAI_API_KEY is set.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/reset-session")
def reset_session_endpoint(session_id: str):
    """Clear the conversation history for a given session_id (starts that chat fresh)."""
    reset_session(session_id)
    return {"status": "session reset", "session_id": session_id}
