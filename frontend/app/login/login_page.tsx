'use client'

/**
 * SAVE TO: frontend/app/login/page.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\login\page.tsx)
 *
 * The login screen. Reachable at /login.
 *
 * Behaviour:
 *   - Submitting the form POSTs to /api/auth/login
 *   - On success: the backend sets the auth_token cookie and we redirect
 *     to / (the home page).
 *   - On 401: shows "invalid email or password"
 *   - On other errors: shows the error message from the API
 *
 * The AuthProvider in layout.tsx exempts this page from the "must be
 * logged in" redirect, so users who hit /login while logged out stay
 * here instead of bouncing back.
 */

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        const detail =
          typeof body?.detail === 'string'
            ? body.detail
            : `Login failed (${res.status})`
        throw new Error(detail)
      }

      // Cookie is set automatically by the backend. Hard-replace prevents
      // a Back button from returning to the login page after success.
      router.replace('/')
    } catch (e: any) {
      setError(e?.message ?? 'Login failed')
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 p-4">
      <div className="w-full max-w-sm rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
        <header className="mb-6">
          <h1 className="text-xl font-bold">Sign in</h1>
          <p className="mt-1 text-sm text-gray-600">StudyLink BonusReport</p>
        </header>

        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-gray-700"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-gray-700"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          {error && (
            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email || !password}
            className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </main>
  )
}
