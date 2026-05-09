'use client'

/**
 * frontend/app/import/page.tsx
 *
 * CRM file upload page. Multi-file, drag-and-drop, year/month derived
 * from each filename by the backend.
 *
 * Talks to: POST /api/imports  (multipart, field name "files")
 */

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

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
    setFiles((prev) => [...prev, ...valid])
    if (invalid.length) {
      setError(`Skipped ${invalid.length} non-Excel file(s): ${invalid.map((f) => f.name).join(', ')}`)
    } else {
      setError(null)
    }
  }

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const onUpload = async () => {
    if (files.length === 0) {
      setError('Please select at least one file.')
      return
    }
    setUploading(true)
    setError(null)
    setResponse(null)

    const fd = new FormData()
    for (const f of files) fd.append('files', f)

    try {
      const res = await fetch('/api/imports', { method: 'POST', body: fd })
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
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Upload CRM Reports</h1>
          <p className="mt-1 text-sm text-gray-600">
            Drag and drop or pick one or more closed-file xlsx reports. Year and
            month are read from each filename automatically.
          </p>
        </div>
        <button
          onClick={() => router.push('/imports')}
          className="rounded bg-gray-200 px-3 py-1 text-sm"
        >
          View all imports
        </button>
      </header>

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
          {dragOver ? 'Drop files here…' : 'Drag files here, or click to browse'}
        </p>
        <p className="mt-1 text-xs text-gray-500">.xlsx or .xlsm only</p>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xlsm"
          multiple
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
                      Period: <strong>{r.run_year}-{String(r.run_month).padStart(2, '0')}</strong>
                      {' · '}
                      Inserted: {r.summary?.inserted}, Updated: {r.summary?.updated}
                      {r.summary?.error_count
                        ? <span className="text-amber-700">, Errors: {r.summary.error_count}</span>
                        : null}
                    </div>
                    <button
                      onClick={() => {
                        const params = new URLSearchParams({
                          year: String(r.run_year),
                          month: String(r.run_month),
                        })
                        if (r.staff_id) params.set('staff_id', String(r.staff_id))
                        router.push(`/import/review?${params.toString()}`)
                      }}
                      className="rounded bg-blue-600 px-3 py-1 text-xs text-white"
                    >
                      Review →
                    </button>
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
            <button
              onClick={() => router.push('/imports')}
              className="rounded bg-gray-200 px-4 py-2 text-sm"
            >
              View all imports
            </button>
            <button
              onClick={() => setResponse(null)}
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white"
            >
              Upload more
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
