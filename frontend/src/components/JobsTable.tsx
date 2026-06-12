// Presentational jobs table shared by the global Jobs page and the Customer
// detail Jobs panel.

import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { JobStatusBadge } from '@/components/JobStatusBadge'
import type { Job } from '@/types'

interface JobsTableProps {
  jobs: Job[]
  /** Whether to show the Customer column (hidden inside a customer's own panel). */
  showCustomer?: boolean
  emptyMessage?: string
  loading?: boolean
  error?: boolean
}

export function JobsTable({
  jobs,
  showCustomer = true,
  emptyMessage = 'No jobs yet.',
  loading = false,
  error = false,
}: JobsTableProps) {
  const navigate = useNavigate()
  const colSpan = showCustomer ? 5 : 4

  return (
    <div className="card overflow-x-auto">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="border-b border-line bg-elevated text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Case #</th>
            <th className="px-4 py-2 font-medium">Title</th>
            {showCustomer && <th className="px-4 py-2 font-medium">Customer</th>}
            <th className="px-4 py-2 font-medium">Status</th>
            <th className="px-4 py-2 font-medium">Install date</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <Message colSpan={colSpan}>Loading jobs…</Message>
          ) : error ? (
            <Message colSpan={colSpan} className="text-red-400">
              Failed to load jobs.
            </Message>
          ) : jobs.length === 0 ? (
            <Message colSpan={colSpan}>{emptyMessage}</Message>
          ) : (
            jobs.map((job) => (
              <tr
                key={job.id}
                onClick={() => navigate(`/jobs/${job.id}`)}
                className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-elevated"
              >
                <td className="px-4 py-2 font-mono text-xs text-brand-400">{job.case_number}</td>
                <td className="px-4 py-2 text-fg">{job.title ?? '—'}</td>
                {showCustomer && (
                  <td className="px-4 py-2 text-muted">{job.customer.full_name}</td>
                )}
                <td className="px-4 py-2">
                  <JobStatusBadge status={job.status} />
                </td>
                <td className="px-4 py-2 text-muted">{job.install_date ?? '—'}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function Message({
  colSpan,
  children,
  className,
}: {
  colSpan: number
  children: ReactNode
  className?: string
}) {
  return (
    <tr>
      <td colSpan={colSpan} className={`px-4 py-8 text-center text-muted ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}
