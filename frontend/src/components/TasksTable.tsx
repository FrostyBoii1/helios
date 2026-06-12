// Self-contained tasks table: owns its query, renders rows with permission-gated
// inline actions (complete / reopen / edit / delete), and an edit modal.

import { useState } from 'react'
import type { ReactNode } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { canCompleteTask, canDeleteTasks, canEditTask } from '@/auth/permissions'
import { TaskFormModal } from '@/components/TaskFormModal'
import { TaskPriorityBadge, TaskStatusBadge } from '@/components/TaskBadges'
import { useCompleteTask, useDeleteTask, useReopenTask, useTasks } from '@/hooks/useTasks'
import type { ListTasksParams } from '@/lib/tasks'
import type { Task } from '@/types'

interface TasksTableProps {
  params: ListTasksParams
  /** Show Customer/Job columns (hidden inside a customer's/job's own panel). */
  showContext?: boolean
  emptyMessage?: string
}

export function TasksTable({ params, showContext = true, emptyMessage = 'No tasks.' }: TasksTableProps) {
  const { user } = useAuth()
  const { data, isLoading, isError } = useTasks(params)
  const completeMutation = useCompleteTask()
  const reopenMutation = useReopenTask()
  const deleteMutation = useDeleteTask()
  const [editing, setEditing] = useState<Task | null>(null)

  const role = user?.role.name
  const items = data?.items ?? []
  const cols = showContext ? 7 : 5

  function onComplete(task: Task) {
    const notes = window.prompt('Completion notes (optional):', '')
    if (notes === null) return // cancelled
    completeMutation.mutate({ id: task.id, notes: notes || undefined })
  }

  function onDelete(task: Task) {
    if (window.confirm(`Delete task “${task.title}”? This can be recovered later.`)) {
      deleteMutation.mutate(task.id)
    }
  }

  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="border-b border-line bg-elevated text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Task</th>
            {showContext && <th className="px-4 py-2 font-medium">Customer</th>}
            {showContext && <th className="px-4 py-2 font-medium">Job</th>}
            <th className="px-4 py-2 font-medium">Priority</th>
            <th className="px-4 py-2 font-medium">Due</th>
            <th className="px-4 py-2 font-medium">Assignee</th>
            <th className="px-4 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <Message cols={cols}>Loading tasks…</Message>
          ) : isError ? (
            <Message cols={cols} className="text-red-400">
              Failed to load tasks.
            </Message>
          ) : items.length === 0 ? (
            <Message cols={cols}>{emptyMessage}</Message>
          ) : (
            items.map((task) => {
              const active = task.status === 'open' || task.status === 'in_progress'
              return (
                <tr key={task.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2">
                    <div className="font-medium text-fg">{task.title}</div>
                    <div className="mt-0.5">
                      <TaskStatusBadge status={task.status} />
                    </div>
                  </td>
                  {showContext && (
                    <td className="px-4 py-2 text-muted">{task.customer?.full_name ?? '—'}</td>
                  )}
                  {showContext && (
                    <td className="px-4 py-2 font-mono text-xs text-brand-400">
                      {task.job?.case_number ?? '—'}
                    </td>
                  )}
                  <td className="px-4 py-2">
                    <TaskPriorityBadge priority={task.priority} />
                  </td>
                  <td className="px-4 py-2">
                    {task.due_date ? (
                      <span className={task.is_overdue ? 'font-medium text-red-300' : 'text-muted'}>
                        {task.due_date.slice(0, 10)}
                        {task.is_overdue ? ' · overdue' : ''}
                      </span>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-muted">{task.assigned_to?.full_name ?? 'Unassigned'}</td>
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-2 text-xs">
                      {active && canCompleteTask(role, user?.id, task) && (
                        <ActionButton onClick={() => onComplete(task)}>Complete</ActionButton>
                      )}
                      {task.status === 'completed' && canEditTask(role, user?.id, task) && (
                        <ActionButton onClick={() => reopenMutation.mutate(task.id)}>
                          Reopen
                        </ActionButton>
                      )}
                      {canEditTask(role, user?.id, task) && (
                        <ActionButton onClick={() => setEditing(task)}>Edit</ActionButton>
                      )}
                      {canDeleteTasks(role) && (
                        <ActionButton danger onClick={() => onDelete(task)}>
                          Delete
                        </ActionButton>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>

      {editing && (
        <TaskFormModal task={editing} onClose={() => setEditing(null)} onSaved={() => setEditing(null)} />
      )}
    </div>
  )
}

function ActionButton({
  children,
  onClick,
  danger,
}: {
  children: ReactNode
  onClick: () => void
  danger?: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md border px-2 py-1 transition-colors ${
        danger
          ? 'border-red-500/40 text-red-300 hover:bg-red-500/10'
          : 'border-line-strong text-fg hover:bg-elevated'
      }`}
    >
      {children}
    </button>
  )
}

function Message({ cols, children, className }: { cols: number; children: ReactNode; className?: string }) {
  return (
    <tr>
      <td colSpan={cols} className={`px-4 py-8 text-center text-muted ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}
