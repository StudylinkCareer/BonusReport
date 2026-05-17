'use client';

/**
 * SAVE TO: frontend/lib/role.ts
 * (Full path: C:\Users\rhod_\Documents\BonusReport\Application\frontend\lib\role.ts)
 *
 * Role-switching for the "Acting as" UI. Persists the current acting role
 * in localStorage so it survives page refreshes, and broadcasts changes
 * via a window event so all open components see the update without needing
 * to refresh.
 *
 * The Role union has three kinds:
 *
 *   { kind: 'admin' }                       — admin operator (default)
 *   { kind: 'persona', personaCode, ... }   — one of 4 role personas
 *                                             (director, manager,
 *                                              quality_officer,
 *                                              finance_officer)
 *   { kind: 'staff', staffId, staffName }   — real staff member
 *
 * Each kind produces a distinct `actingAsKey()` value which is used as the
 * lookup key in the user_layout variant store.
 *
 * Usage:
 *   const [role, setRole] = useRole();
 *   if (role.kind === 'staff') { ... role.staffId, role.staffName ... }
 *   const key = actingAsKey(role);   // 'admin' | 'persona:director' | 'staff:42'
 */

import { useEffect, useState } from 'react';

// ----------------------------------------------------------------------------
// Personas
// ----------------------------------------------------------------------------

export type PersonaCode =
  | 'director'
  | 'manager'
  | 'quality_officer'
  | 'finance_officer';

// Canonical list — used by the picker to render the dropdown and by
// readRole() to validate the localStorage payload. Add new personas here
// in one place.
export const PERSONAS: ReadonlyArray<{
  code: PersonaCode;
  label: string;
}> = [
  { code: 'director',         label: 'Director' },
  { code: 'manager',          label: 'Manager' },
  { code: 'quality_officer',  label: 'Quality Officer' },
  { code: 'finance_officer',  label: 'Finance Officer' },
];

const PERSONA_CODES: ReadonlySet<string> = new Set(PERSONAS.map((p) => p.code));

// ----------------------------------------------------------------------------
// Role union
// ----------------------------------------------------------------------------

export type Role =
  | { kind: 'admin' }
  | { kind: 'persona'; personaCode: PersonaCode; personaName: string }
  | { kind: 'staff';   staffId: number; staffName: string };

const STORAGE_KEY = 'bonusreport.role';
const EVENT_NAME  = 'bonusreport.role.changed';

// ----------------------------------------------------------------------------
// Persistence
// ----------------------------------------------------------------------------

function readRole(): Role {
  if (typeof window === 'undefined') return { kind: 'admin' };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { kind: 'admin' };
    const parsed = JSON.parse(raw);

    if (parsed?.kind === 'admin') return { kind: 'admin' };

    if (
      parsed?.kind === 'persona' &&
      typeof parsed.personaCode === 'string' &&
      typeof parsed.personaName === 'string' &&
      PERSONA_CODES.has(parsed.personaCode)
    ) {
      return parsed as Role;
    }

    if (
      parsed?.kind === 'staff' &&
      typeof parsed.staffId === 'number' &&
      typeof parsed.staffName === 'string'
    ) {
      return parsed as Role;
    }
  } catch {
    // Malformed payload — fall through to default.
  }
  return { kind: 'admin' };
}

// ----------------------------------------------------------------------------
// Hook
// ----------------------------------------------------------------------------

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

// ----------------------------------------------------------------------------
// Display + variant-store key
// ----------------------------------------------------------------------------

export function roleLabel(role: Role): string {
  if (role.kind === 'admin')   return 'Admin';
  if (role.kind === 'persona') return role.personaName;
  return role.staffName;
}

/**
 * Encode the current role as the hierarchical string key used by
 * user_layout.acting_as. Format:
 *
 *   'admin'                 — admin persona
 *   'persona:<code>'        — one of the 4 role personas
 *   'staff:<staffId>'       — real staff member
 *
 * This is the stable key the backend uses to scope variant rows.
 */
export function actingAsKey(role: Role): string {
  if (role.kind === 'admin')   return 'admin';
  if (role.kind === 'persona') return `persona:${role.personaCode}`;
  return `staff:${role.staffId}`;
}
