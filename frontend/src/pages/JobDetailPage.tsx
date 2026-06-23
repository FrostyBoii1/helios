import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import {
  canChangeJobStatus,
  canDeleteJobs,
  canEditJobDetails,
  canEditJobInstallDate,
} from '@/auth/permissions'
import { AutosaveField } from '@/components/AutosaveField'
import { CustomerOtherJobsPanel } from '@/components/CustomerOtherJobsPanel'
import { ImportedSourceNotes } from '@/components/ImportedSourceNotes'
import { InternalNotesPanel } from '@/components/InternalNotesPanel'
import { HardwareNotes } from '@/components/HardwareNotes'
import { HardwareSearchInput } from '@/components/HardwareSearchInput'
import {
  applyHardwareSystemEdits,
  deriveHardwareNotes,
  deriveSystemHardware,
  type HardwareSelection,
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
import { ApiError } from '@/lib/api'
import { buildDetailsPatch } from '@/lib/detailsPatch'
import { parseImportedJobDetails } from '@/lib/importedJobDetails'
import type { HardwareSearchResult, JobInput, JobStatus } from '@/types'
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

  // H5B: structured registry fields autosave per-field (no batch state). `editingDetails` now toggles
  // ONLY the TEMPORARY hardware Edit/Save flow below (H5C converts hardware to autosave).
  const [editingDetails, setEditingDetails] = useState(false)
  // System-hardware textbox edits (Panel type / Inverter / Battery / Metering), keyed by field key;
  // folded into the same PATCH as details.hardware on save. `hardwareSelections` records the
  // catalogue pick per field (provenance) when the user chose an autocomplete result.
  const [hardwareEdits, setHardwareEdits] = useState<Record<string, string>>({})
  const [hardwareSelections, setHardwareSelections] = useState<Record<string, HardwareSelection>>({})
  const [installDate, setInstallDate] = useState('')
  const [editingInstall, setEditingInstall] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // H5A: top-level descriptive fields are now field-level autosave (each AutosaveField reconciles
  // its OWN draft from the server, only when it isn't mid-edit), so there is NO global form reset
  // here — a refetch can never wipe a dirty field. The structured-details + hardware edits below
  // TEMPORARILY keep the batch Edit/Save flow (converted to autosave in H5B/H5C).
  useEffect(() => {
    if (job) {
      setInstallDate(job.install_date ?? '')
      setHardwareEdits({})
      setHardwareSelections({})
    }
  }, [job])

  // path ("<section>.<key>") → field spec, for input_type-aware coercion on save.
  const fieldByPath = useMemo(() => {
    const m = new Map<string, FieldSpec>()
    if (registry) for (const f of registry.fields) m.set(detailsPath(f.storage), f)
    return m
  }, [registry])

  // Two DISTINCT concepts — do NOT collapse them:
  //  • whether the job HAS structured details (`job.details`) decides which fields are top-level
  //    columns vs derived/structured — drives the autosave field set (see `isStructuredJob` below);
  //  • whether the structured-details EDITOR can render (needs the registry too) — `structuredEditable`.
  // A structured job is still structured while the registry is loading, so the autosave field set must
  // key off `job.details` ALONE, never off `structuredEditable`, or derived blobs (system_details/
  // install_details/approval_details/notes) would briefly become editable during that load window.
  const structuredEditable = !!(job?.details && registry)

  // H5B: autosave a single structured registry leaf. Builds the same one-leaf, coerced,
  // path-restricted patch the batch save used (`buildDetailsPatch` with one `section.key`) and
  // PATCHes `{ details: { section: { key } } }`. A no-op (unchanged after coercion) sends nothing.
  async function saveStructuredField(path: string, value: string): Promise<void> {
    const patch = buildDetailsPatch({ [path]: value }, job?.details ?? null, fieldByPath)
    if (!patch) return
    await updateMutation.mutateAsync({ details: patch })
  }

  function handleHardwareChange(key: string, value: string) {
    setHardwareEdits((prev) => ({ ...prev, [key]: value }))
    // Typing invalidates any prior catalogue pick for this field, so a stale canonical id is never
    // stamped onto hand-edited text. A pick() calls this (clear) THEN handleHardwareSelect (set), and
    // the ordered functional updates compose to "set", so a genuine selection survives.
    setHardwareSelections((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
  }
  function handleHardwareSelect(key: string, result: HardwareSearchResult) {
    setHardwareSelections((prev) => ({
      ...prev,
      [key]: { id: result.id, confidence: 'manual_correction', model: result.canonical_model ?? null },
    }))
  }

  // H5B: this batch payload now covers ONLY the TEMPORARY hardware Edit/Save flow. Top-level
  // descriptive fields (H5A) and structured registry fields (H5B) autosave individually, so they are
  // no longer collected here; H5C will convert hardware to autosave and retire this batch entirely.
  function buildPayload(): JobInput {
    const payload: JobInput = {}
    const hwPatch = applyHardwareSystemEdits(job?.details?.hardware, hardwareEdits, hardwareSelections)
    if (hwPatch) payload.details = { hardware: hwPatch }
    return payload
  }
  const pendingPayload = useMemo(buildPayload, [hardwareEdits, hardwareSelections, job])
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

  // H5B: the batch save now covers ONLY the temporary hardware edit flow.
  async function saveDetails() {
    setError(null)
    if (!hasDetailChanges) {
      setEditingDetails(false)
      return
    }
    try {
      await updateMutation.mutateAsync(pendingPayload)
      setHardwareEdits({})
      setHardwareSelections({})
      setEditingDetails(false)
    } catch (err) {
      setError(describeError(err, 'Could not save hardware.'))
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
          {/* H5B: top-level descriptive fields (H5A) AND structured registry fields (H5B) autosave —
              no Edit wall. This button is TEMPORARY and now governs only the remaining batch items —
              hardware + the approval control's edit form — until hardware converts to autosave in
              H5C. (Approval editing stays gated on this button exactly as before, unchanged.) */}
          {structuredEditable && mayEditDetails && !editingDetails && (
            <button
              onClick={() => setEditingDetails(true)}
              className="btn-secondary px-3 py-1 text-sm"
            >
              Edit hardware &amp; approval
            </button>
          )}
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

        {/* Structured registry fields autosave per-field (H5B) — always-editable for editors, no
            Save button. Hardware fields TEMPORARILY keep the batch Edit/Save flow (the "Edit hardware
            & approval" button) until H5C converts them. */}
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
              // Hardware extras stay on the temporary batch flow — editable only in the hardware Edit
              // mode (H5C converts them to autosave like the registry fields).
              extraEdits={editingDetails ? hardwareEdits : undefined}
              onExtraChange={editingDetails && mayEditDetails ? handleHardwareChange : undefined}
              renderExtraInput={
                editingDetails && mayEditDetails
                  ? (field, value, onChange) => (
                      <HardwareSearchInput
                        value={value}
                        onChange={onChange}
                        onSelect={(result) => handleHardwareSelect(field.key, result)}
                        category={field.category}
                        placeholder={field.label}
                      />
                    )
                  : undefined
              }
            />
            {/* Network approval: structured state with its own Set-approval control. Its editable
                form is gated on the temporary Edit button exactly as before (unchanged). */}
            <JobApprovalControl job={job} editing={editingDetails} />
            {/* Temporary hardware Save/Cancel bar (H5C retires it). Saves only the hardware sub-patch. */}
            {editingDetails && (
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => {
                    setEditingDetails(false)
                    setHardwareEdits({})
                    setHardwareSelections({})
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
                  {updateMutation.isPending ? 'Saving…' : hasDetailChanges ? 'Save hardware' : 'No changes'}
                </button>
              </div>
            )}
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
