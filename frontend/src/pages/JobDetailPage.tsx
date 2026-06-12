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
import { Timeline } from '@/components/Timeline'
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

  if (isLoading) return <p className="text-muted">Loading…</p>
  if (isError || !job) {
    return (
      <div>
        <p className="text-red-400">Job not found.</p>
        <Link to="/jobs" className="mt-2 inline-block text-muted underline hover:text-fg">
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
      <Link to="/jobs" className="text-sm text-muted underline hover:text-fg">
        ← Jobs
      </Link>

      <div className="mt-2 mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="font-mono text-xl font-semibold text-fg">{job.case_number}</h1>
          <JobStatusBadge status={job.status} />
        </div>
        {mayDelete && (
          <button
            onClick={onDelete}
            disabled={deleteMutation.isPending}
            className="btn-danger px-3 py-1.5 text-sm"
          >
            Delete
          </button>
        )}
      </div>

      <p className="mb-4 text-sm text-muted">
        Customer:{' '}
        <Link
          to={`/customers/${job.customer.id}`}
          className="text-brand-400 underline hover:text-brand-500"
        >
          {job.customer.full_name}
        </Link>
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Status + install date controls */}
      <div className="mb-4 grid gap-4 sm:grid-cols-2">
        <div className="card p-4">
          <h2 className="eyebrow mb-2">Status</h2>
          {mayChangeStatus ? (
            <select
              value={job.status}
              disabled={statusMutation.isPending}
              onChange={(e) => onStatusChange(e.target.value as JobStatus)}
              className="input text-sm"
            >
              {JOB_STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {JOB_STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-fg">{JOB_STATUS_LABELS[job.status]}</p>
          )}
        </div>

        <div className="card p-4">
          <h2 className="eyebrow mb-2">Install date</h2>
          {editingInstall ? (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={installDate}
                onChange={(e) => setInstallDate(e.target.value)}
                className="input w-auto px-2 py-1 text-sm"
              />
              <button
                onClick={saveInstallDate}
                disabled={updateMutation.isPending}
                className="btn-primary px-3 py-1 text-sm"
              >
                Save
              </button>
              <button
                onClick={() => {
                  setEditingInstall(false)
                  setInstallDate(job.install_date ?? '')
                }}
                className="text-sm text-muted underline hover:text-fg"
              >
                Cancel
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-fg">{job.install_date ?? 'Not scheduled'}</span>
              {mayEditInstall && (
                <button
                  onClick={() => setEditingInstall(true)}
                  className="text-sm text-brand-400 underline hover:text-brand-500"
                >
                  {job.install_date ? 'Reschedule' : 'Set date'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Descriptive details */}
      <div className="card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="eyebrow">Details</h2>
          {mayEditDetails && !editingDetails && (
            <button
              onClick={() => setEditingDetails(true)}
              className="btn-secondary px-3 py-1 text-sm"
            >
              Edit
            </button>
          )}
        </div>

        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {DESCRIPTIVE_FIELDS.map(({ key, label, textarea }) => (
            <div key={key} className={textarea ? 'sm:col-span-2' : ''}>
              <dt className="eyebrow text-faint">{label}</dt>
              {editingDetails ? (
                textarea ? (
                  <textarea
                    rows={2}
                    value={form[key] ?? ''}
                    onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                    className="input mt-1 px-2 py-1 text-sm"
                  />
                ) : (
                  <input
                    type={key === 'sale_date' ? 'date' : 'text'}
                    value={form[key] ?? ''}
                    onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
                    className="input mt-1 px-2 py-1 text-sm"
                  />
                )
              ) : (
                <dd className="mt-0.5 whitespace-pre-wrap text-fg">
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
              className="btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              onClick={saveDetails}
              disabled={updateMutation.isPending}
              className="btn-primary text-sm"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        )}
      </div>

      {/* Tasks/Documents remain later phases; the activity timeline is live. */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <PlaceholderPanel title="Tasks" hint="Job tasks appear here (Tasks phase)." />
        <PlaceholderPanel title="Documents" hint="Job files appear here (NAS phase)." />
      </div>
      <div className="mt-6">
        <Timeline jobId={job.id} />
      </div>
    </div>
  )
}

function PlaceholderPanel({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong bg-surface p-4">
      <h3 className="font-medium text-fg">{title}</h3>
      <p className="mt-1 text-sm text-faint">{hint}</p>
    </div>
  )
}
