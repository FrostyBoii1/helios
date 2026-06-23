// A single always-editable, field-level autosave field for top-level Job Detail columns (H5A).
//
// Renders a label + an `AutosaveControl` that saves when the user finishes interacting (blur for
// text/textarea, change for date) — no Save button, with a per-field state indicator. When the user
// cannot edit, it renders a read-only value only. The actual PATCH is the injected single-field
// `onSave`. All autosave state/indicator logic lives in `AutosaveControl` / `useFieldAutosave`.

import { AutosaveControl, type AutosaveKind } from '@/components/AutosaveControl'

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
  kind?: AutosaveKind
  canEdit: boolean
  onSave: (value: string) => Promise<void>
  colSpan?: boolean
}) {
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
      <span className="eyebrow text-faint">{label}</span>
      <AutosaveControl value={value} kind={kind} onSave={onSave} ariaLabel={label} />
    </div>
  )
}
