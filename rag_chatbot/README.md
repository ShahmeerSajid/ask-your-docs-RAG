# RAG Chatbot

A chatbot that answers questions over your own documents (PDF / TXT / MD), built with
**LangChain**, **FAISS**, **Google Gemini**, and **FastAPI**. Runs entirely free —
embeddings run locally on your machine, and chat generation uses Gemini's free API
tier (no credit card).

## How it works

1. Drop your documents into `documents/`.
2. `ingest.py` loads them, splits them into overlapping chunks, embeds each chunk
   **locally** (a small model runs on your machine, no API key or network call), and
   saves a FAISS vector index to `faiss_index/`.
3. `main.py` serves a FastAPI app. `POST /query` embeds the incoming question locally,
   retrieves the most relevant chunks from FAISS, and asks Gemini to answer using
   only that retrieved context (classic RAG), while keeping conversation history so
   follow-up questions work naturally.

```
documents/  --ingest.py (local embed)-->  faiss_index/  --main.py (local retriever + Gemini chat)-->  /query
```

**Why local embeddings instead of Gemini's?** Google's hosted embedding endpoint has
an ongoing, intermittent server-side bug (`500 INTERNAL` errors on valid requests —
confirmed by multiple developers reporting the same issue over several weeks, not
specific to this project). Embeddings run locally instead, which sidesteps it
entirely and is also literally free with no rate limit. Gemini is still used for the
chat/generation half, which has been reliable.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set GOOGLE_API_KEY
```

Get a free key at [Google AI Studio](https://aistudio.google.com/apikey) — sign in
with a Google account, no credit card needed. This key is only used for chat
generation now (embeddings run locally). Free tier is rate-limited but plenty for a
personal project. Note: on the free tier, Google may use your prompts to improve
their models — keep sensitive data off it, or upgrade to the paid tier for a privacy
guarantee.

The first time you run `ingest.py`, it downloads the local embedding model
(~90MB, one-time) — after that it runs fully offline.

## Add your documents and build the index

```bash
# put your resume.pdf, notes.md, etc. into documents/
python ingest.py
```

This creates `faiss_index/` on disk. Re-run `python ingest.py` any time you add,
remove, or edit files in `documents/`.

## Run the API

```bash
uvicorn main:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

### Endpoints

| Method | Path             | Description                                                        |
|--------|------------------|----------------------------------------------------------------------|
| GET    | `/health`        | Liveness check; also reports whether an index exists                 |
| POST   | `/query`         | Ask a question. Supports multi-turn conversation via `session_id`.    |
| POST   | `/upload`        | Upload a new file; it's embedded and added to the index immediately.  |
| POST   | `/reindex`       | Full rebuild of the FAISS index from everything in `documents/`.       |
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
store (Redis, a DB table) if you need it to survive restarts.

**Upload a new document (no manual `ingest.py` needed):**

```bash
curl -X POST http://127.0.0.1:8000/upload -F "file=@/path/to/new_notes.pdf"
```

This embeds just the new file and adds it to the existing index — it does not
re-embed everything you already ingested. Use `/reindex` instead if you ever remove
or edit a file already in `documents/`, since deletions/edits need a full rebuild.

## Configuration (`.env`)

| Variable          | Default                                    | Notes                                        |
|-------------------|----------------------------------------------|------------------------------------------------|
| `GOOGLE_API_KEY`  | —                                             | required for chat; get one free at aistudio.google.com |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2`     | runs locally, no key needed                    |
| `CHAT_MODEL`      | `gemini-3-flash-preview`                     | fast + free-tier eligible                      |
| `CHUNK_SIZE`      | `1000`                                       | characters per chunk                            |
| `CHUNK_OVERLAP`   | `150`                                        | overlap between chunks                          |
| `TOP_K`           | `4`                                          | chunks retrieved per query                      |

Google's model lineup and free-tier eligibility change more often than most
providers' — if you hit a 404 on the chat model, check the current list at
[ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)
and update `CHAT_MODEL` in `.env`.

## Notes / possible extensions

- Swap `PyPDFLoader`/`TextLoader` for more loader types (docx, HTML, CSV) if needed.
- If you'd rather use Gemini's hosted embeddings instead of local ones, swap
  `HuggingFaceEmbeddings` back to `GoogleGenerativeAIEmbeddings` in `ingest.py` and
  `rag_chain.py` — just be aware of the intermittent server bug noted above.
- Persist chat history (Redis or a DB table) instead of the in-memory dict, so
  conversations survive a server restart.
- Add auth (e.g. an API key header) before deploying this publicly — right now
  `/upload` and `/query` are open to anyone who can reach the server.
