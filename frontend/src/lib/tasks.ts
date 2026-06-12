// Task API calls.

import { apiFetch } from '@/lib/api'
import type {
  SelectableUser,
  Task,
  TaskInput,
  TaskListResponse,
  TaskPriority,
  TaskStatus,
} from '@/types'

export interface ListTasksParams {
  q?: string
  status?: TaskStatus
  priority?: TaskPriority
  assigned_to_id?: number
  customer_id?: number
  job_id?: number
  overdue?: boolean
  limit?: number
  offset?: number
}

export function listTasks(params: ListTasksParams = {}): Promise<TaskListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.status) search.set('status', params.status)
  if (params.priority) search.set('priority', params.priority)
  if (params.assigned_to_id != null) search.set('assigned_to_id', String(params.assigned_to_id))
  if (params.customer_id != null) search.set('customer_id', String(params.customer_id))
  if (params.job_id != null) search.set('job_id', String(params.job_id))
  if (params.overdue) search.set('overdue', 'true')
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiFetch<TaskListResponse>(`/tasks${qs ? `?${qs}` : ''}`)
}

export function getTask(id: number): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`)
}

export function createTask(input: TaskInput): Promise<Task> {
  return apiFetch<Task>('/tasks', { method: 'POST', body: input })
}

export function updateTask(id: number, input: TaskInput): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}`, { method: 'PATCH', body: input })
}

export function completeTask(id: number, notes?: string): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}/complete`, {
    method: 'POST',
    body: { notes: notes || null },
  })
}

export function reopenTask(id: number): Promise<Task> {
  return apiFetch<Task>(`/tasks/${id}/reopen`, { method: 'POST', body: {} })
}

export function deleteTask(id: number): Promise<void> {
  return apiFetch<void>(`/tasks/${id}`, { method: 'DELETE' })
}

export function listSelectableUsers(): Promise<SelectableUser[]> {
  return apiFetch<SelectableUser[]>('/users/selectable')
}
