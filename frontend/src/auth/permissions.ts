// Frontend permission helpers (UX gating only — the backend re-checks everything).
// Mirrors the approved customer permission matrix.

import type { RoleName } from '@/types'

export function canWriteCustomers(role: RoleName | undefined): boolean {
  return role === 'admin' || role === 'sales_admin'
}

export function canDeleteCustomers(role: RoleName | undefined): boolean {
  return role === 'admin'
}
