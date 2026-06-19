// Job Detail: a compact, display-only list of the customer's OTHER jobs (excluding
// the one being viewed), so sibling jobs are reachable without returning to the
// Customer page. Reuses the shared JobsTable + the existing per-customer jobs query
// (no new API/schema). Renders nothing when the customer has no other jobs.

import { Link } from 'react-router-dom'
import { JobsTable } from '@/components/JobsTable'
import { useJobs } from '@/hooks/useJobs'

interface CustomerOtherJobsPanelProps {
  customerId: number
  /** The job currently being viewed — excluded from the list. */
  currentJobId: number
}

export function CustomerOtherJobsPanel({ customerId, currentJobId }: CustomerOtherJobsPanelProps) {
  const { data, isLoading, isError } = useJobs({ customer_id: customerId, limit: 50 })
  // The same customer's jobs, minus the one being viewed.
  const others = (data?.items ?? []).filter((job) => job.id !== currentJobId)

  // Display/navigation-only: appear ONLY when there is at least one other job to show,
  // so a single-job customer adds no clutter and there is no loading/error flash.
  if (isLoading || isError || others.length === 0) return null

  return (
    <div className="mt-6">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="font-medium text-fg">Other jobs for this customer ({others.length})</h3>
        <Link
          to={`/customers/${customerId}`}
          className="whitespace-nowrap text-sm text-brand-400 underline hover:text-brand-500"
        >
          View all on customer →
        </Link>
      </div>
      <JobsTable jobs={others} showCustomer={false} showSite />
    </div>
  )
}
