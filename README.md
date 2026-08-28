## PDF_RAG_ChatBot using 

Try it out: https://ask-your-docs-rag.vercel.app



# Ask Your Docs — RAG Chatbot

A full-stack Retrieval-Augmented Generation (RAG) chatbot that answers questions
using your own documents (PDF / TXT / MD). Upload a file, ask a question, get an
answer grounded in that file's actual content: with source citations, multi-turn
conversation, and a live document manager.

**Live stack:** Next.js frontend (Vercel) → FastAPI backend (Render) → Google
Gemini (embeddings + chat) → Pinecone (vector storage).

---

## Table of contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repo structure](#repo-structure)
- [How it works](#how-it-works)
- [API reference](#api-reference)
- [Design decisions & trade-offs](#design-decisions--trade-offs)
- [Setup — local development](#setup--local-development)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)
- [Possible extensions](#possible-extensions)

---

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│                  │  HTTP   │                  │         │                 │
│  Next.js Frontend│ ──────► │  FastAPI Backend │ ──────► │  Google Gemini  │
│  (Vercel)        │ ◄────── │  (Render)        │ ◄────── │  (embed + chat) │
│                  │  JSON   │                  │         │                 │
└──────────────────┘         └────────┬─────────┘         └─────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │    Pinecone      │
                              │  (vector store)  │
                              └─────────────────┘
```

**Request flow for a question:**

1. Frontend sends `{question, session_id}` to `POST /query`.
2. Backend embeds the question with Gemini (`gemini-embedding-001`).
3. Backend searches Pinecone for the top-4 most similar chunks (cosine similarity).
4. Backend sends `{question, retrieved chunks, chat history}` to Gemini's chat model
   (`gemini-3.5-flash-lite`), which generates an answer grounded only in that
   context.
5. Backend returns `{answer, sources, session_id}` to the frontend.
6. Frontend renders the answer (as Markdown) with clickable source citations.

**Request flow for an upload:**

1. Frontend sends the file to `POST /upload` (multipart form data).
2. Backend saves it, loads + splits it into chunks (`RecursiveCharacterTextSplitter`,
   1000 chars/chunk, 150 char overlap).
3. Backend embeds each chunk with Gemini and upserts the vectors into Pinecone,
   tagged with `source` (filename) and `page` metadata.

---

## Tech stack

| Layer               | Choice                                   | Why |
|---------------------|--------------------------------------------|-----|
| Frontend framework  | Next.js 14 (App Router) + TypeScript       | Matches the rest of the author's portfolio stack; deploys natively on Vercel |
| Styling             | Tailwind CSS                               | Custom "personal archive" design tokens, not a default template look |
| Markdown rendering  | `react-markdown`                            | Gemini's answers come back as Markdown; renders bold/lists/headings properly instead of showing raw `**` |
| Backend framework   | FastAPI (Python)                            | Async-friendly, auto-generates OpenAPI docs at `/docs` |
| Orchestration       | LangChain (`langchain`, `langchain-core`, `langchain-community`, `langchain-text-splitters`) | Standardizes document loading, chunking, and LCEL chain composition |
| Embeddings          | Google Gemini — `gemini-embedding-001` (3072-dim) | Free tier, no separate account needed alongside the chat model |
| Chat / generation   | Google Gemini — `gemini-3.5-flash-lite`     | Current GA (production) model with a generous free daily quota — see [Design decisions](#design-decisions--trade-offs) for the models that *didn't* work out |
| Vector database     | Pinecone (serverless, free tier)            | Real persistent vector DB — survives backend restarts/redeploys, unlike an embedded library |
| Backend hosting     | Render (free tier)                          | No credit card required |
| Frontend hosting    | Vercel                                      | Native Next.js support |
| Retry handling      | `tenacity`                                  | Exponential backoff around Gemini calls (Google's embedding endpoint has occasional intermittent `500` errors — see below) |

---

## Repo structure

```
RAG bot/
├── rag_chatbot/              # FastAPI backend
│   ├── main.py                # API routes
│   ├── ingest.py               # document loading, chunking, embedding, Pinecone upsert/delete/list
│   ├── rag_chain.py             # the actual RAG chain: retrieval + generation + chat memory
│   ├── requirements.txt
│   ├── runtime.txt              # pins Python version for Render
│   ├── render.yaml               # Render deploy blueprint
│   ├── .env.example
│   └── documents/                 # local scratch folder for files being ingested
│
└── rag-frontend/              # Next.js frontend
    ├── app/
    │   ├── page.tsx             # main chat UI, state management
    │   └── layout.tsx            # fonts, metadata
    ├── components/
    │   ├── MessageBubble.tsx      # chat bubble + Markdown rendering
    │   ├── SourceChips.tsx         # expandable citation chips
    │   └── UploadPanel.tsx          # drag-and-drop upload + live document list/delete
    ├── lib/api.ts                # typed client for the backend API
    └── .env.local.example
```

---

## How it works

### Chunking

`RecursiveCharacterTextSplitter` — splits on paragraph → sentence → word
boundaries, in that priority order, so it avoids cutting mid-sentence where
possible.

- `CHUNK_SIZE=1000` characters
- `CHUNK_OVERLAP=150` characters (context bleeds slightly across chunk boundaries
  so an answer isn't lost because it happened to fall right on a split point)

### Retrieval

Plain vector similarity search: the question is embedded, then Pinecone returns
the `TOP_K=4` chunks with the highest cosine similarity. No re-ranking, no hybrid
keyword+vector search, no metadata filtering at query time.

Retrieval always searches using the user's **raw question text** — it does not
rewrite follow-up questions ("what about that?") using conversation history before
searching. (This was a deliberate trade-off — see below.)

### Conversation memory

Per-`session_id`, in-memory chat history (`ChatMessageHistory` via LangChain's
`RunnableWithMessageHistory`). The final answer-generation call receives the full
conversation history, so follow-up answers stay coherent even though *retrieval*
itself isn't history-aware. History resets on backend restart — it's not persisted
to a database.

### Document management

- `POST /upload` — embeds a new file and upserts it, without re-embedding
  everything already in the index.
- `GET /documents` — pages through every vector ID in Pinecone, fetches metadata
  in batches, and returns each distinct source filename with its chunk count.
  (Pinecone has no native "list distinct metadata values" call, so this is done by
  hand — fine at personal scale, would need a different approach — e.g. tracking
  filenames in a small side database — at much larger scale.)
- `DELETE /documents/{filename}` — removes every chunk tagged with that filename,
  via Pinecone's delete-by-metadata-filter.
- `POST /reindex` — full rebuild from whatever's currently in `documents/` on the
  server (rarely useful in production, since `documents/` doesn't survive a Render
  redeploy — `/upload` and `/documents/{filename}` are the reliable path).

---

## API reference

| Method | Path | Description |
|--------|------|--------------|
| GET | `/health` | Liveness check; reports whether Pinecone has any vectors |
| POST | `/query` | `{question, session_id?}` → `{answer, sources, session_id}` |
| POST | `/upload` | Multipart file upload → embeds + upserts into Pinecone |
| GET | `/documents` | List every indexed file with its chunk count |
| DELETE | `/documents/{filename}` | Remove one file's chunks from the index |
| POST | `/reindex` | Full rebuild from `documents/` |
| POST | `/reset-session?session_id=...` | Clear one conversation's history |

Full interactive docs (Swagger UI) at `/docs` on the running backend.

---

## Design decisions & trade-offs

A running list of things that didn't work on the first try, and why the current
approach won — useful context for understanding *why* the code looks the way it
does, not just what it does.

**FAISS → Pinecone.** Started with FAISS (an embedded vector search library, not a
real database) for simplicity. Switched to Pinecone for two real reasons: FAISS's
index lived on Render's local disk, which doesn't reliably survive redeploys, and
Pinecone is what's actually used in production RAG systems in industry — FAISS
tends to be a prototyping/research tool. Trade-off: one more account/API key,
network latency per query instead of an in-process lookup.

**Gemini embeddings → local (sentence-transformers) → back to Gemini embeddings.**
Google's `gemini-embedding-001` endpoint has an intermittent, currently-active,
publicly-reported `500 INTERNAL` bug. Tried switching to a local embedding model
(`sentence-transformers/all-MiniLM-L6-v2`) to sidestep it entirely — but that
model depends on PyTorch, which exceeded Render's free-tier 512MB RAM limit and
crashed the deployed app outright. A crash is worse than an occasional flaky
request, so the project moved back to Gemini's hosted embeddings with retry logic
(`tenacity`, 4 attempts, exponential backoff) instead.

**Removed the "contextualize question" step.** The original design rewrote
follow-up questions using chat history before embedding them for retrieval (e.g.
"which university?" → "Which university did Shahmeer attend?") — a standard
conversational-RAG pattern. In practice, this meant every 2nd+ question in a
session made two back-to-back Gemini calls (a chat completion immediately followed
by an embedding call), and that specific pattern 100%-reproducibly triggered the
`500` bug above — not randomly, but on *every single* multi-turn conversation.
Removing the rewrite step means retrieval always uses the raw question; the final
answer still receives full chat history, so answers stay conversational even
though search itself lost some pronoun-resolution precision. A working chatbot
beats a more sophisticated one that breaks on the second message.

**Chat model churn.** Google deprecates/replaces free-tier Gemini models faster
than most providers. This project has moved through `gemini-2.0-flash` →
`gemini-3-flash-preview` (hit a 20-requests/**day** cap) → `gemini-2.5-flash`
(deprecated for new users) → `gemini-3.5-flash-lite` (current GA model as of this
writing). If `/query` starts returning a `404 NOT_FOUND` on the model name, check
[ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models)
for the current lineup and update `CHAT_MODEL`.

**No global client caching.** Early versions cached the Gemini/Pinecone client
objects as module-level globals to avoid rebuilding them on every request. This
caused a real, reproducible bug: FastAPI runs sync endpoints in a threadpool, so a
request can land on a different thread than the one that created the client — and
the client's internal gRPC connection is bound to its creating thread. Reusing it
from a different thread produced the same opaque `500` error. Every client is now
built fresh per request.

---

## Setup — local development

### Backend

```bash
cd rag_chatbot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: GOOGLE_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME
```

Get a free Gemini key at [Google AI Studio](https://aistudio.google.com/apikey).
Get a free Pinecone key + create an index at [pinecone.io](https://pinecone.io) —
**dimension must be `3072`** (matches Gemini's embedding output), metric `cosine`.

```bash
# add files to documents/, then:
python ingest.py
uvicorn main:app --reload
```

Interactive docs at `http://127.0.0.1:8000/docs`.

### Frontend

```bash
cd rag-frontend
npm install
cp .env.local.example .env.local   # defaults to http://127.0.0.1:8000
npm run dev
```

Open `http://localhost:3000`.

---

## Deployment

**Backend → Render** (free, no card):
1. Push to GitHub.
2. Render → New → Web Service → connect the repo, root directory `rag_chatbot`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Environment variables: `GOOGLE_API_KEY`, `PINECONE_API_KEY`,
   `PINECONE_INDEX_NAME`, `PYTHON_VERSION=3.12.7` (pinning this matters — some
   dependencies, like `faiss-cpu` historically, don't ship wheels for the very
   latest Python).

**Frontend → Vercel:**
1. Push to GitHub (same repo, different subfolder is fine).
2. Vercel → New Project → import repo, root directory `rag-frontend`.
3. Environment variable: `NEXT_PUBLIC_API_URL` = your Render URL.
4. Deploy.

Render's free tier sleeps after inactivity — the first request after a while can
take 30-50 seconds to wake up. Expected, not a bug.

---

## Known limitations

- **No OCR.** `PyPDFLoader` reads a PDF's existing text layer. Scanned PDFs (images
  of pages, no embedded text) will extract nothing or garbage.
- **No auth.** `/upload`, `/query`, and `/documents/*` are open to anyone who can
  reach the deployed URL. Fine for a personal demo; add an API key check before
  sharing widely.
- **Chat history is in-memory only.** Lost on backend restart/redeploy. Document
  vectors (Pinecone) are unaffected — only the *conversation* state resets.
- **Retrieval isn't history-aware.** A very pronoun-heavy follow-up may retrieve
  slightly less precisely than a rewritten version would (see trade-offs above).
- **Gemini free-tier rate limits.** Model availability and daily/per-minute quotas
  change; if `/query` starts failing, check the current model lineup and quotas.
- **`GET /documents` scales linearly** with total vector count (it pages through
  every ID). Fine at personal scale; would need a different design (e.g. a small
  side database tracking filenames) at large scale.

## Possible extensions

- Persist chat history to Redis or a DB table instead of an in-memory dict.
- Add auth (API key header) before any public sharing.
- Add OCR (e.g. Tesseract) for scanned PDF support.
- Bring back history-aware retrieval, but decoupled from a live chat call (e.g. a
  cheap regex/heuristic rewrite instead of an LLM call) to avoid the back-to-back
  Gemini call pattern that caused the original bug.
- Swap Pinecone's free tier for a paid tier / different provider if this ever needs
  to scale past personal use.
