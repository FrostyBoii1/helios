// Create/edit a task. Used for creation (optionally pre-linked to a customer or
// job) and for editing/reassigning an existing task.

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { useCreateTask, useSelectableUsers, useUpdateTask } from '@/hooks/useTasks'
import { TASK_PRIORITY_LABELS, TASK_PRIORITY_ORDER } from '@/components/TaskBadges'
import type { Task, TaskInput, TaskPriority } from '@/types'

interface TaskFormModalProps {
  /** Existing task to edit; omitted for create. */
  task?: Task
  /** Pre-link context when creating from a customer/job panel. */
  customerId?: number
  jobId?: number
  onClose: () => void
  onSaved: (taskId: number) => void
}

export function TaskFormModal({ task, customerId, jobId, onClose, onSaved }: TaskFormModalProps) {
  const isEdit = task != null
  const [title, setTitle] = useState(task?.title ?? '')
  const [description, setDescription] = useState(task?.description ?? '')
  const [priority, setPriority] = useState<TaskPriority>(task?.priority ?? 'normal')
  const [dueDate, setDueDate] = useState(task?.due_date ? task.due_date.slice(0, 10) : '')
  const [assignee, setAssignee] = useState<string>(
    task?.assigned_to_id != null ? String(task.assigned_to_id) : '',
  )
  const [error, setError] = useState<string | null>(null)

  const { data: users } = useSelectableUsers()
  const createMutation = useCreateTask()
  const updateMutation = useUpdateTask(task?.id ?? 0)
  const pending = createMutation.isPending || updateMutation.isPending

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    const input: TaskInput = {
      title: title.trim(),
      description: description.trim() || null,
      priority,
      // Due "by end of that day" in UTC for intuitive overdue behaviour.
      due_date: dueDate ? `${dueDate}T23:59:59Z` : null,
      assigned_to_id: assignee ? Number(assignee) : null,
    }
    if (!isEdit) {
      if (customerId != null) input.customer_id = customerId
      if (jobId != null) input.job_id = jobId
    }
    try {
      const saved = isEdit
        ? await updateMutation.mutateAsync(input)
        : await createMutation.mutateAsync(input)
      onSaved(saved.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to save this task.')
      } else if (err instanceof ApiError && typeof err.detail === 'string') {
        setError(err.detail)
      } else {
        setError('Could not save the task. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <form onSubmit={handleSubmit} className="card w-full max-w-lg p-6 shadow-2xl shadow-black/40">
        <h2 className="mb-4 text-lg font-semibold text-fg">{isEdit ? 'Edit task' : 'New task'}</h2>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <Field label="Title *">
          <input required value={title} onChange={(e) => setTitle(e.target.value)} className="input" />
        </Field>
        <Field label="Description">
          <textarea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="input"
          />
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Priority">
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as TaskPriority)}
              className="input"
            >
              {TASK_PRIORITY_ORDER.map((p) => (
                <option key={p} value={p}>
                  {TASK_PRIORITY_LABELS[p]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Due date">
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="input"
            />
          </Field>
        </div>
        <Field label="Assignee">
          <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="input">
            <option value="">Unassigned</option>
            {(users ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.role})
              </option>
            ))}
          </select>
        </Field>

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={pending} className="btn-primary">
            {pending ? 'Saving…' : isEdit ? 'Save changes' : 'Create task'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="mb-3 block text-sm">
      <span className="mb-1 block font-medium text-fg">{label}</span>
      {children}
    </label>
  )
}
