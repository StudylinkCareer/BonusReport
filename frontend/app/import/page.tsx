'use client';

import { useState, useEffect, FormEvent } from 'react';

type Staff = {
  id: number;
  name: string;
  role_code: string;
  office_code: string;
};

type ImportResult = {
  filename: string;
  year: number;
  month: number;
  inserted: number;
  updated: number;
  rows_skipped: number;
  notes_attached: number;
  notes_orphan: number;
  errors: string[];
};

export default function ImportPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [staffId, setStaffId] = useState<number | null>(null);
  const [year, setYear] = useState(new Date().getFullYear());
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/staff')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setStaff)
      .catch((e) => setError(`Failed to load staff list: ${e}`));
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) {
      setError('Please choose a file');
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('year', String(year));
    formData.append('month', String(month));

    try {
      const res = await fetch('/api/imports', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      setResult(await res.json());
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-3xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">CRM Importer</h1>
        <p className="text-gray-600 mb-6">
          Upload a closed-file Excel report from the CRM. The system parses,
          resolves references, and writes cases to the database.
        </p>

        <form
          onSubmit={handleSubmit}
          className="space-y-5 bg-white p-6 rounded-lg shadow border border-gray-200"
        >
          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              Staff Member <span className="text-gray-400 font-normal">(reference only — backend infers from filename/data)</span>
            </label>
            <select
              value={staffId ?? ''}
              onChange={(e) =>
                setStaffId(e.target.value ? Number(e.target.value) : null)
              }
              className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">— pick a staff member —</option>
              {staff.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.role_code}, {s.office_code})
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1.5 text-gray-700">
                Year
              </label>
              <input
                type="number"
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                min={2020}
                max={2030}
                className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5 text-gray-700">
                Month
              </label>
              <input
                type="number"
                value={month}
                onChange={(e) => setMonth(Number(e.target.value))}
                min={1}
                max={12}
                className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5 text-gray-700">
              CRM Excel File
            </label>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="w-full p-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
            {file && (
              <p className="text-sm text-gray-600 mt-1.5">
                Selected: <span className="font-mono">{file.name}</span> (
                {(file.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </div>

          <button
            type="submit"
            disabled={submitting || !file}
            className="w-full bg-blue-600 text-white py-2.5 rounded font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Uploading and importing…' : 'Upload and Import'}
          </button>
        </form>

        {error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded">
            <p className="text-red-800 font-medium">Error</p>
            <p className="text-red-700 text-sm mt-1 font-mono whitespace-pre-wrap">
              {error}
            </p>
          </div>
        )}

        {result && (
          <div className="mt-4 p-5 bg-green-50 border border-green-200 rounded">
            <h2 className="font-semibold text-green-900 mb-3">
              Import complete
            </h2>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-gray-600">Filename</dt>
              <dd className="font-mono">{result.filename}</dd>
              <dt className="text-gray-600">Period</dt>
              <dd>
                {result.year}-{String(result.month).padStart(2, '0')}
              </dd>
              <dt className="text-gray-600">Inserted</dt>
              <dd className="font-semibold">{result.inserted}</dd>
              <dt className="text-gray-600">Updated</dt>
              <dd className="font-semibold">{result.updated}</dd>
              <dt className="text-gray-600">Skipped</dt>
              <dd className="font-semibold">{result.rows_skipped}</dd>
              <dt className="text-gray-600">Notes attached</dt>
              <dd>{result.notes_attached}</dd>
              <dt className="text-gray-600">Notes orphan</dt>
              <dd>{result.notes_orphan}</dd>
            </dl>
            {result.errors.length > 0 && (
              <div className="mt-4 pt-3 border-t border-green-200">
                <p className="font-semibold text-red-700 mb-1">
                  Per-row errors ({result.errors.length}):
                </p>
                <ul className="text-sm text-red-700 list-disc pl-5 space-y-0.5">
                  {result.errors.map((err, i) => (
                    <li key={i} className="font-mono">
                      {err}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {staffId && (
              <a
                href={`/import/review?staff_id=${staffId}&year=${result.year}&month=${result.month}`}
                className="inline-block mt-4 px-4 py-2 bg-blue-600 text-white rounded font-medium hover:bg-blue-700"
              >
                Review imported cases →
              </a>
            )}
          </div>
        )}
      </div>
    </main>
  );
}