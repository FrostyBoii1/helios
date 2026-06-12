import { useEffect, useMemo, useState } from 'react'
import { JOB_STATUS_LABELS, JOB_STATUS_ORDER } from '@/components/JobStatusBadge'
import { JobsTable } from '@/components/JobsTable'
import { useJobs } from '@/hooks/useJobs'
import type { JobStatus } from '@/types'

const PAGE_SIZE = 25

export function JobsListPage() {
  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<JobStatus | ''>('')
  const [offset, setOffset] = useState(0)

  // Debounce search; reset to first page on a new query.
  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const { data, isLoading, isError, isFetching } = useJobs({
    q: q || undefined,
    status: status || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const total = data?.total ?? 0
  const pageInfo = useMemo(() => {
    if (total === 0) return '0 jobs'
    return `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`
  }, [offset, total])

  return (
    <div>
      <h1 className="mb-4 text-2xl font-semibold text-fg">Jobs</h1>

      <div className="mb-4 flex flex-col gap-3 sm:flex-row">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search case number or title…"
          className="input flex-1"
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as JobStatus | '')
            setOffset(0)
          }}
          className="input sm:w-56"
        >
          <option value="">All statuses</option>
          {JOB_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {JOB_STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      <JobsTable
        jobs={data?.items ?? []}
        showCustomer
        loading={isLoading}
        error={isError}
        emptyMessage={q || status ? 'No jobs match your filters.' : 'No jobs yet.'}
      />

      <div className="mt-3 flex items-center justify-between text-sm text-muted">
        <span>
          {pageInfo}
          {isFetching && !isLoading ? ' · updating…' : ''}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
