// Customer Detail: the "Alternate contact details" card showing alternate customer-level
// identity/contact/address variants (from merges + manual entry) WITHOUT overwriting the
// primary fields. Read-only for everyone; admins (Stage 4) can ADD a manual variant and
// ARCHIVE manual variants. Source-derived (merged) variants are immutable — no archive,
// no edit, no promote. Hidden for non-admins when there are no variants.

import { useState } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { canManageCustomerVariants } from '@/auth/permissions'
import { AddContactVariantModal } from '@/components/AddContactVariantModal'
import { useArchiveContactVariant, useCustomerContactVariants } from '@/hooks/useCustomers'
import type { CustomerContactVariant } from '@/types'

// Module-local (not exported, so this stays a component-only file for Fast Refresh).
const SOURCE_LABELS: Record<string, string> = {
  merged_customer: 'Merged customer',
  import_row: 'Import row',
  manual: 'Manual',
  document: 'Document',
}

function variantLines(v: CustomerContactVariant): { label: string; value: string }[] {
  const city = [v.suburb, v.state, v.postcode]
    .map((p) => p?.trim())
    .filter(Boolean)
    .join(' ')
  const address = [v.address_line1, v.address_line2, city]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(', ')
  const lines: { label: string; value: string }[] = []
  if (v.display_name) lines.push({ label: 'Name', value: v.display_name })
  if (v.email) lines.push({ label: 'Email', value: v.email })
  if (v.phone) lines.push({ label: 'Phone', value: v.phone })
  if (address) lines.push({ label: 'Address', value: address })
  return lines
}

export function AlternateContactDetailsCard({ customerId }: { customerId: number }) {
  const { user } = useAuth()
  const canManage = canManageCustomerVariants(user?.role.name)
  const { data } = useCustomerContactVariants(customerId)
  const archiveMutation = useArchiveContactVariant(customerId)
  const [adding, setAdding] = useState(false)
  const variants = data?.items ?? []

  // Non-admins with no variants see nothing (no clutter). Admins always see the card so
  // they can add the first alternate set.
  if (variants.length === 0 && !canManage) return null

  function handleArchive(id: number) {
    if (window.confirm('Archive this alternate detail set? It can be recovered later.')) {
      archiveMutation.mutate(id)
    }
  }

  return (
    <div className="card p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="eyebrow">Alternate contact details ({variants.length})</h2>
        {canManage && (
          <button onClick={() => setAdding(true)} className="btn-secondary px-3 py-1 text-sm">
            Add alternate details
          </button>
        )}
      </div>

      {variants.length === 0 ? (
        <p className="text-sm text-faint">No alternate contact details yet.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {variants.map((v) => {
            const lines = variantLines(v)
            // Only admins may archive, and only MANUAL variants (merged snapshots are immutable).
            const canArchive = canManage && v.source_type === 'manual'
            return (
              <div key={v.id} className="rounded-md border border-line bg-elevated p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-fg">{v.label || 'Alternate details'}</span>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className="text-[11px] text-faint">
                      {SOURCE_LABELS[v.source_type] ?? v.source_type}
                    </span>
                    {canArchive && (
                      <button
                        onClick={() => handleArchive(v.id)}
                        disabled={archiveMutation.isPending}
                        className="text-[11px] text-red-300 hover:underline disabled:opacity-50"
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </div>
                {lines.length > 0 ? (
                  <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                    {lines.map((l, i) => (
                      <div key={i}>
                        <dt className="eyebrow text-faint">{l.label}</dt>
                        <dd className="mt-0.5 break-words text-sm text-fg">{l.value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="text-xs text-faint">No populated fields.</p>
                )}
                {v.note && <p className="mt-2 text-xs text-muted">{v.note}</p>}
              </div>
            )
          })}
        </div>
      )}

      {adding && (
        <AddContactVariantModal
          customerId={customerId}
          onClose={() => setAdding(false)}
          onAdded={() => setAdding(false)}
        />
      )}
    </div>
  )
}
