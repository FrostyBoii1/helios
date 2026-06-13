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

// ---- Imports (review of staged workbooks — admin only, mirrors backend) ----
export function canReviewImports(role: RoleName | undefined): boolean {
  return role === 'admin'
}

// ---- Tasks (per-task, evaluated against the current user) ----
interface TaskOwnership {
  created_by_id: number | null
  assigned_to_id: number | null
  status: string
}

export function canCreateTasks(role: RoleName | undefined): boolean {
  return role != null // any authenticated role
}

export function canEditTask(role: RoleName | undefined, userId: number | undefined, task: TaskOwnership): boolean {
  return role === 'admin' || (userId != null && task.created_by_id === userId)
}

export function canCompleteTask(
  role: RoleName | undefined,
  userId: number | undefined,
  task: TaskOwnership,
): boolean {
  return role === 'admin' || (userId != null && task.assigned_to_id === userId)
}

export function canDeleteTasks(role: RoleName | undefined): boolean {
  return role === 'admin'
}
