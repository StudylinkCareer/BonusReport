'use client'

/**
 * frontend/app/imports/page.tsx
 *
 * Imports list page. Shows every upload from tx_import_run, most recent
 * first. Each row links to the Review page for that period.
 *
 * Talks to: GET /api/imports
 */

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

type ImportRun = {
  id: number
  original_filename: string
  file_path: string
  run_year: number
  run_month: number
  uploaded_at: string
  inserted_count: number
  updated_count: number
  rows_skipped_count: number
  notes_attached_count: number
  notes_orphan_count: number
  error_count: number
  errors_json: string[] | null
  current_state: string
  created_at: string
  updated_at: string
}

const STATE_STYLES: Record<string, string> = {
  pending:  'bg-amber-100 text-amber-800 border-amber-300',
  approved: 'bg-green-100 text-green-800 border-green-300',
  archived: 'bg-gray-100 text-gray-700 border-gray-300',
}

function StateBadge({ state }: { state: string }) {
  const cls = STATE_STYLES[state] ?? 'bg-gray-100 text-gray-700 border-gray-300'
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {state}
    </span>
  )
}

export default function ImportsListPage() {
  const router = useRouter()
  const [imports, setImports] = useState<ImportRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/imports')
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load imports (${res.status})`)
        return res.json()
      })
      .then((data: ImportRun[]) => {
        setImports(data)
        setLoading(false)
      })
      .catch((e: any) => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  return (
    <div className="p-6">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Imports</h1>
          <p className="mt-1 text-sm text-gray-600">
            All CRM uploads, most recent first.
          </p>
        </div>
        <button
          onClick={() => router.push('/import')}
          className="rounded bg-blue-600 px-4 py-2 text-white"
        >
          + New Upload
        </button>
      </header>

      {loading && (
        <div className="py-12 text-center text-gray-500">Loading…</div>
      )}

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-red-800">
          <strong>Error:</strong> {error}
        </div>
      )}

      {!loading && !error && imports.length === 0 && (
        <div className="py-12 text-center text-gray-500">
          No uploads yet. Click <strong>+ New Upload</strong> to add one.
        </div>
      )}

      {!loading && !error && imports.length > 0 && (
        <div className="overflow-auto rounded border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="border-b border-gray-200 text-left">
                <th className="px-3 py-2 font-semibold">Period</th>
                <th className="px-3 py-2 font-semibold">Filename</th>
                <th className="px-3 py-2 font-semibold">Uploaded</th>
                <th className="px-3 py-2 font-semibold">Inserted</th>
                <th className="px-3 py-2 font-semibold">Updated</th>
                <th className="px-3 py-2 font-semibold">Skipped</th>
                <th className="px-3 py-2 font-semibold">Errors</th>
                <th className="px-3 py-2 font-semibold">State</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {imports.map((r) => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-2 font-mono">
                    {r.run_year}-{String(r.run_month).padStart(2, '0')}
                  </td>
                  <td
                    className="max-w-md truncate px-3 py-2"
                    title={r.original_filename}
                  >
                    {r.original_filename}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {new Date(r.uploaded_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">{r.inserted_count}</td>
                  <td className="px-3 py-2">{r.updated_count}</td>
                  <td className="px-3 py-2 text-gray-500">{r.rows_skipped_count}</td>
                  <td className="px-3 py-2">
                    {r.error_count > 0 ? (
                      <span className="font-semibold text-red-600">{r.error_count}</span>
                    ) : (
                      <span className="text-gray-400">0</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <StateBadge state={r.current_state} />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() =>
                        router.push(`/import/review?year=${r.run_year}&month=${r.run_month}`)
                      }
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Review →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
