import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canDeleteCustomers, canWriteCustomers } from '@/auth/permissions'
import { CustomerJobsPanel } from '@/components/CustomerJobsPanel'
import { useCustomer, useDeleteCustomer, useUpdateCustomer } from '@/hooks/useCustomers'
import type { CustomerInput } from '@/types'

const EDITABLE_FIELDS: { key: keyof CustomerInput; label: string }[] = [
  { key: 'full_name', label: 'Full name' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'address_line1', label: 'Address line 1' },
  { key: 'address_line2', label: 'Address line 2' },
  { key: 'suburb', label: 'Suburb' },
  { key: 'state', label: 'State' },
  { key: 'postcode', label: 'Postcode' },
  { key: 'notes', label: 'Notes' },
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

      {/* Jobs for this customer (Jobs phase). Timeline remains a later phase. */}
      <div className="mt-6">
        <CustomerJobsPanel customerId={customer.id} customerName={customer.full_name} />
      </div>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <PlaceholderPanel title="Timeline" hint="Activity history appears here (Activity Timeline phase)." />
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
