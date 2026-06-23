// A single always-editable, field-level autosave input for Job Detail (H5A).
//
// Renders a label + input/textarea that saves when the user finishes interacting (blur for text,
// change for date) via useFieldAutosave — no Save button. Shows a small per-field state
// (Unsaved / Saving… / Saved ✓ / Error + Retry). When the user cannot edit, it renders a read-only
// value only. The actual PATCH is the injected single-field `onSave`.

import { ApiError } from '@/lib/api'
import { useFieldAutosave, type AutosaveStatus } from '@/hooks/useFieldAutosave'

function describeSaveError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) {
      return typeof err.detail === 'string' ? err.detail : 'You do not have permission to do that.'
    }
    if (typeof err.detail === 'string') return err.detail
  }
  return 'Could not save.'
}

function StatusChip({
  status,
  error,
  onRetry,
}: {
  status: AutosaveStatus
  error: string | null
  onRetry: () => void
}) {
  if (status === 'dirty') return <span className="text-[10px] uppercase tracking-wide text-faint">Unsaved</span>
  if (status === 'saving') return <span className="text-[10px] uppercase tracking-wide text-faint">Saving…</span>
  if (status === 'saved') return <span className="text-[10px] uppercase tracking-wide text-emerald-400">Saved ✓</span>
  if (status === 'error') {
    return (
      <span className="text-[10px] text-red-300">
        {error ?? 'Could not save.'}{' '}
        <button type="button" onClick={onRetry} className="underline hover:text-red-200">
          Retry
        </button>
      </span>
    )
  }
  return null
}

export function AutosaveField({
  label,
  value,
  kind = 'text',
  canEdit,
  onSave,
  colSpan = false,
}: {
  label: string
  value: string
  kind?: 'text' | 'date' | 'textarea'
  canEdit: boolean
  onSave: (value: string) => Promise<void>
  colSpan?: boolean
}) {
  const fa = useFieldAutosave(value, onSave, describeSaveError)
  const wrap = colSpan ? 'sm:col-span-2' : ''

  if (!canEdit) {
    return (
      <div className={wrap}>
        <dt className="eyebrow text-faint">{label}</dt>
        <dd className="mt-0.5 whitespace-pre-wrap text-fg">{value || '—'}</dd>
      </div>
    )
  }

  return (
    <div className={wrap}>
      <div className="mb-0.5 flex items-center gap-1.5">
        <span className="eyebrow text-faint">{label}</span>
        <StatusChip status={fa.status} error={fa.error} onRetry={fa.retry} />
      </div>
      {kind === 'textarea' ? (
        <textarea
          rows={2}
          value={fa.draft}
          onChange={(e) => fa.onChange(e.target.value)}
          onBlur={() => fa.commit()}
          className="input px-2 py-1 text-sm"
        />
      ) : (
        <input
          // Date commits on change (the selection IS the interaction end); text commits on blur,
          // never per keystroke.
          type={kind === 'date' ? 'date' : 'text'}
          value={fa.draft}
          onChange={(e) => {
            fa.onChange(e.target.value)
            if (kind === 'date') fa.commit(e.target.value)
          }}
          onBlur={kind === 'date' ? undefined : () => fa.commit()}
          className="input px-2 py-1 text-sm"
        />
      )}
    </div>
  )
}
