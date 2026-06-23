import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import {
  canChangeJobStatus,
  canDeleteJobs,
  canEditJobDetails,
  canEditJobInstallDate,
} from '@/auth/permissions'
import { AutosaveControl } from '@/components/AutosaveControl'
import { AutosaveField } from '@/components/AutosaveField'
import { AutosaveHardwareField } from '@/components/AutosaveHardwareField'
import { CustomerOtherJobsPanel } from '@/components/CustomerOtherJobsPanel'
import { ImportedSourceNotes } from '@/components/ImportedSourceNotes'
import { InternalNotesPanel } from '@/components/InternalNotesPanel'
import { HardwareNotes } from '@/components/HardwareNotes'
import {
  applyHardwareSystemEdits,
  deriveHardwareNotes,
  deriveSystemHardware,
  type HardwareSelection,
  type SystemHardwareField,
} from '@/lib/hardwareDisplay'
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

  // H5C: top-level (H5A), structured registry (H5B) AND hardware (H5C) fields all autosave per-field —
  // no batch hardware state and no "Edit" wall remain. Approval keeps its own explicit edit toggle
  // (decoupled from the retired hardware batch), preserving its read-vs-edit behaviour unchanged.
  const [editingApproval, setEditingApproval] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // H5A–D: descriptive / structured / hardware / install-date fields are ALL field-level autosave —
  // each control reconciles its OWN draft from the server only when idle/saved — so there is NO global
  // form reset here and a background refetch can never wipe a dirty in-progress edit.

  // path ("<section>.<key>") → field spec, for input_type-aware coercion on save.
  const fieldByPath = useMemo(() => {
    const m = new Map<string, FieldSpec>()
    if (registry) for (const f of registry.fields) m.set(detailsPath(f.storage), f)
    return m
  }, [registry])

  // H5B: autosave a single structured registry leaf. Builds the same one-leaf, coerced,
  // path-restricted patch the batch save used (`buildDetailsPatch` with one `section.key`) and
  // PATCHes `{ details: { section: { key } } }`. A no-op (unchanged after coercion) sends nothing.
  async function saveStructuredField(path: string, value: string): Promise<void> {
    const patch = buildDetailsPatch({ [path]: value }, job?.details ?? null, fieldByPath)
    if (!patch) return
    await updateMutation.mutateAsync({ details: patch })
  }

  // H5C: autosave ONE hardware System field. `applyHardwareSystemEdits` with a single key builds a
  // patch touching only that sub-section (panel / inverters / batteries / metering): free text drops
  // stale catalogue provenance; a selection stamps `canonical_hardware_id_at_parse_time` +
  // manual_correction. PATCHes only `{ details: { hardware: <one-subsection> } }`.
  async function saveHardwareField(
    field: SystemHardwareField,
    value: string,
    selection: HardwareSelection | undefined,
  ): Promise<void> {
    const patch = applyHardwareSystemEdits(
      job?.details?.hardware,
      { [field.key]: value },
      selection ? { [field.key]: selection } : undefined,
    )
    if (!patch) return
    await updateMutation.mutateAsync({ details: { hardware: patch } })
  }

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

  // H5D: install date is field-level autosave under its OWN INSTALL_ROLES permission — a single
  // `{ install_date }` PATCH, never batched with descriptive details. The shared autosave hook no-ops
  // when unchanged, retains the typed value + offers inline Retry on failure (not the global banner),
  // and never clobbers an in-flight edit on refetch.
  const saveInstallDate = (value: string): Promise<void> =>
    updateMutation.mutateAsync({ install_date: value || null }).then(() => undefined)

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

  // When a structured hardware snapshot exists, CONFIRMED hardware shows as normal System fields
  // (Panel type / Inverter / Battery / Metering·CT) and the legacy raw `panel`/`inverter` fields are
  // hidden — so the job-facing System value is the cleaned snapshot, not the raw workbook text.
  // Uncertain/ambiguous/warning evidence goes to a small "Hardware notes" area. Absent -> legacy.
  const hasHardware = job.details?.hardware != null
  const hardwareHideKeys = hasHardware ? ['panel', 'inverter'] : undefined
  const systemHardware = hasHardware ? deriveSystemHardware(job.details?.hardware) : undefined
  const hardwareNotes = hasHardware ? deriveHardwareNotes(job.details?.hardware) : []

  // H5A: top-level descriptive fields that now autosave (no Edit wall). The field set keys off
  // whether the job HAS structured details (`isStructuredJob`), NOT off registry readiness — so a
  // structured job NEVER exposes its derived blobs (system_details/install_details/approval_details/
  // notes) as editable, even during the registry-load window. A structured job exposes only title +
  // sale_date as top-level columns; a legacy details=NULL job edits the full descriptive column set.
  // All share the DESCRIPTIVE permission, so each is a single-field PATCH gated by `mayEditDetails`.
  const isStructuredJob = job.details != null
  const descriptiveAutosaveFields = isStructuredJob ? STRUCTURED_MODE_LEGACY_FIELDS : DESCRIPTIVE_FIELDS
  const saveTopLevel = (key: keyof JobInput) => (value: string) =>
    updateMutation.mutateAsync({ [key]: value || null } as JobInput).then(() => undefined)

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

      {/* Other jobs for this multi-job customer — surfaced near the top (mirrors the Customer
          page showing the jobs list first) so sibling jobs are reachable without returning to
          the Customer page. Excludes the current job; hidden when this is the only job. */}
      <CustomerOtherJobsPanel customerId={job.customer_id} currentJobId={job.id} />

      {/* Two columns: status + details on the left, a tall manual internal-notes
          panel on the right (sticky). Tasks/documents/timeline stay full-width
          below this grid. */}
      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_20rem]">
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
          {/* H5D: save-on-change autosave under its OWN INSTALL_ROLES permission — same
              AutosaveControl + status chip as every other Job Detail field. Read-only otherwise. */}
          {mayEditInstall ? (
            <AutosaveControl
              value={job.install_date ?? ''}
              kind="date"
              onSave={saveInstallDate}
              ariaLabel="Install date"
            />
          ) : (
            <p className="text-fg">{job.install_date ?? 'Not scheduled'}</p>
          )}
        </div>
      </div>

      {/* Operational labels (Phase L2) — shown near the lifecycle status. */}
      <JobLabelChips jobId={job.id} />

      {/* Descriptive details — H5A/B/C: every editable Job Detail field autosaves; there is no
          Edit wall and no global Save button. (Approval keeps its own small Edit toggle below.) */}
      <div className="card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="eyebrow">Details</h2>
        </div>

        {/* Top-level descriptive fields — always-editable, field-level autosave (H5A). Saved on
            blur (text) / change (date); non-editors see read-only values. */}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {descriptiveAutosaveFields.map(({ key, label, textarea }) => (
            <AutosaveField
              key={key}
              label={label}
              value={(job[key] as string | null) ?? ''}
              kind={textarea ? 'textarea' : key === 'sale_date' ? 'date' : 'text'}
              colSpan={textarea}
              canEdit={mayEditDetails}
              onSave={saveTopLevel(key)}
            />
          ))}
        </dl>

        {propertyAddress && (
          <div className="mt-4">
            <span className="eyebrow text-faint">Property address</span>
            <p className="mt-0.5 text-fg">{propertyAddress}</p>
          </div>
        )}

        {/* Structured registry fields (H5B) AND hardware System fields (H5C) autosave per-field —
            always-editable for editors, no Save button. Hardware free text saves on blur; a catalogue
            selection saves immediately, stamping provenance. */}
        {job.details && registry ? (
          <div className="mt-4 flex flex-col gap-4">
            <StructuredDetailsView
              registry={registry}
              details={job.details}
              recordKey={job.id}
              hideImportedNotes
              hideKeys={hardwareHideKeys}
              systemExtras={systemHardware}
              // H5B: registry value fields autosave per-field for editors; read-only otherwise.
              autosaveField={mayEditDetails ? saveStructuredField : undefined}
              // H5C: hardware System fields autosave per-field (autocomplete + safe provenance).
              renderAutosaveExtra={
                mayEditDetails
                  ? (field) => (
                      <AutosaveHardwareField
                        field={field}
                        onSave={(value, selection) => saveHardwareField(field, value, selection)}
                      />
                    )
                  : undefined
              }
            />
            {/* Network approval: structured "label is law" state with its OWN Set-approval control.
                Now that the hardware batch is retired (H5C), approval has its own explicit edit
                toggle (decoupled), preserving its read-vs-edit behaviour. Gated on mayEditDetails
                exactly as the prior coupled button was, so who can edit approval is unchanged. */}
            <div className="flex flex-col gap-1">
              {mayEditDetails && (
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => setEditingApproval((v) => !v)}
                    className="text-xs text-brand-400 underline hover:text-brand-500"
                  >
                    {editingApproval ? 'Done editing approval' : 'Edit approval'}
                  </button>
                </div>
              )}
              <JobApprovalControl
                job={job}
                editing={editingApproval}
                // H5D: collapse the editor back to the read view after a successful approval set
                // (UX only — the mutation, permission gating, and "label is law" rules are unchanged).
                onSaved={() => setEditingApproval(false)}
              />
            </div>
          </div>
        ) : importedView ? (
          // Legacy imported job (details=NULL): the descriptive fields above are now editable; the
          // parsed legacy detail sections remain below as a read-only reference.
          <div className="mt-4">
            <ImportedJobDetails view={importedView} />
          </div>
        ) : null}

        {/* Supplemental hardware notes — low-confidence/manual-review flags, ambiguous options,
            warnings, misc (the hardware VALUES show as normal System fields above, regardless of
            confidence). Read-only; absent when there is nothing to flag. */}
        {hasHardware && hardwareNotes.length > 0 && (
          <div className="mt-3">
            <HardwareNotes notes={hardwareNotes} />
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
