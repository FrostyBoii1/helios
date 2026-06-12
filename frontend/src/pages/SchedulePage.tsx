import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { JobStatusBadge } from '@/components/JobStatusBadge'
import { ScheduleJobModal } from '@/components/ScheduleJobModal'
import { useJobs } from '@/hooks/useJobs'
import type { Job } from '@/types'

const WEEKS = 9 // current week + next 8
const WINDOW_DAYS = WEEKS * 7

// ---- Monday-based week helpers (local time) ----
function mondayOf(d: Date): Date {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const dow = (x.getDay() + 6) % 7 // Mon=0 … Sun=6
  x.setDate(x.getDate() - dow)
  return x
}
function addDays(d: Date, n: number): Date {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}
function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
function parseISO(iso: string): Date {
  const p = iso.split('-').map(Number)
  return new Date(p[0] ?? 1970, (p[1] ?? 1) - 1, p[2] ?? 1)
}
function weekLabel(monday: Date): string {
  return `Week of ${monday.getDate()} ${monday.toLocaleDateString(undefined, { month: 'long' })}`
}

export function SchedulePage() {
  // windowStart = Monday of the first visible week.
  const [windowStart, setWindowStart] = useState<Date>(() => mondayOf(new Date()))
  const [selected, setSelected] = useState<Job | null>(null)
  const todayWeekKey = isoDate(mondayOf(new Date()))
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([todayWeekKey]))

  const weeks = useMemo(
    () => Array.from({ length: WEEKS }, (_, i) => mondayOf(addDays(windowStart, i * 7))),
    [windowStart],
  )
  const from = isoDate(windowStart)
  const to = isoDate(addDays(windowStart, WINDOW_DAYS - 1))

  const { data: scheduled, isLoading, isError } = useJobs({
    install_date_from: from,
    install_date_to: to,
    limit: 100,
  })
  const { data: unscheduled } = useJobs({ unscheduled: true, limit: 50 })

  // Bucket scheduled jobs by their week (Monday ISO key).
  const byWeek = useMemo(() => {
    const map = new Map<string, Job[]>()
    for (const job of scheduled?.items ?? []) {
      if (!job.install_date) continue
      const key = isoDate(mondayOf(parseISO(job.install_date)))
      const bucket = map.get(key) ?? []
      bucket.push(job)
      map.set(key, bucket)
    }
    return map
  }, [scheduled])

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-fg">Schedule</h1>
        <div className="flex gap-2 text-sm">
          <button
            onClick={() => setWindowStart((d) => addDays(d, -WINDOW_DAYS))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated"
          >
            ← Earlier
          </button>
          <button
            onClick={() => setWindowStart(mondayOf(new Date()))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated"
          >
            This week
          </button>
          <button
            onClick={() => setWindowStart((d) => addDays(d, WINDOW_DAYS))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated"
          >
            Later →
          </button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        {/* Weekly board */}
        <div className="space-y-3">
          {isLoading ? (
            <div className="card p-6 text-sm text-muted">Loading schedule…</div>
          ) : isError ? (
            <div className="card p-6 text-sm text-red-400">Failed to load the schedule.</div>
          ) : (
            weeks.map((monday) => {
              const key = isoDate(monday)
              const jobs = byWeek.get(key) ?? []
              const isOpen = expanded.has(key)
              const isCurrent = key === todayWeekKey
              return (
                <div key={key} className="card overflow-hidden">
                  <button
                    onClick={() => toggle(key)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-elevated"
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-faint">{isOpen ? '▾' : '▸'}</span>
                      <span className="font-medium text-fg">{weekLabel(monday)}</span>
                      {isCurrent && (
                        <span className="rounded-full bg-brand-500/15 px-2 py-0.5 text-xs font-medium text-brand-400 ring-1 ring-inset ring-brand-500/20">
                          This week
                        </span>
                      )}
                    </span>
                    <span className="text-sm text-muted">
                      {jobs.length} {jobs.length === 1 ? 'job' : 'jobs'}
                    </span>
                  </button>

                  {isOpen && (
                    <div className="border-t border-line">
                      {jobs.length === 0 ? (
                        <p className="px-4 py-4 text-sm text-faint">Nothing scheduled this week.</p>
                      ) : (
                        jobs
                          .slice()
                          .sort((a, b) => (a.install_date ?? '').localeCompare(b.install_date ?? ''))
                          .map((job) => (
                            <JobRow key={job.id} job={job} onOpen={() => setSelected(job)} showDate />
                          ))
                      )}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>

        {/* Needs scheduling */}
        <aside>
          <h2 className="mb-2 font-medium text-fg">
            Needs scheduling {unscheduled ? `(${unscheduled.total})` : ''}
          </h2>
          <div className="card overflow-hidden">
            {(unscheduled?.items.length ?? 0) === 0 ? (
              <p className="px-4 py-4 text-sm text-faint">Nothing waiting to be scheduled.</p>
            ) : (
              unscheduled?.items.map((job) => (
                <JobRow key={job.id} job={job} onOpen={() => setSelected(job)} />
              ))
            )}
          </div>
          <Link
            to="/jobs"
            className="mt-3 inline-block text-sm text-brand-400 underline hover:text-brand-500"
          >
            All jobs
          </Link>
        </aside>
      </div>

      {selected && <ScheduleJobModal job={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function JobRow({ job, onOpen, showDate }: { job: Job; onOpen: () => void; showDate?: boolean }) {
  return (
    <button
      onClick={onOpen}
      className="block w-full border-b border-line/60 px-4 py-3 text-left last:border-0 hover:bg-elevated"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-brand-400">{job.case_number}</span>
        <JobStatusBadge status={job.status} />
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-sm text-fg">{job.customer.full_name}</span>
        {showDate && job.install_date && (
          <span className="text-xs text-muted">{job.install_date}</span>
        )}
      </div>
      {job.title && <div className="text-xs text-muted">{job.title}</div>}
    </button>
  )
}
