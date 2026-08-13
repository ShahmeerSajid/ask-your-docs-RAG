"use client";

import SourceChips from "./SourceChips";
import type { SourceChunk } from "@/lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: SourceChunk[];
  pending?: boolean;
};

export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[75%] ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        <div
          className={`rounded-sm px-4 py-3 text-[15px] leading-relaxed ${
            isUser
              ? "bg-rust/15 border border-rust/30 text-parchment"
              : "bg-panel border border-line text-parchment"
          }`}
        >
          {message.pending ? (
            <span className="inline-flex items-center gap-1 text-slate">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brass" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brass [animation-delay:0.15s]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brass [animation-delay:0.3s]" />
            </span>
          ) : (
            <p className="whitespace-pre-wrap">{message.content}</p>
          )}
        </div>
        {!isUser && message.sources && <SourceChips sources={message.sources} />}
      </div>
    </div>
  );
}
