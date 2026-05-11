'use client'

/**
 * frontend/app/imports/page.tsx
 *
 * Upload-event history. Every row here is one POST to /api/imports (or
 * /api/imports/consolidated) from the web UI — i.e. one Upload action.
 *
 * Note: this is intentionally an audit log of UPLOAD EVENTS, not a count
 * of cases. CLI-driven imports (e.g. regression-test bulk loads) are not
 * tracked here yet; for total case counts see the home page pillars.
 */

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'

type ImportRun = {
  id: number
  original_filename: string
  file_path: string
  run_year: number
  run_month: number
  staff_id?: number | null
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

  // Aggregate counts across uploads (just for the reconciliation note)
  const totalInsertedHere = imports.reduce((s, r) => s + (r.inserted_count ?? 0), 0)

  return (
    <div className="mx-auto max-w-7xl p-6">
      <nav className="mb-4 text-sm text-gray-500">
        <Link href="/" className="hover:text-gray-900 hover:underline">← Back to Case workflow</Link>
      </nav>

      <header className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Upload history</h1>
          <p className="mt-1 text-sm text-gray-600">
            Every file you&apos;ve uploaded through the web UI, most recent first.
          </p>
        </div>
        <button
          onClick={() => router.push('/import')}
          className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
        >
          + New Upload
        </button>
      </header>

      {/* Reconciliation note */}
      <div className="mb-4 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900">
        <strong>About this list.</strong> These are <em>upload events</em>, not cases.
        One upload can insert many cases (see the &ldquo;Inserted&rdquo; column).
        {!loading && !error && imports.length > 0 && (
          <>
            {' '}This page shows <strong>{imports.length}</strong> upload event(s)
            totalling <strong>{totalInsertedHere.toLocaleString()}</strong> case insertion(s).
          </>
        )}{' '}
        <br />
        Cases imported via the command-line (regression testing, bulk reloads)
        are not tracked here — for the authoritative total see the pillar counts on the home page.
      </div>

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
              {imports.map((r, idx) => (
                <tr
                  key={r.id}
                  className={`border-b border-gray-100 hover:bg-blue-50 ${
                    idx % 2 === 0 ? 'bg-white' : 'bg-slate-50'
                  }`}
                >
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
                      onClick={() => {
                        const params = new URLSearchParams({
                          year: String(r.run_year),
                          month: String(r.run_month),
                        })
                        if (r.staff_id) params.set('staff_id', String(r.staff_id))
                        router.push(`/import/review?${params.toString()}`)
                      }}
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
