// Stage 4: admin-only modal to add a MANUAL alternate-contact variant for a customer.
// The backend forces source_type='manual' and rejects an all-blank entry (a label or
// note alone is not a variant). The primary customer details are never touched here.

import { useState } from 'react'
import { ApiError } from '@/lib/api'
import { useCreateContactVariant } from '@/hooks/useCustomers'
import type { ContactVariantInput } from '@/types'

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
// A variant needs at least one DETAIL field — label/note alone do not count.
const DETAIL_KEYS: (keyof ContactVariantInput)[] = [
  'display_name', 'email', 'phone', 'address_line1', 'address_line2', 'suburb', 'state', 'postcode',
]

interface AddContactVariantModalProps {
  customerId: number
  onClose: () => void
  onAdded: () => void
}

export function AddContactVariantModal({ customerId, onClose, onAdded }: AddContactVariantModalProps) {
  const mutation = useCreateContactVariant(customerId)
  const [form, setForm] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const hasDetail = DETAIL_KEYS.some((k) => (form[k] ?? '').trim() !== '')
  const canSave = hasDetail && !mutation.isPending

  async function handleSave() {
    if (!hasDetail) return
    setError(null)
    const input: ContactVariantInput = {}
    for (const { key } of FIELDS) {
      const value = (form[key] ?? '').trim()
      if (value) (input as Record<string, string>)[key] = value
    }
    try {
      await mutation.mutateAsync(input)
      onAdded()
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to add alternate details.')
      } else if (err instanceof ApiError && err.status === 400) {
        setError('Enter at least one contact or address field.')
      } else if (err instanceof ApiError && err.status === 404) {
        setError('This customer no longer exists.')
      } else {
        setError('Could not add alternate details. Please try again.')
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
        <h2 className="mb-1 text-lg font-semibold text-fg">Add alternate contact details</h2>
        <p className="mb-4 text-sm text-muted">
          A manual alternate set for this customer. The primary details are not changed.
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
            {mutation.isPending ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  )
}
