const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export type SourceChunk = {
  source: string;
  page: number | null;
  snippet: string;
};

export type QueryResponse = {
  answer: string;
  sources: SourceChunk[];
  session_id: string;
};

export type HealthResponse = {
  status: string;
  index_ready: boolean;
};

export type DocumentInfo = {
  filename: string;
  chunks: number;
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function checkHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
  return handle<HealthResponse>(res);
}

export async function askQuestion(
  question: string,
  sessionId: string | null
): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId || undefined }),
  });
  return handle<QueryResponse>(res);
}

export async function uploadDocument(
  file: File
): Promise<{ filename: string; chunks_added: number; status: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_URL}/upload`, {
    method: "POST",
    body: formData,
  });
  return handle(res);
}

export async function resetSession(sessionId: string): Promise<void> {
  await fetch(`${API_URL}/reset-session?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${API_URL}/documents`, { cache: "no-store" });
  return handle<DocumentInfo[]>(res);
}

export async function deleteDocument(filename: string): Promise<void> {
  const res = await fetch(`${API_URL}/documents/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
  await handle(res);
}

export { API_URL };
