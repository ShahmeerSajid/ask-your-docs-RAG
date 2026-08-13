"use client";

import { useCallback, useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";

type UploadedDoc = {
  filename: string;
  chunks: number;
};

const ACCEPTED = [".pdf", ".txt", ".md"];

export default function UploadPanel({
  onUploaded,
}: {
  onUploaded: () => void;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState<UploadedDoc[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const file = files[0];
      const ext = "." + file.name.split(".").pop()?.toLowerCase();
      if (!ACCEPTED.includes(ext)) {
        setError(`Unsupported file type. Use ${ACCEPTED.join(", ")}.`);
        return;
      }
      setError(null);
      setIsUploading(true);
      try {
        const result = await uploadDocument(file);
        setDocs((prev) => [...prev, { filename: result.filename, chunks: result.chunks_added }]);
        onUploaded();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed.");
      } finally {
        setIsUploading(false);
      }
    },
    [onUploaded]
  );

  return (
    <div className="border-t border-line p-4">
      <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-slate">
        Add to the archive
      </p>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`relative cursor-pointer overflow-hidden rounded-sm border border-dashed px-4 py-5 text-center transition-colors ${
          isDragging
            ? "border-brass bg-brass/5"
            : "border-line hover:border-brasssoft"
        }`}
      >
        {isUploading && (
          <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden bg-line">
            <div className="animate-scan h-full w-1/3 bg-brass" />
          </div>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <p className="text-sm text-slate">
          {isUploading ? (
            "Embedding…"
          ) : (
            <>
              Drop a file, or{" "}
              <span className="text-brass underline underline-offset-2">browse</span>
            </>
          )}
        </p>
        <p className="mt-1 font-mono text-[10px] text-slate/60">PDF · TXT · MD</p>
      </div>

      {error && <p className="mt-2 text-xs text-rust">{error}</p>}

      {docs.length > 0 && (
        <ul className="mt-3 space-y-1">
          {docs.map((d, i) => (
            <li
              key={i}
              className="flex items-center justify-between font-mono text-[11px] text-slate"
            >
              <span className="truncate">{d.filename}</span>
              <span className="text-brass/70">{d.chunks} chunks</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
