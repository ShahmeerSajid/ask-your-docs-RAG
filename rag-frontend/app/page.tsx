"use client";

import { useEffect, useRef, useState } from "react";
import { askQuestion, checkHealth, resetSession } from "@/lib/api";
import MessageBubble, { type ChatMessage } from "@/components/MessageBubble";
import UploadPanel from "@/components/UploadPanel";

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [indexReady, setIndexReady] = useState<boolean | null>(null);
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshHealth = () => {
    checkHealth()
      .then((h) => setIndexReady(h.index_ready))
      .catch(() => setIndexReady(false));
  };

  useEffect(() => {
    refreshHealth();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    const question = input.trim();
    if (!question || isSending) return;

    setInput("");
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", pending: true },
    ]);
    setIsSending(true);

    try {
      const result = await askQuestion(question, sessionId);
      setSessionId(result.session_id);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: result.answer, sources: result.sources },
      ]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Something went wrong.";
      setMessages((prev) => [
        ...prev.slice(0, -1),
        { role: "assistant", content: `Couldn't get an answer: ${msg}` },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleNewConversation = () => {
    if (sessionId) resetSession(sessionId);
    setSessionId(null);
    setMessages([]);
  };

  return (
    <main className="mx-auto flex h-screen max-w-5xl flex-col px-4 py-6 md:px-8">
      {/* Header */}
      <header className="mb-6 flex items-start justify-between border-b border-line pb-6">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-brass/80">
            Personal Archive
          </p>
          <h1 className="mt-1 font-display text-3xl italic text-parchment">
            Ask your documents
          </h1>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <span
            className={`h-2 w-2 rounded-full ${
              indexReady === null
                ? "bg-slate"
                : indexReady
                ? "bg-emerald-500"
                : "bg-rust animate-pulse"
            }`}
            title={
              indexReady === null
                ? "Checking…"
                : indexReady
                ? "Index ready"
                : "No documents indexed yet"
            }
          />
          <span className="font-mono text-[11px] text-slate">
            {indexReady === null ? "checking" : indexReady ? "indexed" : "empty"}
          </span>
        </div>
      </header>

      <div className="grid flex-1 grid-cols-1 gap-6 overflow-hidden md:grid-cols-[1fr_260px]">
        {/* Chat column */}
        <div className="flex min-h-0 flex-col">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto pr-1">
            {messages.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center text-center">
                <p className="font-display text-xl italic text-slate">
                  {indexReady
                    ? "The archive is open."
                    : "Nothing indexed yet."}
                </p>
                <p className="mt-2 max-w-xs text-sm text-slate/70">
                  {indexReady
                    ? "Ask anything about the documents you've added."
                    : "Add a document on the right to begin."}
                </p>
              </div>
            )}
            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} />
            ))}
          </div>

          {/* Composer */}
          <div className="mt-4 flex items-end gap-2 border-t border-line pt-4">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask a question…"
              rows={1}
              className="max-h-32 flex-1 resize-none rounded-sm border border-line bg-panel px-3 py-2.5 text-[15px] text-parchment placeholder:text-slate/60 focus:border-brasssoft focus:outline-none"
            />
            <button
              onClick={handleSend}
              disabled={isSending || !input.trim()}
              className="rounded-sm border border-brasssoft bg-brass/10 px-4 py-2.5 text-sm font-medium text-brass transition-colors hover:bg-brass/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Ask
            </button>
          </div>
          {messages.length > 0 && (
            <button
              onClick={handleNewConversation}
              className="mt-2 self-start font-mono text-[11px] text-slate hover:text-brass"
            >
              ↺ new conversation
            </button>
          )}
        </div>

        {/* Sidebar */}
        <aside className="flex min-h-0 flex-col rounded-sm border border-line bg-panel/40">
          <UploadPanel onUploaded={refreshHealth} />
        </aside>
      </div>
    </main>
  );
}
