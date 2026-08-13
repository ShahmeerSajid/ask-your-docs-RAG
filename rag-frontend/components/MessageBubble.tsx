"use client";

import ReactMarkdown from "react-markdown";
import SourceChips from "./SourceChips";
import type { SourceChunk } from "@/lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  sources?: SourceChunk[];
  pending?: boolean;
};

// Maps markdown elements to the archive theme's typography/spacing so a
// Gemini-generated markdown answer (bold, lists, headings, etc.) reads
// consistently with the rest of the UI instead of using browser defaults.
const markdownComponents = {
  p: (props: any) => <p className="mb-2 last:mb-0" {...props} />,
  strong: (props: any) => <strong className="font-semibold text-brass" {...props} />,
  em: (props: any) => <em className="italic" {...props} />,
  ul: (props: any) => <ul className="mb-2 ml-4 list-disc space-y-1 last:mb-0" {...props} />,
  ol: (props: any) => <ol className="mb-2 ml-4 list-decimal space-y-1 last:mb-0" {...props} />,
  li: (props: any) => <li className="pl-1" {...props} />,
  h1: (props: any) => <h1 className="mb-2 mt-1 font-display text-lg italic text-parchment" {...props} />,
  h2: (props: any) => <h2 className="mb-2 mt-1 font-display text-base italic text-parchment" {...props} />,
  h3: (props: any) => <h3 className="mb-1.5 mt-1 font-semibold text-parchment" {...props} />,
  code: (props: any) => (
    <code className="rounded-sm bg-ink px-1 py-0.5 font-mono text-[13px] text-brass" {...props} />
  ),
  a: (props: any) => (
    <a className="text-brass underline underline-offset-2 hover:text-brass/80" target="_blank" rel="noopener noreferrer" {...props} />
  ),
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
          ) : isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <ReactMarkdown components={markdownComponents}>{message.content}</ReactMarkdown>
          )}
        </div>
        {!isUser && message.sources && <SourceChips sources={message.sources} />}
      </div>
    </div>
  );
}
