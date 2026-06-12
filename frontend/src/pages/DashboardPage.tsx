// Placeholder role-aware dashboard. Real widgets (outstanding approvals,
// upcoming installs, jobs needing scheduling, overdue tasks, etc.) will be wired
// to backend endpoints as those features land. For now it confirms the
// authenticated session and backend connectivity.

import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/auth/AuthContext'
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

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-800">
        Welcome, {user?.full_name}
      </h1>
      <p className="mt-1 text-slate-500">
        Your dashboard will show work relevant to the{' '}
        <span className="font-medium">{user?.role.name}</span> role. Feature
        widgets are coming as the core workflow is built out.
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <PlaceholderCard title="Outstanding approvals" hint="Approvals workflow" />
        <PlaceholderCard title="Upcoming installs" hint="Scheduling workflow" />
        <PlaceholderCard title="Jobs to schedule" hint="Scheduling workflow" />
        <PlaceholderCard title="Overdue tasks" hint="Tasks workflow" />
        <PlaceholderCard title="Support follow-ups" hint="Support workflow" />
        <PlaceholderCard title="Welcome calls" hint="Sales/Admin workflow" />
      </div>

      <p className="mt-8 text-xs text-slate-400">
        API: {health ? `${health.status} · v${health.version} · ${health.environment}` : 'connecting…'}
      </p>
    </div>
  )
}

function PlaceholderCard({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-4">
      <h2 className="font-medium text-slate-700">{title}</h2>
      <p className="mt-1 text-sm text-slate-400">{hint}</p>
    </div>
  )
}
