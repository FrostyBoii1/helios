// Placeholder role-aware dashboard. Real widgets (outstanding approvals,
// upcoming installs, jobs needing scheduling, overdue tasks, etc.) will be wired
// to backend endpoints as those features land. For now it confirms the
// authenticated session and backend connectivity.

import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { TasksTable } from '@/components/TasksTable'
import { useTasks } from '@/hooks/useTasks'
import { apiFetch } from '@/lib/api'

interface HealthResponse {
  status: string
  version: string
  environment: string
}

export function DashboardPage() {
  const { user } = useAuth()

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => apiFetch<HealthResponse>('/health', { auth: false }),
  })

  // Real task data: my active tasks + a count of those overdue.
  const myParams = { assigned_to_id: user?.id, limit: 10 }
  const { data: myTasks } = useTasks(myParams)
  const overdueCount = (myTasks?.items ?? []).filter((t) => t.is_overdue).length

  return (
    <div>
      <h1 className="text-2xl font-semibold text-fg">Welcome, {user?.full_name}</h1>
      <p className="mt-1 text-muted">
        Work relevant to the{' '}
        <span className="font-medium text-fg">{user?.role.name}</span> role.
      </p>

      <section className="mt-6">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-fg">
            My open tasks {myTasks ? `(${myTasks.total})` : ''}
            {overdueCount > 0 && (
              <span className="ml-2 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-300 ring-1 ring-inset ring-red-400/20">
                {overdueCount} overdue
              </span>
            )}
          </h2>
          <Link to="/tasks" className="text-sm text-brand-400 underline hover:text-brand-500">
            All tasks
          </Link>
        </div>
        <TasksTable params={myParams} showContext emptyMessage="You have no open tasks." />
      </section>

      <h2 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted">
        Coming soon
      </h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <PlaceholderCard title="Outstanding approvals" hint="Approvals workflow" />
        <PlaceholderCard title="Upcoming installs" hint="Scheduling workflow" />
        <PlaceholderCard title="Jobs to schedule" hint="Scheduling workflow" />
        <PlaceholderCard title="Overdue tasks" hint="Tasks workflow" />
        <PlaceholderCard title="Support follow-ups" hint="Support workflow" />
        <PlaceholderCard title="Welcome calls" hint="Sales/Admin workflow" />
      </div>

      <p className="mt-8 text-xs text-faint">
        API: {health ? `${health.status} · v${health.version} · ${health.environment}` : 'connecting…'}
      </p>
    </div>
  )
}

function PlaceholderCard({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong bg-surface p-4">
      <h2 className="font-medium text-fg">{title}</h2>
      <p className="mt-1 text-sm text-faint">{hint}</p>
    </div>
  )
}
