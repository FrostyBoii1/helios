import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import {
  canChangeJobStatus,
  canDeleteJobs,
  canEditJobDetails,
  canEditJobInstallDate,
} from '@/auth/permissions'
import { CustomerOtherJobsPanel } from '@/components/CustomerOtherJobsPanel'
import { ImportedSourceNotes } from '@/components/ImportedSourceNotes'
import { InternalNotesPanel } from '@/components/InternalNotesPanel'
import { JobStatusBadge, JOB_STATUS_LABELS, JOB_STATUS_ORDER } from '@/components/JobStatusBadge'
import { ImportedJobDetails } from '@/components/ImportedJobDetails'
import { JobApprovalControl } from '@/components/JobApprovalControl'
import { JobLabelChips } from '@/components/JobLabelChips'
import { StructuredDetailsView, detailsPath } from '@/components/structured/StructuredDetailsView'
import { TasksPanel } from '@/components/TasksPanel'
import { Timeline } from '@/components/Timeline'
import { useCustomer } from '@/hooks/useCustomers'
import { useChangeJobStatus, useDeleteJob, useJob, useUpdateJob } from '@/hooks/useJobs'
import { useFieldRegistry } from '@/hooks/useImports'
import { ApiError } from '@/lib/api'
import { buildDetailsPatch } from '@/lib/detailsPatch'
import { parseImportedJobDetails } from '@/lib/importedJobDetails'
import type { JobInput, JobStatus } from '@/types'
import type { FieldSpec } from '@/types/imports'

const DESCRIPTIVE_FIELDS: { key: keyof JobInput; label: string; textarea?: boolean }[] = [
  { key: 'title', label: 'Title' },
  { key: 'sale_date', label: 'Sale date' },
  { key: 'system_details', label: 'System details', textarea: true },
  { key: 'install_details', label: 'Install details', textarea: true },
  { key: 'approval_details', label: 'Approval details', textarea: true },
  { key: 'notes', label: 'Notes', textarea: true },
]

// In structured edit mode the derived blobs (system_details/install_details) are
// re-rendered by the backend from Job.details, so they are NOT edited directly.
// `notes` is also excluded: it is the read-only IMPORTED source blob — manual
// notes now live in the dedicated internal-notes panel (Phase A). `approval_details`
// is excluded too: approval is structured state edited via the dedicated Approval
// control (label-is-law), never a free-text textarea.
const STRUCTURED_MODE_LEGACY_FIELDS = DESCRIPTIVE_FIELDS.filter(
  (f) =>
    f.key !== 'system_details' &&
    f.key !== 'install_details' &&
    f.key !== 'notes' &&
    f.key !== 'approval_details',
)

function describeError(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return typeof err.detail === 'string' ? err.detail : 'You do not have permission to do that.'
    }
    if (err.status === 422) {
      return typeof err.detail === 'string'
        ? err.detail
        : 'Some structured fields could not be saved (disallowed path or invalid value).'
    }
    if (typeof err.detail === 'string') return err.detail
  }
  return fallback
}

export function JobDetailPage() {
  const { id } = useParams()
  const jobId = Number(id)
  const navigate = useNavigate()
  const { user } = useAuth()

  const { data: job, isLoading, isError } = useJob(jobId)
  const { data: customer } = useCustomer(job?.customer_id ?? 0)
  const updateMutation = useUpdateJob(jobId)
  const statusMutation = useChangeJobStatus(jobId)
  const deleteMutation = useDeleteJob()
  // Phase 4a: drives the read-only structured view when job.details is present.
  const { data: registry } = useFieldRegistry()

  const [editingDetails, setEditingDetails] = useState(false)
  const [form, setForm] = useState<Record<string, string>>({})
  // Phase 4c: string UI state for structured fields, keyed by "<section>.<key>".
  const [detailsEdits, setDetailsEdits] = useState<Record<string, string>>({})
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
      setDetailsEdits({})
    }
  }, [job])

  // path ("<section>.<key>") → field spec, for input_type-aware coercion on save.
  const fieldByPath = useMemo(() => {
    const m = new Map<string, FieldSpec>()
    if (registry) for (const f of registry.fields) m.set(detailsPath(f.storage), f)
    return m
  }, [registry])

  // A details-bearing job (with the registry loaded) edits structured fields;
  // a details=NULL job keeps the legacy pipe-string textareas.
  const structuredEditable = !!(job?.details && registry)

  function handleDetailsChange(path: string, value: string) {
    setDetailsEdits((prev) => ({ ...prev, [path]: value }))
  }

  // One PATCH: changed legacy fields + (structured mode) the coerced details patch.
  function buildPayload(): JobInput {
    const payload: JobInput = {}
    const legacyFields = structuredEditable ? STRUCTURED_MODE_LEGACY_FIELDS : DESCRIPTIVE_FIELDS
    for (const { key } of legacyFields) {
      const current = (job?.[key] as string | null) ?? ''
      const next = form[key] ?? ''
      if (next !== current) (payload as Record<string, string | null>)[key] = next || null
    }
    if (structuredEditable) {
      const patch = buildDetailsPatch(detailsEdits, job?.details ?? null, fieldByPath)
      if (patch) payload.details = patch
    }
    return payload
  }
  const pendingPayload = useMemo(buildPayload, [
    form,
    detailsEdits,
    structuredEditable,
    fieldByPath,
    job,
  ])
  const hasDetailChanges = Object.keys(pendingPayload).length > 0

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
    if (!hasDetailChanges) {
      setEditingDetails(false)
      return
    }
    try {
      await updateMutation.mutateAsync(pendingPayload)
      setDetailsEdits({})
      setEditingDetails(false)
    } catch (err) {
      setError(describeError(err, 'Could not save job details.'))
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

  // Structured view for imported jobs (null for native jobs -> plain rendering).
  const importedView = parseImportedJobDetails(job)

  // Job/property address. G (Stage 1): PREFER this job's OWN site address
  // (Job.details.site) over the customer headline address — a multi-job customer can
  // have jobs at different sites. Falls back to the customer address when the job has
  // no site detail (e.g. native jobs or rows staged before per-job site capture).
  const site = job.details?.site
  const jobSiteAddress = site
    ? [site.line1, [site.suburb, site.state, site.postcode].filter(Boolean).join(' ')]
        .map((p) => (p ? String(p).trim() : ''))
        .filter(Boolean)
        .join(', ') || (site.raw ? String(site.raw).trim() : '')
    : ''
  const customerAddress = customer
    ? [
        customer.address_line1,
        [customer.suburb, customer.state, customer.postcode].filter(Boolean).join(' '),
      ]
        .filter((part) => part && String(part).trim())
        .join(', ')
    : ''
  const propertyAddress = jobSiteAddress || customerAddress

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

      {/* Two columns: status + details on the left, a tall manual internal-notes
          panel on the right (sticky). Tasks/documents/timeline stay full-width
          below this grid. */}
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="flex min-w-0 flex-col gap-4">
          {/* Status + install date controls */}
          <div className="grid gap-4 sm:grid-cols-2">
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

      {/* Operational labels (Phase L2) — shown near the lifecycle status. */}
      <JobLabelChips jobId={job.id} />

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

        {editingDetails ? (
          job.details && registry ? (
            // Phase 4c: structured edit — editable details + non-derived legacy
            // fields (title/sale_date/approval_details/notes). system_details/
            // install_details are derived from details, so they are not edited here.
            <div className="flex flex-col gap-4">
              <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                {STRUCTURED_MODE_LEGACY_FIELDS.map(({ key, label, textarea }) => (
                  <div key={key} className={textarea ? 'sm:col-span-2' : ''}>
                    <dt className="eyebrow text-faint">{label}</dt>
                    {textarea ? (
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
                    )}
                  </div>
                ))}
              </dl>
              {propertyAddress && (
                <div>
                  <span className="eyebrow text-faint">Property address</span>
                  <p className="mt-0.5 text-fg">{propertyAddress}</p>
                </div>
              )}
              <StructuredDetailsView
                registry={registry}
                details={job.details}
                editable
                edits={detailsEdits}
                onChange={handleDetailsChange}
                hideImportedNotes
              />
              {/* Network approval: structured state, under the Electrical/network details. */}
              <JobApprovalControl job={job} editing />
            </div>
          ) : (
            // Legacy edit mode (details=NULL) — unchanged raw text fields.
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              {DESCRIPTIVE_FIELDS.map(({ key, label, textarea }) => (
                <div key={key} className={textarea ? 'sm:col-span-2' : ''}>
                  <dt className="eyebrow text-faint">{label}</dt>
                  {textarea ? (
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
                  )}
                </div>
              ))}
            </dl>
          )
        ) : job.details && registry ? (
          // Phase 4a: structured Job.details (registry-driven, read-only). Takes
          // priority over the legacy pipe-string view when details is present.
          <div className="flex flex-col gap-4">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              <div>
                <dt className="eyebrow text-faint">Title</dt>
                <dd className="mt-0.5 text-fg">{job.title || '—'}</dd>
              </div>
              <div>
                <dt className="eyebrow text-faint">Sale date</dt>
                <dd className="mt-0.5 text-fg">{job.sale_date || '—'}</dd>
              </div>
            </dl>
            {propertyAddress && (
              <div>
                <span className="eyebrow text-faint">Property address</span>
                <p className="mt-0.5 text-fg">{propertyAddress}</p>
              </div>
            )}
            {/* Imported review/source notes are hidden here — the same preserved
                context is shown in Job internal notes. */}
            <StructuredDetailsView registry={registry} details={job.details} hideImportedNotes />
            {/* Network approval state is visible in read mode (before pressing Edit). */}
            <JobApprovalControl job={job} editing={false} />
          </div>
        ) : importedView ? (
          // Imported job (legacy blobs): title/sale-date + structured detail sections.
          <div className="flex flex-col gap-4">
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              <div>
                <dt className="eyebrow text-faint">Title</dt>
                <dd className="mt-0.5 text-fg">{job.title || '—'}</dd>
              </div>
              <div>
                <dt className="eyebrow text-faint">Sale date</dt>
                <dd className="mt-0.5 text-fg">{job.sale_date || '—'}</dd>
              </div>
            </dl>
            <ImportedJobDetails view={importedView} />
          </div>
        ) : (
          // Non-imported job: original plain rendering, unchanged.
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
            {DESCRIPTIVE_FIELDS.map(({ key, label, textarea }) => (
              <div key={key} className={textarea ? 'sm:col-span-2' : ''}>
                <dt className="eyebrow text-faint">{label}</dt>
                <dd className="mt-0.5 whitespace-pre-wrap text-fg">
                  {(job[key] as string | null) || '—'}
                </dd>
              </div>
            ))}
          </dl>
        )}

        {editingDetails && (
          <div className="mt-5 flex justify-end gap-3">
            <button
              onClick={() => {
                setEditingDetails(false)
                setDetailsEdits({})
                setForm(
                  Object.fromEntries(
                    DESCRIPTIVE_FIELDS.map(({ key }) => [key, (job[key] as string | null) ?? '']),
                  ),
                )
                setError(null)
              }}
              className="btn-secondary text-sm"
            >
              Cancel
            </button>
            <button
              onClick={saveDetails}
              disabled={updateMutation.isPending || !hasDetailChanges}
              className="btn-primary text-sm disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Saving…' : hasDetailChanges ? 'Save changes' : 'No changes'}
            </button>
          </div>
        )}
          </div>

          {/* Imported source notes. For details-BACKED jobs these come from the
              structured details (StructuredDetailsView's misfiled / name-cell
              fields above) — never the rendered legacy blob, which bundles
              Salesperson/Payment/Compliance/provenance. Only a details=NULL
              (legacy/native) job falls back to its plain notes text here. */}
          {!job.details && <ImportedSourceNotes text={job.notes} />}
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <InternalNotesPanel
            title="Job internal notes"
            value={job.internal_notes}
            canWrite={mayEditDetails}
            saving={updateMutation.isPending}
            onSave={(text) =>
              updateMutation.mutateAsync({ internal_notes: text || null }).then(() => undefined)
            }
          />
        </aside>
      </div>

      {/* Other jobs for this multi-job customer — open a sibling job without going
          back to the Customer page. Hidden when this is the customer's only job. */}
      <CustomerOtherJobsPanel customerId={job.customer_id} currentJobId={job.id} />

      {/* Tasks + timeline are live; Documents remains a later phase. */}
      <div className="mt-6">
        <TasksPanel jobId={job.id} />
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
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
