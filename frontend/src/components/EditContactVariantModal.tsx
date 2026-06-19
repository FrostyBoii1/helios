// Admin-only modal to EDIT a Known Customer Detail (any source_type). Editing changes only
// this variant row — never the primary Customer record, the job, or the variant's source
// provenance (source_type / source row / source job are preserved by the backend). The
// backend stamps an edit marker so the detail survives a later reversal of its source row.

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { useUpdateContactVariant } from '@/hooks/useCustomers'
import type { ContactVariantInput, CustomerContactVariant } from '@/types'

// Module-local (not exported -> component-only file for Fast Refresh).
const FIELDS: { key: keyof ContactVariantInput; label: string; full?: boolean }[] = [
  { key: 'label', label: 'Label (optional)' },
  { key: 'display_name', label: 'Name' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'address_line1', label: 'Address line 1', full: true },
  { key: 'address_line2', label: 'Address line 2', full: true },
  { key: 'suburb', label: 'Suburb' },
  { key: 'state', label: 'State' },
  { key: 'postcode', label: 'Postcode' },
  { key: 'note', label: 'Note (optional)', full: true },
]
// A detail must keep at least one of these non-blank (label/note alone is not enough).
const DETAIL_KEYS: (keyof ContactVariantInput)[] = [
  'display_name', 'email', 'phone', 'address_line1', 'address_line2', 'suburb', 'state', 'postcode',
]

interface EditContactVariantModalProps {
  customerId: number
  variant: CustomerContactVariant
  onClose: () => void
  onSaved: () => void
}

export function EditContactVariantModal({
  customerId,
  variant,
  onClose,
  onSaved,
}: EditContactVariantModalProps) {
  const mutation = useUpdateContactVariant(customerId)
  const [form, setForm] = useState<Record<string, string>>(() =>
    Object.fromEntries(FIELDS.map(({ key }) => [key, (variant[key] as string | null) ?? ''])),
  )
  const [error, setError] = useState<string | null>(null)

  const hasDetail = DETAIL_KEYS.some((k) => (form[k] ?? '').trim() !== '')
  const canSave = hasDetail && !mutation.isPending

  async function handleSave() {
    if (!hasDetail) return
    setError(null)
    // Send every editable field (empty -> '' -> cleared to NULL server-side).
    const input: Record<string, string> = {}
    for (const { key } of FIELDS) {
      input[key] = (form[key] ?? '').trim()
    }
    try {
      await mutation.mutateAsync({ variantId: variant.id, input })
      onSaved()
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to edit contact details.')
      } else if (err instanceof ApiError && err.status === 400) {
        setError('Keep at least one contact or address field.')
      } else if (err instanceof ApiError && err.status === 404) {
        setError('This detail no longer exists.')
      } else {
        setError('Could not save changes. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div className="card w-full max-w-lg p-6 shadow-2xl shadow-black/40" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1 text-lg font-semibold text-fg">Edit customer contact details</h2>
        <p className="mb-4 text-sm text-muted">
          Correct this known customer-level detail. The primary customer record is not changed,
          and where this came from (its source) is kept.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {FIELDS.map(({ key, label, full }) => (
            <div key={key} className={full ? 'sm:col-span-2' : ''}>
              <label className="eyebrow text-faint">{label}</label>
              <input
                value={form[key] ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                className="input mt-1 px-2 py-1 text-sm"
              />
            </div>
          ))}
        </dl>

        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button onClick={handleSave} disabled={!canSave} className="btn-primary disabled:opacity-50">
            {mutation.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
