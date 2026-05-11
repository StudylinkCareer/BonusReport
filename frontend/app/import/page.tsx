'use client'

/**
 * SAVE TO: frontend/app/import/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\import\page.tsx)
 *
 * Import Board — CRM file upload page. Two upload modes:
 *   - 'individual'  / "Input sheet" tab : drag/drop one or more closed-file
 *                     xlsx reports; year/month derived from filename, period
 *                     validated against the file header. Posts to POST /api/imports.
 *   - 'consolidated'/ "Mass Upload" tab : single mass-upload xlsx (every
 *                     status across many months in one sheet); period derived
 *                     per row. Posts to POST /api/imports/consolidated.
 *
 * Results from either mode appear in the same Uploaded pillar on the home page.
 */

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

type Mode = 'individual' | 'consolidated'

type FileSummary = {
  inserted: number
  updated: number
  rows_skipped: number
  notes_attached: number
  notes_orphan: number
  error_count: number
}

type FileResult = {
  success: boolean
  filename: string | null
  error?: string
  warning?: string
  import_run_id?: number
  run_year?: number
  run_month?: number
  staff_id?: number | null
  file_path?: string
  summary?: FileSummary
  errors?: string[]
}

type UploadResponse = {
  total_files: number
  successful: number
  failed: number
  files: FileResult[]
}

export default function UploadPage() {
  const router = useRouter()
  const [mode, setMode] = useState<Mode>('individual')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [response, setResponse] = useState<UploadResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const onPick = (filelist: FileList | null) => {
    if (!filelist) return
    const valid = Array.from(filelist).filter((f) => /\.(xlsx|xlsm)$/i.test(f.name))
    const invalid = Array.from(filelist).filter((f) => !/\.(xlsx|xlsm)$/i.test(f.name))
    // Consolidated mode is single-file only
    const next = mode === 'consolidated' ? valid.slice(0, 1) : [...files, ...valid]
    setFiles(next)
    if (invalid.length) {
      setError(`Skipped ${invalid.length} non-Excel file(s): ${invalid.map((f) => f.name).join(', ')}`)
    } else {
      setError(null)
    }
  }

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const switchMode = (next: Mode) => {
    if (next === mode) return
    setMode(next)
    setFiles([])
    setResponse(null)
    setError(null)
  }

  const onUpload = async () => {
    if (files.length === 0) {
      setError('Please select at least one file.')
      return
    }
    setUploading(true)
    setError(null)
    setResponse(null)

    const endpoint = mode === 'consolidated' ? '/api/imports/consolidated' : '/api/imports'

    const fd = new FormData()
    if (mode === 'consolidated') {
      fd.append('file', files[0])
    } else {
      for (const f of files) fd.append('files', f)
    }

    try {
      const res = await fetch(endpoint, { method: 'POST', body: fd })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Upload failed (${res.status})`)
      }
      const body: UploadResponse = await res.json()
      setResponse(body)
      setFiles([])
    } catch (e: any) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      {/* Header with back-to-home link */}
      <nav className="mb-4 text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-900 hover:underline">← Back to Case workflow</Link>
      </nav>

      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Upload Cases</h1>
          <p className="mt-1 text-sm text-gray-600">
            Two formats supported. Pick the right one for your file.
          </p>
        </div>
        <button
          onClick={() => router.push('/imports')}
          className="rounded bg-gray-200 px-3 py-1 text-sm hover:bg-gray-300"
        >
          View upload history
        </button>
      </header>

      {/* Mode tabs */}
      <div className="mb-4 flex gap-0 border-b border-gray-200">
        <ModeTab
          label="Input sheet"
          sub="One file per staff member per month"
          active={mode === 'individual'}
          onClick={() => switchMode('individual')}
        />
        <ModeTab
          label="Mass Upload"
          sub="Single consolidated file across all staff/months"
          active={mode === 'consolidated'}
          onClick={() => switchMode('consolidated')}
        />
      </div>

      {mode === 'individual' ? <IndividualNote /> : <ConsolidatedNote />}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          onPick(e.dataTransfer.files)
        }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded border-2 border-dashed p-10 text-center transition ${
          dragOver
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
        }`}
      >
        <p className="text-sm text-gray-700">
          {dragOver
            ? 'Drop files here…'
            : mode === 'consolidated'
            ? 'Drag one file here, or click to browse'
            : 'Drag files here, or click to browse'}
        </p>
        <p className="mt-1 text-xs text-gray-500">.xlsx or .xlsm only</p>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xlsm"
          multiple={mode === 'individual'}
          onChange={(e) => onPick(e.target.files)}
          className="hidden"
        />
      </div>

      {/* Pending list */}
      {files.length > 0 && (
        <div className="mt-4">
          <h2 className="mb-2 text-sm font-semibold">
            Files to upload ({files.length}):
          </h2>
          <ul className="divide-y divide-gray-100 rounded border border-gray-200">
            {files.map((f, i) => (
              <li key={i} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="truncate" title={f.name}>{f.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="text-xs text-red-600 hover:underline"
                  disabled={uploading}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Action buttons */}
      {files.length > 0 && (
        <div className="mt-4 flex gap-2">
          <button
            onClick={onUpload}
            disabled={uploading}
            className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          >
            {uploading
              ? `Uploading ${files.length} file(s)…`
              : `Upload ${files.length} file(s)`}
          </button>
          <button
            onClick={() => setFiles([])}
            disabled={uploading}
            className="rounded bg-gray-200 px-4 py-2 text-sm"
          >
            Clear
          </button>
        </div>
      )}

      {/* Errors / warnings */}
      {error && (
        <div className="mt-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Per-file results */}
      {response && (
        <div className="mt-6">
          <h2 className="mb-3 font-semibold">
            Upload results — {response.successful} succeeded, {response.failed} failed
          </h2>
          <ul className="space-y-2">
            {response.files.map((r, i) => (
              <li
                key={i}
                className={`rounded border px-4 py-3 text-sm ${
                  r.success
                    ? 'border-green-200 bg-green-50'
                    : 'border-red-200 bg-red-50'
                }`}
              >
                <div className="mb-1 font-mono text-xs">{r.filename ?? '(no filename)'}</div>
                {r.success ? (
                  <div className="flex items-center justify-between">
                    <div>
                      {r.run_year && r.run_month && (
                        <>Period: <strong>{r.run_year}-{String(r.run_month).padStart(2, '0')}</strong>{' · '}</>
                      )}
                      Inserted: {r.summary?.inserted ?? 0}
                      {r.summary && r.summary.updated > 0 && <>, Updated: {r.summary.updated}</>}
                      {r.summary?.error_count
                        ? <span className="text-amber-700">, Errors: {r.summary.error_count}</span>
                        : null}
                    </div>
                    <Link
                      href="/"
                      className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
                    >
                      View on home →
                    </Link>
                  </div>
                ) : (
                  <div className="text-red-700">{r.error}</div>
                )}
                {r.warning && (
                  <div className="mt-1 text-xs text-amber-700">⚠ {r.warning}</div>
                )}
              </li>
            ))}
          </ul>
          <div className="mt-4 flex gap-2">
            <Link
              href="/"
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
            >
              Back to Case workflow
            </Link>
            <button
              onClick={() => setResponse(null)}
              className="rounded bg-gray-200 px-4 py-2 text-sm hover:bg-gray-300"
            >
              Upload more
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ---------------- helpers ---------------- */

function ModeTab({
  label, sub, active, onClick,
}: { label: string; sub: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2.5 text-left transition border-b-2 -mb-px ${
        active
          ? 'border-blue-600 text-blue-700 bg-blue-50/40'
          : 'border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-50'
      }`}
    >
      <div className="text-sm font-medium">{label}</div>
      <div className="text-xs text-gray-500">{sub}</div>
    </button>
  )
}

function IndividualNote() {
  return (
    <div className="mb-4 rounded border border-gray-200 bg-gray-50 px-4 py-3 text-xs text-gray-700">
      <strong>Input sheet mode.</strong> Each file should be a single staff member&apos;s
      closed-file report for one month, with a filename like{' '}
      <code className="font-mono">Phạm Thị Lợi&apos;s report of closed file in July 2025.xlsx</code>.
      Year and month are read from the filename automatically.
    </div>
  )
}

function ConsolidatedNote() {
  return (
    <div className="mb-4 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
      <strong>Mass Upload mode.</strong> A single consolidated xlsx containing every closed-file row across many
      months and staff (the format we use for regression testing). The period for each row is derived from its
      status + date columns. Cases land in the same Uploaded pillar as Input sheet imports — once loaded, they look identical in the Review Board.
    </div>
  )
}
