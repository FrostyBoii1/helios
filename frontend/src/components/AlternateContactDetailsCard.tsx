// Customer Detail: "Known customer details" — every additional customer-LEVEL contact set
// on record for this customer (from merges, imports and manual entry), shown beside the
// primary Details card as part of the same customer-details area. These are real known
// details for the same customer, NOT "lesser alternates". The primary Details card above
// stays the source of truth; nothing here overwrites it. Admins can ADD a manual set, EDIT
// any set (the primary record + provenance are never changed by an edit), and ARCHIVE manual
// sets. Each entry shows a SOURCE line so you can tell which import row/job contributed it.
// Job-site addresses are NOT shown here — they live in the Job sites / Jobs panels.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canManageCustomerVariants } from '@/auth/permissions'
import { AddContactVariantModal } from '@/components/AddContactVariantModal'
import { EditContactVariantModal } from '@/components/EditContactVariantModal'
import {
  useArchiveContactVariant,
  useCustomerContactVariants,
} from '@/hooks/useCustomers'
import type { CustomerContactVariant } from '@/types'

// Module-local (not exported, so this stays a component-only file for Fast Refresh).
const SOURCE_LABELS: Record<string, string> = {
  manual: 'Added manually',
  merged_customer: 'From merged customer',
  import_row: 'Imported',
  document: 'From document',
}

// How many sets to show before collapsing behind a "Show all" toggle.
const COLLAPSE_AFTER = 4

// A clean one-line summary of a detail set: Name · phone · email · address.
function summaryParts(v: CustomerContactVariant): string[] {
  const city = [v.suburb, v.state, v.postcode]
    .map((p) => p?.trim())
    .filter(Boolean)
    .join(' ')
  const address = [v.address_line1, v.address_line2, city]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
    .join(', ')
  return [v.display_name, v.phone, v.email, address]
    .map((p) => (p ? String(p).trim() : ''))
    .filter(Boolean)
}

// The SOURCE provenance line shown before each detail set. Uses only SAFE API-computed
// provenance (workbook row number + committed job case number/id), never raw FK ids.
function ProvenanceLine({ v }: { v: CustomerContactVariant }) {
  const isImport = v.source_type === 'import_row'
  const rowText =
    isImport && v.source_row_number != null ? `Source row #${v.source_row_number}` : null
  const base = SOURCE_LABELS[v.source_type] ?? v.source_type
  return (
    <p className="mb-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-faint">
      <span>{rowText ?? base}</span>
      {isImport && v.source_job_case_number && (
        <>
          <span aria-hidden>·</span>
          {v.source_job_id != null ? (
            <Link to={`/jobs/${v.source_job_id}`} className="text-brand-400 hover:underline">
              Job {v.source_job_case_number}
            </Link>
          ) : (
            <span>Job {v.source_job_case_number}</span>
          )}
        </>
      )}
      {isImport && v.source_reversed && (
        <>
          <span aria-hidden>·</span>
          <span className="text-amber-300">import reversed</span>
        </>
      )}
      {v.edited_at && (
        <>
          <span aria-hidden>·</span>
          <span>edited</span>
        </>
      )}
    </p>
  )
}

export function AlternateContactDetailsCard({ customerId }: { customerId: number }) {
  const { user } = useAuth()
  const canManage = canManageCustomerVariants(user?.role.name)
  const { data } = useCustomerContactVariants(customerId)
  const archiveMutation = useArchiveContactVariant(customerId)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<CustomerContactVariant | null>(null)
  const [expanded, setExpanded] = useState(false)
  const variants = data?.items ?? []

  // Non-admins with no extra details see nothing (no clutter). Admins always see the card
  // so they can add the first set.
  if (variants.length === 0 && !canManage) return null

  const shown = expanded ? variants : variants.slice(0, COLLAPSE_AFTER)
  const hiddenCount = variants.length - shown.length

  function handleArchive(id: number) {
    if (window.confirm('Archive this set of contact details? It can be recovered later.')) {
      archiveMutation.mutate(id)
    }
  }

  return (
    <div className="card p-5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <h2 className="eyebrow">Known customer details ({variants.length})</h2>
        {canManage && (
          <button onClick={() => setAdding(true)} className="btn-secondary px-3 py-1 text-sm">
            Add contact details
          </button>
        )}
      </div>
      <p className="mb-3 text-xs text-faint">
        Other names, phones and emails on record for this customer (from merges, imports and
        manual entry), each showing where it came from. The primary Details above remain the
        source of truth.
      </p>

      {variants.length === 0 ? (
        <p className="text-sm text-faint">No additional contact details recorded yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {shown.map((v) => {
            const parts = summaryParts(v)
            // Only admins may archive, and only MANUAL sets (source-derived are not archivable).
            const canArchive = canManage && v.source_type === 'manual'
            return (
              <div
                key={v.id}
                className="flex items-start justify-between gap-3 rounded-md border border-line bg-elevated px-3 py-2"
              >
                <div className="min-w-0">
                  <ProvenanceLine v={v} />
                  {parts.length > 0 ? (
                    <p className="break-words text-sm text-fg">{parts.join(' · ')}</p>
                  ) : (
                    <p className="text-sm text-faint">No populated fields.</p>
                  )}
                  {v.label && <p className="mt-0.5 text-[11px] text-muted">{v.label}</p>}
                  {v.note && <p className="mt-0.5 text-[11px] text-muted">{v.note}</p>}
                </div>
                {canManage && (
                  <div className="flex shrink-0 items-center gap-3 pt-0.5">
                    <button
                      onClick={() => setEditing(v)}
                      className="text-[11px] text-brand-400 hover:underline"
                    >
                      Edit
                    </button>
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
                )}
              </div>
            )
          })}

          {variants.length > COLLAPSE_AFTER && (
            <button
              onClick={() => setExpanded((e) => !e)}
              className="self-start text-xs text-brand-400 hover:underline"
            >
              {expanded ? 'Show fewer' : `Show all (${hiddenCount} more)`}
            </button>
          )}
        </div>
      )}

      {adding && (
        <AddContactVariantModal
          customerId={customerId}
          onClose={() => setAdding(false)}
          onAdded={() => setAdding(false)}
        />
      )}

      {editing && (
        <EditContactVariantModal
          customerId={customerId}
          variant={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
    </div>
  )
}
