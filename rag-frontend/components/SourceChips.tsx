"use client";

import { useState } from "react";
import type { SourceChunk } from "@/lib/api";

export default function SourceChips({ sources }: { sources: SourceChunk[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {sources.map((s, i) => {
        const isOpen = openIndex === i;
        return (
          <div key={i} className="relative">
            <button
              onClick={() => setOpenIndex(isOpen ? null : i)}
              className="group flex items-center gap-1.5 rounded-sm border border-line bg-panel px-2.5 py-1 font-mono text-[11px] text-slate transition-colors hover:border-brasssoft hover:text-brass"
            >
              <span className="text-brass/70">§</span>
              {s.source}
              {s.page !== null ? `:${s.page}` : ""}
            </button>
            {isOpen && (
              <div className="absolute bottom-full left-0 z-10 mb-2 w-72 rounded-sm border border-line bg-panel p-3 shadow-lg shadow-black/40">
                <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-brass/80">
                  {s.source}
                  {s.page !== null ? ` — page ${s.page + 1}` : ""}
                </p>
                <p className="text-xs leading-relaxed text-slate">
                  {s.snippet}
                  {s.snippet.length >= 300 ? "…" : ""}
                </p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
