// Customer Detail (Stage 2): a read-only "Alternate contact details" card showing
// alternate customer-level identity/contact/address variants (from merges, imports,
// manual entry, or documents in later stages) WITHOUT overwriting the primary fields.
// Hidden when the customer has no variants. Display-only — no edit/archive/promote here.

import { useCustomerContactVariants } from '@/hooks/useCustomers'
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
  const { data } = useCustomerContactVariants(customerId)
  const variants = data?.items ?? []
  // Hidden entirely when there are no variants (no clutter for the common case).
  if (variants.length === 0) return null

  return (
    <div className="card p-5">
      <h2 className="eyebrow mb-3">Alternate contact details ({variants.length})</h2>
      <div className="flex flex-col gap-4">
        {variants.map((v) => {
          const lines = variantLines(v)
          return (
            <div key={v.id} className="rounded-md border border-line bg-elevated p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-fg">{v.label || 'Alternate details'}</span>
                <span className="text-[11px] text-faint">
                  {SOURCE_LABELS[v.source_type] ?? v.source_type}
                </span>
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
    </div>
  )
}
