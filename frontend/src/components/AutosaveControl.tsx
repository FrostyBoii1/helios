// Reusable autosave control (Job Detail H5): an input / textarea / select / number / date that
// saves when the user finishes interacting — blur for text/textarea/number, change for date/select —
// never per keystroke, with an inline state chip (Unsaved / Saving… / Saved ✓ / Error + Retry). It
// wraps `useFieldAutosave` (the single source of autosave state logic); the actual PATCH is the
// injected single-field `onSave`. Shared by the top-level Job fields (`AutosaveField`) and the
// structured Job Detail registry fields (`StructuredDetailsView` autosave mode).

import { ApiError } from '@/lib/api'
import { useFieldAutosave, type AutosaveStatus } from '@/hooks/useFieldAutosave'

export type AutosaveKind = 'text' | 'textarea' | 'number' | 'date' | 'select'

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
  if (status === 'dirty') return <span className="mt-0.5 text-[10px] uppercase tracking-wide text-faint">Unsaved</span>
  if (status === 'saving') return <span className="mt-0.5 text-[10px] uppercase tracking-wide text-faint">Saving…</span>
  if (status === 'saved') return <span className="mt-0.5 text-[10px] uppercase tracking-wide text-emerald-400">Saved ✓</span>
  if (status === 'error') {
    return (
      <span className="mt-0.5 text-[10px] text-red-300">
        {error ?? 'Could not save.'}{' '}
        <button type="button" onClick={onRetry} className="underline hover:text-red-200">
          Retry
        </button>
      </span>
    )
  }
  return null
}

export function AutosaveControl({
  value,
  kind,
  options,
  onSave,
  ariaLabel,
}: {
  value: string
  kind: AutosaveKind
  options?: string[]
  onSave: (value: string) => Promise<void>
  ariaLabel?: string
}) {
  const fa = useFieldAutosave(value, onSave, describeSaveError)
  const chip = <StatusChip status={fa.status} error={fa.error} onRetry={fa.retry} />

  if (kind === 'textarea') {
    return (
      <div className="flex flex-col">
        <textarea
          rows={2}
          value={fa.draft}
          aria-label={ariaLabel}
          onChange={(e) => fa.onChange(e.target.value)}
          onBlur={() => fa.commit()}
          className="input mt-0.5 px-2 py-1 text-sm"
        />
        {chip}
      </div>
    )
  }

  if (kind === 'select') {
    return (
      <div className="flex flex-col">
        <select
          value={fa.draft}
          aria-label={ariaLabel}
          // Select commits on change (the choice IS the interaction end).
          onChange={(e) => {
            fa.onChange(e.target.value)
            fa.commit(e.target.value)
          }}
          className="input mt-0.5 px-2 py-1 text-sm"
        >
          <option value="">—</option>
          {(options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        {chip}
      </div>
    )
  }

  const type = kind === 'number' ? 'number' : kind === 'date' ? 'date' : 'text'
  const commitOnChange = kind === 'date' // date commits on change; text/number on blur
  return (
    <div className="flex flex-col">
      <input
        type={type}
        value={fa.draft}
        aria-label={ariaLabel}
        onChange={(e) => {
          fa.onChange(e.target.value)
          if (commitOnChange) fa.commit(e.target.value)
        }}
        onBlur={commitOnChange ? undefined : () => fa.commit()}
        className="input mt-0.5 px-2 py-1 text-sm"
      />
      {chip}
    </div>
  )
}
