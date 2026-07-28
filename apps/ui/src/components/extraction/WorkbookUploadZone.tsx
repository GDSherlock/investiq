'use client';

import {
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from 'react';

interface WorkbookUploadZoneProps {
  selectedFile: File | null;
  busy: boolean;
  hasError: boolean;
  canRetry: boolean;
  onFileSelected: (file: File) => void;
  onRetry: () => void;
}

export function WorkbookUploadZone({
  selectedFile,
  busy,
  hasError,
  canRetry,
  onFileSelected,
  onRetry,
}: WorkbookUploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const chooseFile = () => {
    if (!busy) {
      inputRef.current?.click();
    }
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.currentTarget.files?.[0];
    if (nextFile && !busy) {
      onFileSelected(nextFile);
    }
    // Browsers otherwise suppress change when the same file is chosen again.
    event.currentTarget.value = '';
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const nextFile = event.dataTransfer.files?.[0];
    if (nextFile && !busy) {
      onFileSelected(nextFile);
    }
  };

  return (
    <section
      data-testid="workbook-drop-zone"
      onDragEnter={(event) => {
        event.preventDefault();
        if (!busy) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      aria-busy={busy}
      className={`mx-auto max-w-3xl rounded-xl border-2 border-dashed px-5 py-8 text-center transition sm:px-8 sm:py-9 ${
        dragging
          ? 'border-gold-400 bg-gold-500/10'
          : 'border-slate-400/80 bg-d-card/30'
      } ${busy ? 'cursor-wait opacity-75' : ''}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx"
        disabled={busy}
        onChange={handleChange}
        className="sr-only"
        aria-label="Choose Excel workbook"
      />

      <div className="mx-auto flex max-w-xl flex-col items-center justify-center gap-5 sm:flex-row">
        <div
          className="relative flex h-20 w-16 shrink-0 items-center justify-center rounded-md border border-slate-400 bg-navy-100 text-emerald-300"
          aria-hidden="true"
        >
          <span className="absolute -right-px -top-px h-5 w-5 border-b border-l border-slate-400 bg-d-bg [clip-path:polygon(100%_0,100%_100%,0_0)]" />
          <span className="text-3xl font-semibold">X</span>
        </div>

        <div>
          <p className="text-base font-medium text-white">
            {busy
              ? 'Uploading and analyzing your workbook'
              : 'Drag & drop your Excel workbook here'}
          </p>
          {!busy ? <p className="mt-1 text-sm text-d-muted">or</p> : null}
          {!busy && !hasError ? (
            <button
              type="button"
              onClick={chooseFile}
              className="mt-3 rounded-md bg-gold-500 px-6 py-2.5 text-sm font-semibold text-navy-950 shadow-sm transition hover:bg-gold-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-gold-300"
            >
              Choose File
            </button>
          ) : null}
          {selectedFile ? (
            <p className="mt-3 break-all text-sm text-slate-300">
              {selectedFile.name}
            </p>
          ) : null}
          <p className="mt-3 text-xs text-d-muted">
            Supports .xlsx (max 25 MB)
          </p>
        </div>
      </div>

      {hasError ? (
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          <button
            type="button"
            disabled={!canRetry || busy}
            onClick={onRetry}
            className="rounded-md bg-gold-500 px-5 py-2 text-sm font-semibold text-navy-950 transition hover:bg-gold-400 disabled:cursor-not-allowed disabled:bg-slate-600 disabled:text-slate-300"
          >
            Retry upload
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={chooseFile}
            className="rounded-md border border-slate-500 px-5 py-2 text-sm font-medium text-white transition hover:bg-d-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            Choose another file
          </button>
        </div>
      ) : null}
    </section>
  );
}
