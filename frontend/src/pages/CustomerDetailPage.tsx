import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canDeleteCustomers, canWriteCustomers } from '@/auth/permissions'
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

  if (isLoading) return <p className="text-slate-500">Loading…</p>
  if (isError || !customer) {
    return (
      <div>
        <p className="text-red-600">Customer not found.</p>
        <Link to="/customers" className="mt-2 inline-block text-slate-700 underline">
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
      <Link to="/customers" className="text-sm text-slate-500 underline">
        ← Customers
      </Link>

      <div className="mt-2 mb-4 flex items-start justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-800">{customer.full_name}</h1>
        {canWrite && !editing && (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(true)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              Edit
            </button>
            {canDelete && (
              <button
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                Delete
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Details
        </h2>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          {EDITABLE_FIELDS.map(({ key, label }) => (
            <div key={key}>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {label}
              </dt>
              {editing ? (
                <input
                  value={form[key] ?? ''}
                  onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))}
                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400"
                />
              ) : (
                <dd className="mt-0.5 text-slate-800">
                  {(customer[key] as string | null) || '—'}
                </dd>
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
              className="rounded-md border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
            >
              {updateMutation.isPending ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        )}
      </div>

      {/* Placeholders — wired in later phases (out of scope for the Customers phase). */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <PlaceholderPanel title="Jobs" hint="Jobs for this customer appear here (Jobs phase)." />
        <PlaceholderPanel title="Timeline" hint="Activity history appears here (Activity Timeline phase)." />
      </div>
    </div>
  )
}

function PlaceholderPanel({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white p-4">
      <h3 className="font-medium text-slate-700">{title}</h3>
      <p className="mt-1 text-sm text-slate-400">{hint}</p>
    </div>
  )
}
