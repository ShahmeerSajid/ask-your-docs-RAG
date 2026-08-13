# RAG Chatbot

A chatbot that answers questions over your own documents (PDF / TXT / MD), built with
**LangChain**, **Pinecone**, **Google Gemini**, and **FastAPI**. Free to run — Gemini's
API free tier handles chat + embeddings (no credit card), and Pinecone's free tier
(2GB storage, no card, doesn't expire) handles vector storage.

## How it works

1. Drop your documents into `documents/`.
2. `ingest.py` loads them, splits them into overlapping chunks, embeds each chunk
   with Gemini, and upserts them into your Pinecone index.
3. `main.py` serves a FastAPI app. `POST /query` embeds the incoming question,
   retrieves the most relevant chunks from Pinecone, and asks Gemini to answer using
   only that retrieved context (classic RAG), while keeping conversation history so
   follow-up questions work naturally.

```
documents/  --ingest.py (Gemini embed)-->  Pinecone index  --main.py (retrieve + Gemini chat)-->  /query
```

Unlike FAISS, Pinecone is a **hosted, persistent** vector store — there's no local
index folder. Vectors survive server restarts and redeploys automatically.

## Setup

### 1. Get a Gemini API key

Free at [Google AI Studio](https://aistudio.google.com/apikey) — sign in with a
Google account, no credit card. Used for both chat generation and embeddings. Note:
on the free tier, Google may use your prompts to improve their models — keep
sensitive data off it, or upgrade to the paid tier for a privacy guarantee.

### 2. Get a Pinecone API key and create an index

1. Sign up at [pinecone.io](https://pinecone.io) (no card needed).
2. In the dashboard, click **Create Index**. Settings:
   - **Name**: anything, e.g. `ask-your-docs`
   - **Dimension**: `3072` — this must match `gemini-embedding-001`'s default output
     size exactly, or every upsert/query will fail with a dimension-mismatch error.
   - **Metric**: `cosine`
3. Dashboard → API Keys → copy your key.

### 3. Install and configure

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env: set GOOGLE_API_KEY, PINECONE_API_KEY, and PINECONE_INDEX_NAME
```

## Add your documents and build the index

```bash
# put your resume.pdf, notes.md, etc. into documents/
python ingest.py
```

This embeds everything in `documents/` and upserts it into your Pinecone index.
Re-run any time you add or edit files — it clears and rebuilds the whole index, since
Pinecone has no built-in concept of "this chunk is stale."

## Run the API

```bash
uvicorn main:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

### Endpoints

| Method | Path             | Description                                                        |
|--------|------------------|----------------------------------------------------------------------|
| GET    | `/health`        | Liveness check; also reports whether the Pinecone index has vectors  |
| POST   | `/query`         | Ask a question. Supports multi-turn conversation via `session_id`.    |
| POST   | `/upload`        | Upload a new file; it's embedded and upserted immediately.            |
| POST   | `/reindex`       | Full rebuild of the Pinecone index from everything in `documents/`.    |
| POST   | `/reset-session` | Clears the chat history for a given `session_id`.                     |

**Ask a question (first turn — no session_id yet):**

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What research has this person done?"}'
```

Response includes a `session_id` — reuse it to continue the same conversation:

```json
{
  "answer": "...",
  "sources": [{"source": "resume.pdf", "page": 1, "snippet": "..."}],
  "session_id": "b6e2b6b0-2f39-4b1a-9b6e-6e8e2b6b0e2f"
}
```

**Continue the conversation (follow-up question, same session):**

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What about his SLAM work specifically?", "session_id": "b6e2b6b0-2f39-4b1a-9b6e-6e8e2b6b0e2f"}'
```

The model rewrites "his SLAM work" against the chat history before retrieving, so
follow-up questions don't need to repeat context. Chat history lives in memory and
is lost on server restart — swap `_session_store` in `rag_chain.py` for a persistent
store (Redis, a DB table) if you need it to survive restarts. (Note this is separate
from your document vectors, which now persist in Pinecone regardless.)

**Upload a new document (no manual `ingest.py` needed):**

```bash
curl -X POST http://127.0.0.1:8000/upload -F "file=@/path/to/new_notes.pdf"
```

This embeds just the new file and upserts it — it does not re-embed everything you
already ingested. Use `/reindex` instead if you ever remove or edit a file already in
`documents/`, since deletions/edits need a full rebuild.

## Configuration (`.env`)

| Variable              | Default                    | Notes                                        |
|------------------------|-----------------------------|------------------------------------------------|
| `GOOGLE_API_KEY`       | —                            | required; get one free at aistudio.google.com  |
| `PINECONE_API_KEY`     | —                            | required; get one free at pinecone.io          |
| `PINECONE_INDEX_NAME`  | `ask-your-docs`              | must match the index you created in Pinecone   |
| `EMBEDDING_MODEL`      | `models/gemini-embedding-001` | outputs 3072 dims by default                  |
| `CHAT_MODEL`           | `gemini-3-flash-preview`     | fast + free-tier eligible                      |
| `CHUNK_SIZE`           | `1000`                       | characters per chunk                            |
| `CHUNK_OVERLAP`        | `150`                        | overlap between chunks                          |
| `TOP_K`                | `4`                          | chunks retrieved per query                      |

Google's model lineup and free-tier eligibility change more often than most
providers' — if you hit a 404 on the chat model, check the current list at
[ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)
and update `CHAT_MODEL` in `.env`.

## Deploying

- **Backend**: Render (free tier, no card). See `render.yaml`. Set `GOOGLE_API_KEY`
  and `PINECONE_API_KEY` in Render's Environment tab (`PINECONE_INDEX_NAME`,
  `CHAT_MODEL`, `EMBEDDING_MODEL` are already set as defaults in `render.yaml`).
- **Frontend**: see the separate `rag-frontend` project — deploys to Vercel, points
  at your Render backend URL via `NEXT_PUBLIC_API_URL`.

Gemini's embedding endpoint has an occasional intermittent `500` error (a known,
not-project-specific issue) — both `ingest.py` and `rag_chain.py` retry automatically
with exponential backoff, so a single transient failure won't break a request.

## Notes / possible extensions

- Swap `PyPDFLoader`/`TextLoader` for more loader types (docx, HTML, CSV) if needed.
- Pinecone supports namespaces — useful if you ever want to separate documents by
  category or user without creating multiple indexes.
- Persist chat history (Redis or a DB table) instead of the in-memory dict, so
  conversations survive a server restart.
- Add auth (e.g. an API key header) before deploying this publicly — right now
  `/upload` and `/query` are open to anyone who can reach the server.
