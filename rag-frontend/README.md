# RAG Chatbot — Frontend

A chat UI for the [rag_chatbot](../rag_chatbot) FastAPI backend. Built with Next.js 14,
TypeScript, and Tailwind CSS. Lets you ask questions, see cited source chunks, and
upload new documents directly from the browser.

## Local development

```bash
npm install
cp .env.local.example .env.local
# .env.local defaults to http://127.0.0.1:8000 — fine if your backend runs locally
npm run dev
```

Open `http://localhost:3000`. Make sure your FastAPI backend
(`uvicorn main:app --reload`) is running first.

## Deploying

This is a two-part deployment: the frontend goes on Vercel, but **the backend needs
to be hosted somewhere else first** — Vercel can't run this FastAPI app as-is,
because it needs a persistent process and a local ML model for embeddings, which
don't fit Vercel's serverless model.

### 1. Deploy the backend (Render)

Render has a genuinely free tier with no credit card required, which is why it's
recommended here over Railway or Fly.io (both now require a card).

1. Push the `rag_chatbot` folder to a GitHub repo.
2. Go to [render.com](https://render.com) → New → Web Service → connect your repo.
3. Settings:
   - **Root directory**: `rag_chatbot` (if it's in the same repo as the frontend)
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance type**: Free
4. Add environment variable `GOOGLE_API_KEY` with your key.
5. Deploy. Note the URL Render gives you (e.g. `https://your-app.onrender.com`).
6. Once it's live, you'll need to actually build the index — either upload your
   documents via the frontend's upload panel (recommended, works against the live
   backend), or SSH/shell into the instance and run `python ingest.py`.

**Known trade-offs of Render's free tier:**
- **Cold starts**: the instance sleeps after inactivity; the first request after
  a while can take 30-50 seconds to wake up. Your frontend's health check will just
  look slow, not broken — this is expected.
- **Memory**: `sentence-transformers` pulls in PyTorch, which is fairly heavy. If you
  see the service crash or fail to start, it likely hit the free tier's RAM limit —
  you'd need to upgrade to a paid instance to fix it.

### 2. Deploy the frontend (Vercel)

1. Push this `rag-frontend` folder to a GitHub repo (can be the same repo, different
   subfolder, or a separate repo).
2. Go to [vercel.com](https://vercel.com) → New Project → import the repo.
3. If it's a subfolder, set **Root Directory** to `rag-frontend`.
4. Add environment variable `NEXT_PUBLIC_API_URL` = your Render backend URL from
   step 1 (e.g. `https://your-app.onrender.com`) — **not** `127.0.0.1`.
5. Deploy.

Once both are live, your Vercel URL is a fully public, working chatbot over your own
documents.

## Notes

- CORS is already wide open (`allow_origins=["*"]`) on the backend, so no extra
  config is needed there.
- Chat history is per-session and stored in the backend's memory — it resets if the
  Render instance restarts or sleeps and wakes back up.
- There's no auth on `/upload` — anyone with your deployed URL can add documents to
  your index. Fine for a personal demo; add an API key check before sharing widely.
