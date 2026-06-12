import { useEffect, useState } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { canCreateTasks } from '@/auth/permissions'
import { TaskFormModal } from '@/components/TaskFormModal'
import {
  TASK_PRIORITY_LABELS,
  TASK_PRIORITY_ORDER,
  TASK_STATUS_LABELS,
  TASK_STATUS_ORDER,
} from '@/components/TaskBadges'
import { TasksTable } from '@/components/TasksTable'
import type { ListTasksParams } from '@/lib/tasks'
import type { TaskPriority, TaskStatus } from '@/types'

export function TasksListPage() {
  const { user } = useAuth()
  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<TaskStatus | ''>('')
  const [priority, setPriority] = useState<TaskPriority | ''>('')
  const [mineOnly, setMineOnly] = useState(false)
  const [overdueOnly, setOverdueOnly] = useState(false)
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    const handle = setTimeout(() => setQ(searchInput.trim()), 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const params: ListTasksParams = {
    q: q || undefined,
    status: status || undefined,
    priority: priority || undefined,
    assigned_to_id: mineOnly ? user?.id : undefined,
    overdue: overdueOnly || undefined,
    limit: 50,
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-fg">Tasks</h1>
        {canCreateTasks(user?.role.name) && (
          <button onClick={() => setShowCreate(true)} className="btn-primary text-sm">
            New task
          </button>
        )}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search task title…"
          className="input flex-1 sm:min-w-[16rem]"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as TaskStatus | '')}
          className="input sm:w-44"
        >
          <option value="">Default (active)</option>
          {TASK_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {TASK_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value as TaskPriority | '')}
          className="input sm:w-40"
        >
          <option value="">All priorities</option>
          {TASK_PRIORITY_ORDER.map((p) => (
            <option key={p} value={p}>
              {TASK_PRIORITY_LABELS[p]}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
          My tasks
        </label>
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={overdueOnly}
            onChange={(e) => setOverdueOnly(e.target.checked)}
          />
          Overdue
        </label>
      </div>

      <TasksTable params={params} showContext emptyMessage="No tasks match your filters." />

      {showCreate && (
        <TaskFormModal onClose={() => setShowCreate(false)} onSaved={() => setShowCreate(false)} />
      )}
    </div>
  )
}
