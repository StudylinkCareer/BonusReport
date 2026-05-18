'use client'

/**
 * SAVE TO: frontend/app/_components/AuthProvider.tsx
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\app\_components\AuthProvider.tsx)
 *
 * The underscore prefix on the folder name tells Next.js NOT to treat it
 * as a route — it's a regular shared components folder.
 *
 * This component wraps every page in the app (via layout.tsx) and:
 *   1. On page load, calls GET /api/auth/me to find out who's logged in
 *   2. If 401 and the user isn't already on /login, redirects to /login
 *   3. If 200, exposes the user info via React context so any page can
 *      do `const { user } = useAuth()` to get the current user
 *   4. Renders a small fixed badge in the top-right showing the user's
 *      name + a Logout button
 *
 * The auth_token cookie is HttpOnly, so this code never touches it
 * directly. The browser sends it automatically on every /api/* call.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from 'react'
import { useRouter, usePathname } from 'next/navigation'

// Mirror of UserInfo from backend/auth/models.py
type User = {
  id: number
  email: string
  display_name: string
  roles: string[]
  staff_id: number | null
  linked_staff_name: string | null
}

type AuthContextValue = {
  user: User | null
  loading: boolean
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

/** Hook for pages to access the current user.
 *  Example:
 *      const { user, logout } = useAuth()
 *      if (user.roles.includes('DIRECTOR')) { ... }
 */
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

// Pages that don't require a logged-in user.
const PUBLIC_PATHS = ['/login']

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname() ?? ''
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const isPublicPage = PUBLIC_PATHS.includes(pathname)

  useEffect(() => {
    let cancelled = false
    fetch('/api/auth/me')
      .then((r) => {
        if (r.status === 401) return null
        if (!r.ok) throw new Error(`/api/auth/me returned ${r.status}`)
        return r.json() as Promise<User>
      })
      .then((data) => {
        if (cancelled) return
        setUser(data)
        setLoading(false)
        if (!data && !isPublicPage) {
          router.replace('/login')
        }
      })
      .catch(() => {
        if (cancelled) return
        setLoading(false)
        if (!isPublicPage) router.replace('/login')
      })
    return () => {
      cancelled = true
    }
  }, [pathname, isPublicPage, router])

  const logout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
      router.replace('/login')
    }
  }

  // While we're checking the cookie, don't flash a partial UI.
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-gray-500">
        Loading…
      </div>
    )
  }

  // Not logged in + not on a public page: router is about to redirect us
  // to /login, so render nothing in the meantime to avoid a flash of
  // protected content.
  if (!user && !isPublicPage) {
    return null
  }

  return (
    <AuthContext.Provider value={{ user, loading, logout }}>
      {children}
      {user && <UserBadge user={user} onLogout={logout} />}
    </AuthContext.Provider>
  )
}

function UserBadge({
  user,
  onLogout,
}: {
  user: User
  onLogout: () => void
}) {
  return (
    <div className="fixed right-3 bottom-3 z-50 flex items-center gap-2 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs shadow-sm">
      <div className="flex flex-col leading-tight">
        <span className="font-medium text-gray-800">{user.display_name}</span>
        <span className="text-[10px] text-gray-500">
          {user.roles.length > 0 ? user.roles.join(', ') : 'no roles'}
        </span>
      </div>
      <button
        onClick={onLogout}
        className="ml-1 rounded bg-gray-100 px-2 py-0.5 text-gray-700 hover:bg-gray-200"
      >
        Logout
      </button>
    </div>
  )
}
