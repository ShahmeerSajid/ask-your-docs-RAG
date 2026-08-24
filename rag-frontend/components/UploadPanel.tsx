"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadDocument, listDocuments, deleteDocument, type DocumentInfo } from "@/lib/api";

const ACCEPTED = [".pdf", ".txt", ".md"];

export default function UploadPanel({
  onUploaded,
}: {
  onUploaded: () => void;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(true);
  const [deletingFilename, setDeletingFilename] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshDocs = useCallback(async () => {
    try {
      const result = await listDocuments();
      setDocs(result);
    } catch {
      // If this fails, leave the last-known list showing rather than blanking it --
      // a transient fetch failure isn't the same as "no documents."
    } finally {
      setIsLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    refreshDocs();
  }, [refreshDocs]);

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
        await uploadDocument(file);
        await refreshDocs();
        onUploaded();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Upload failed.");
      } finally {
        setIsUploading(false);
      }
    },
    [onUploaded, refreshDocs]
  );

  const handleDelete = useCallback(
    async (filename: string) => {
      setError(null);
      setDeletingFilename(filename);
      try {
        await deleteDocument(filename);
        await refreshDocs();
        onUploaded(); // also refreshes the health/"indexed" indicator
      } catch (e) {
        setError(e instanceof Error ? e.message : "Delete failed.");
      } finally {
        setDeletingFilename(null);
      }
    },
    [onUploaded, refreshDocs]
  );

  return (
    <div className="flex min-h-0 flex-col border-t border-line p-4">
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

      <p className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-wider text-slate">
        In the archive
      </p>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoadingDocs ? (
          <p className="font-mono text-[11px] text-slate/60">loading…</p>
        ) : docs.length === 0 ? (
          <p className="font-mono text-[11px] text-slate/60">nothing indexed yet</p>
        ) : (
          <ul className="space-y-1.5">
            {docs.map((d) => (
              <li
                key={d.filename}
                className="group flex items-center justify-between gap-2 rounded-sm border border-line/60 px-2 py-1.5"
              >
                <div className="min-w-0">
                  <p className="truncate font-mono text-[11px] text-parchment">
                    {d.filename}
                  </p>
                  <p className="font-mono text-[10px] text-brass/70">{d.chunks} chunks</p>
                </div>
                <button
                  onClick={() => handleDelete(d.filename)}
                  disabled={deletingFilename === d.filename}
                  title={`Remove ${d.filename} from the archive`}
                  className="shrink-0 rounded-sm px-1.5 py-1 font-mono text-[11px] text-slate opacity-60 transition-colors hover:bg-rust/10 hover:text-rust hover:opacity-100 disabled:opacity-30"
                >
                  {deletingFilename === d.filename ? "…" : "✕"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
