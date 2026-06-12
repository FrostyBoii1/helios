// Tasks panel embedded in Customer and Job detail pages: lists active tasks for
// that entity and offers a create-task modal (any authenticated user).

import { useState } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { canCreateTasks } from '@/auth/permissions'
import { TaskFormModal } from '@/components/TaskFormModal'
import { TasksTable } from '@/components/TasksTable'
import { useTasks } from '@/hooks/useTasks'

interface TasksPanelProps {
  customerId?: number
  jobId?: number
}

export function TasksPanel({ customerId, jobId }: TasksPanelProps) {
  const { user } = useAuth()
  const [showCreate, setShowCreate] = useState(false)
  const params = { customer_id: customerId, job_id: jobId, limit: 50 }
  const { data } = useTasks(params)
  const canCreate = canCreateTasks(user?.role.name)

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-medium text-fg">Tasks {data ? `(${data.total})` : ''}</h3>
        {canCreate && (
          <button onClick={() => setShowCreate(true)} className="btn-primary px-3 py-1.5 text-sm">
            New task
          </button>
        )}
      </div>

      <TasksTable params={params} showContext={false} emptyMessage="No active tasks." />

      {showCreate && (
        <TaskFormModal
          customerId={customerId}
          jobId={jobId}
          onClose={() => setShowCreate(false)}
          onSaved={() => setShowCreate(false)}
        />
      )}
    </div>
  )
}
