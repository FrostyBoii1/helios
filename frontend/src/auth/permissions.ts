// Frontend permission helpers (UX gating only — the backend re-checks everything).
// Mirrors the approved customer permission matrix.

import type { RoleName } from '@/types'

export function canWriteCustomers(role: RoleName | undefined): boolean {
  return role === 'admin' || role === 'sales_admin'
}

export function canDeleteCustomers(role: RoleName | undefined): boolean {
  return role === 'admin'
}

// ---- Jobs (mirror the approved Jobs permission matrix) ----
export function canCreateJobs(role: RoleName | undefined): boolean {
  return role === 'admin' || role === 'sales_admin'
}

export function canEditJobDetails(role: RoleName | undefined): boolean {
  return role === 'admin' || role === 'sales_admin'
}

export function canEditJobInstallDate(role: RoleName | undefined): boolean {
  return role === 'admin' || role === 'scheduling'
}

export function canChangeJobStatus(role: RoleName | undefined): boolean {
  return (
    role === 'admin' ||
    role === 'sales_admin' ||
    role === 'scheduling' ||
    role === 'approvals'
  )
}

export function canDeleteJobs(role: RoleName | undefined): boolean {
  return role === 'admin'
}
