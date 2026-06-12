import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import {
  canChangeJobStatus,
  canDeleteJobs,
  canEditJobDetails,
  canEditJobInstallDate,
} from '@/auth/permissions'
import { JobStatusBadge, JOB_STATUS_LABELS, JOB_STATUS_ORDER } from '@/components/JobStatusBadge'
import { useChangeJobStatus, useDeleteJob, useJob, useUpdateJob } from '@/hooks/useJobs'
import type { JobInput, JobStatus } from '@/types'

const DESCRIPTIVE_FIELDS: { key: keyof JobInput; label: string; textarea?: boolean }[] = [
  { key: 'title', label: 'Title' },
  { key: 'sale_date', label: 'Sale date' },
  { key: 'system_details', label: 'System details', textarea: true },
  { key: 'install_details', label: 'Install details', textarea: true },
  { key: 'approval_details', label: 'Approval details', textarea: true },
  { key: 'notes', label: 'Notes', textarea: true },
]

export function JobDetailPage() {
  const { id } = useParams()
  const jobId = Number(id)
  const navigate = useNavigate()
  const { user } = useAuth()

  const { data: job, isLoading, isError } = useJob(jobId)
  const updateMutation = useUpdateJob(jobId)
  const statusMutation = useChangeJobStatus(jobId)
  const deleteMutation = useDeleteJob()

  const [editingDetails, setEditingDetails] = useState(false)
  const [form, setForm] = useState<Record<string, string>>({})
  const [installDate, setInstallDate] = useState('')
  const [editingInstall, setEditingInstall] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (job) {
      setForm(
        Object.fromEntries(
          DESCRIPTIVE_FIELDS.map(({ key }) => [key, (job[key] as string | null) ?? '']),
        ),
      )
      setInstallDate(job.install_date ?? '')
    }
  }, [job])

  const role = user?.role.name
  const mayEditDetails = canEditJobDetails(role)
  const mayEditInstall = canEditJobInstallDate(role)
  const mayChangeStatus = canChangeJobStatus(role)
  const mayDelete = canDeleteJobs(role)

  if (isLoading) return <p className="text-slate-500">Loading…</p>
  if (isError || !job) {
    return (
      <div>
        <p className="text-red-600">Job not found.</p>
        <Link to="/jobs" className="mt-2 inline-block text-slate-700 underline">
          Back to jobs
        </Link>
      </div>
    )
  }

  async function saveDetails() {
    setError(null)
    const payload: JobInput = {}
    for (const { key } of DESCRIPTIVE_FIELDS) {
      const current = (job![key] as string | null) ?? ''
      const next = form[key] ?? ''
      if (next !== current) {
        ;(payload as Record<string, string | null>)[key] = next || null
      }
    }
    if (Object.keys(payload).length === 0) {
      setEditingDetails(false)
      return
    }
    try {
      await updateMutation.mutateAsync(payload)
      setEditingDetails(false)
    } catch {
      setError('Could not save job details.')
    }
  }

  async function saveInstallDate() {
    setError(null)
    const next = installDate || null
    if ((job!.install_date ?? null) === next) {
      setEditingInstall(false)
      return
    }
    try {
      await updateMutation.mutateAsync({ install_date: next })
      setEditingInstall(false)
    } catch {
      setError('Could not update the install date.')
    }
  }

  async function onStatusChange(next: JobStatus) {
    setError(null)
    try {
      await statusMutation.mutateAsync(next)
    } catch {
      setError('Could not change the status.')
    }
  }

  async function onDelete() {
    if (!window.confirm(`Delete job ${job!.case_number}? This can be recovered later.`)) return
    try {
      await deleteMutation.mutateAsync(jobId)
      navigate('/jobs')
    } catch {
      setError('Could not delete the job.')
    }
  }

  return (
    <div>
      <Link to="/jobs" className="text-sm text-slate-500 underline">
        ← Jobs
      </Link>

      <div className="mt-2 mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="font-mono text-xl font-semibold text-slate-800">{job.case_number}</h1>
          <JobStatusBadge status={job.status} />
        </div>
        {mayDelete && (
          <button
            onClick={onDelete}
            disabled={deleteMutation.isPending}
            className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </div>

      <p className="mb-4 text-sm text-slate-500">
        Customer:{' '}
        <Link to={`/customers/${job.customer.id}`} className="text-slate-700 underline">
          {job.customer.full_name}
        </Link>
      </p>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      {/* Status + install date controls */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Status
          </h2>
          {mayChangeStatus ? (
            <select
              value={job.status}
              disabled={statusMutation.isPending}
              onChange={(e) => onStatusChange(e.target.value as JobStatus)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
            >
              {JOB_STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {JOB_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-slate-700">{JOB_STATUS_LABELS[job.status]}</p>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Install date
          </h2>
          {editingInstall ? (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={installDate}
                onChange={(e) => setInstallDate(e.target.value)}
                className="rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
              />
              <button
                onClick={saveInstallDate}
                disabled={updateMutation.isPending}
                className="rounded-md bg-slate-800 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-60"
              >
                Save
              </button>
              <button
                onClick={() => {
                  setEditingInstall(false)
                  setInstallDate(job.install_date ?? '')
                }}
                className="text-sm text-slate-500 underline"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-slate-700">{job.install_date ?? 'Not scheduled'}</span>
              {mayEditInstall && (
                <button
                  onClick={() => setEditingInstall(true)}
                  className="text-sm text-slate-500 underline"
                >
                  {job.install_date ? 'Reschedule' : 'Set date'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Descriptive details */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Details</h2>
          {mayEditDetails && !editingDetails && (
            <button
              onClick={() => setEditingDetails(true)}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:bg-slate-50"
            >
              Edit
            </button>
          )}
        </div>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {DESCRIPTIVE_FIELDS.map(({ key, label, textarea }) => (
            <div key={key} className={textarea ? 'sm:col-span-2' : ''}>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
              {editingDetails ? (
                textarea ? (
                  <textarea
                    rows={2}
                    value={form[key] ?? ''}
                    onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                  />
                ) : (
                  <input
                    type={key === 'sale_date' ? 'date' : 'text'}
                    value={form[key] ?? ''}
                    onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                  />
                )
              ) : (
                <dd className="mt-0.5 whitespace-pre-wrap text-slate-800">
                  {(job[key] as string | null) || '—'}
                </dd>
              )}
            </div>
          ))}
        </dl>

        {editingDetails && (
          <div className="mt-5 flex justify-end gap-3">
            <button
              onClick={() => {
                setEditingDetails(false)
                setError(null)
              }}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={saveDetails}
              disabled={updateMutation.isPending}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        )}
      </div>

      {/* Placeholders — wired in later phases (out of scope for the Jobs phase). */}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <PlaceholderPanel title="Tasks" hint="Job tasks appear here (Tasks phase)." />
        <PlaceholderPanel title="Documents" hint="Job files appear here (NAS phase)." />
        <PlaceholderPanel title="Timeline" hint="Activity history appears here (Timeline phase)." />
      </div>
    </div>
  )
}

function PlaceholderPanel({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-4">
      <h3 className="font-medium text-slate-700">{title}</h3>
      <p className="mt-1 text-sm text-slate-400">{hint}</p>
    </div>
  )
}
