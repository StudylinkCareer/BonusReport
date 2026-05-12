'use client';

/**
 * SAVE TO: frontend/lib/role.ts
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\lib\role.ts)
 *
 * Temporary role-switching for the "Acting as" UI. Persists the current
 * acting role in localStorage so it survives page refreshes, and
 * broadcasts changes via a window event so all open components see the
 * update without needing to refresh.
 *
 * This is a STUB. Real auth/role enforcement comes later. For now this
 * just lets us demo the staff vs review-team UX (pre-selected vs open
 * checkboxes on the Uploaded pillar).
 *
 * Usage:
 *   const [role, setRole] = useRole();
 *   if (role.kind === 'staff') { ... role.staffId, role.staffName ... }
 */

import { useEffect, useState } from 'react';

export type Role =
  | { kind: 'admin' }
  | { kind: 'staff'; staffId: number; staffName: string };

const STORAGE_KEY = 'bonusreport.role';
const EVENT_NAME = 'bonusreport.role.changed';

function readRole(): Role {
  if (typeof window === 'undefined') return { kind: 'admin' };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { kind: 'admin' };
    const parsed = JSON.parse(raw);
    if (parsed?.kind === 'admin') return { kind: 'admin' };
    if (
      parsed?.kind === 'staff' &&
      typeof parsed.staffId === 'number' &&
      typeof parsed.staffName === 'string'
    ) {
      return parsed as Role;
    }
  } catch {
    // fall through to default
  }
  return { kind: 'admin' };
}

export function useRole(): [Role, (next: Role) => void] {
  const [role, setRoleState] = useState<Role>(() => readRole());

  useEffect(() => {
    const handler = () => setRoleState(readRole());
    // Custom event for same-tab updates
    window.addEventListener(EVENT_NAME, handler);
    // Storage event for cross-tab updates
    window.addEventListener('storage', handler);
    return () => {
      window.removeEventListener(EVENT_NAME, handler);
      window.removeEventListener('storage', handler);
    };
  }, []);

  const setRole = (next: Role) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore quota / privacy-mode errors
    }
    setRoleState(next);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event(EVENT_NAME));
    }
  };

  return [role, setRole];
}

export function roleLabel(role: Role): string {
  return role.kind === 'admin' ? 'Admin' : role.staffName;
}
