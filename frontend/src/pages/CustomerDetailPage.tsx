import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canDeleteCustomers, canWriteCustomers } from '@/auth/permissions'
import { CustomerJobsPanel } from '@/components/CustomerJobsPanel'
import { ImportedSourceNotes } from '@/components/ImportedSourceNotes'
import { InternalNotesPanel } from '@/components/InternalNotesPanel'
import { TasksPanel } from '@/components/TasksPanel'
import { Timeline } from '@/components/Timeline'
import { useCustomer, useDeleteCustomer, useUpdateCustomer } from '@/hooks/useCustomers'
import type { CustomerInput } from '@/types'

// `notes` (imported source) and `internal_notes` (manual) are handled by their
// own dedicated panels, NOT this editable grid.
const EDITABLE_FIELDS: { key: keyof CustomerInput; label: string }[] = [
  { key: 'full_name', label: 'Full name' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'address_line1', label: 'Address line 1' },
  { key: 'address_line2', label: 'Address line 2' },
  { key: 'suburb', label: 'Suburb' },
  { key: 'state', label: 'State' },
  { key: 'postcode', label: 'Postcode' },
]

export function CustomerDetailPage() {
  const { id } = useParams()
  const customerId = Number(id)
  const navigate = useNavigate()
  const { user } = useAuth()

  const { data: customer, isLoading, isError } = useCustomer(customerId)
  const updateMutation = useUpdateCustomer(customerId)
  const deleteMutation = useDeleteCustomer()

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (customer) {
      setForm(
        Object.fromEntries(
          EDITABLE_FIELDS.map(({ key }) => [key, (customer[key] as string | null) ?? '']),
        ),
      )
    }
  }, [customer])

  const canWrite = canWriteCustomers(user?.role.name)
  const canDelete = canDeleteCustomers(user?.role.name)

  if (isLoading) return <p className="text-muted">Loading…</p>
  if (isError || !customer) {
    return (
      <div>
        <p className="text-red-400">Customer not found.</p>
        <Link to="/customers" className="mt-2 inline-block text-muted underline hover:text-fg">
          Back to customers
        </Link>
      </div>
    )
  }

  async function handleSave() {
    setError(null)
    // Send only changed fields; empty string becomes null for optional fields.
    const payload: Record<string, string | null> = {}
    for (const { key } of EDITABLE_FIELDS) {
      const current = (customer![key] as string | null) ?? ''
      const next = form[key] ?? ''
      if (next !== current) payload[key] = key === 'full_name' ? next : next || null
    }
    if (Object.keys(payload).length === 0) {
      setEditing(false)
      return
    }
    try {
      await updateMutation.mutateAsync(payload as Partial<CustomerInput>)
      setEditing(false)
    } catch {
      setError('Could not save changes.')
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete customer “${customer!.full_name}”? This can be recovered later.`)) {
      return
    }
    try {
      await deleteMutation.mutateAsync(customerId)
      navigate('/customers')
    } catch {
      setError('Could not delete the customer.')
    }
  }

  return (
    <div>
      <Link to="/customers" className="text-sm text-muted underline hover:text-fg">
        ← Customers
      </Link>

      <div className="mt-2 mb-4 flex items-start justify-between gap-3">
        <h1 className="text-2xl font-semibold text-fg">{customer.full_name}</h1>
        {canWrite && !editing && (
          <div className="flex gap-2">
            <button onClick={() => setEditing(true)} className="btn-secondary px-3 py-1.5 text-sm">
              Edit
            </button>
            {canDelete && (
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="btn-danger px-3 py-1.5 text-sm"
              >
                Delete
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Two columns: details + history on the left, a tall manual-notes panel
          on the right (sticky so it stays in view while scrolling). */}
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <div className="card p-5">
            <h2 className="eyebrow mb-3">Details</h2>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
              {EDITABLE_FIELDS.map(({ key, label }) => (
                <div key={key}>
                  <dt className="eyebrow text-faint">{label}</dt>
                  {editing ? (
                    <input
                      value={form[key] ?? ''}
                      onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                      className="input mt-1 px-2 py-1 text-sm"
                    />
                  ) : (
                    <dd className="mt-0.5 text-fg">{(customer[key] as string | null) || '—'}</dd>
                  )}
                </div>
              ))}
            </dl>

            {editing && (
              <div className="mt-5 flex justify-end gap-3">
                <button
                  onClick={() => {
                    setEditing(false)
                    setError(null)
                  }}
                  className="btn-secondary text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={updateMutation.isPending}
                  className="btn-primary text-sm"
                >
                  {updateMutation.isPending ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            )}
          </div>

          {/* Read-only imported source notes (provenance / filtered junk). */}
          <ImportedSourceNotes text={customer.notes} />

          <CustomerJobsPanel customerId={customer.id} customerName={customer.full_name} />
          <TasksPanel customerId={customer.id} />
          <Timeline customerId={customer.id} />
        </div>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <InternalNotesPanel
            title="Customer internal notes"
            value={customer.internal_notes}
            canWrite={canWrite}
            saving={updateMutation.isPending}
            onSave={(text) =>
              updateMutation.mutateAsync({ internal_notes: text || null }).then(() => undefined)
            }
          />
        </aside>
      </div>
    </div>
  )
}
