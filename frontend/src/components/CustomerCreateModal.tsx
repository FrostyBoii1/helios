import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { useCreateCustomer } from '@/hooks/useCustomers'
import type { CustomerInput } from '@/types'

interface CustomerCreateModalProps {
  onClose: () => void
  onCreated: (customerId: number) => void
}

const EMPTY: CustomerInput = {
  full_name: '',
  email: '',
  phone: '',
  suburb: '',
  postcode: '',
}

export function CustomerCreateModal({ onClose, onCreated }: CustomerCreateModalProps) {
  const [form, setForm] = useState<CustomerInput>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateCustomer()

  function update(field: keyof CustomerInput, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    // Strip empty optional strings so we don't send "" for nullable fields.
    const payload: CustomerInput = { full_name: form.full_name.trim() }
    for (const key of ['email', 'phone', 'suburb', 'postcode'] as const) {
      const v = form[key]?.toString().trim()
      if (v) payload[key] = v
    }
    try {
      const created = await createMutation.mutateAsync(payload)
      onCreated(created.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError('Please check the form — name is required and email must be valid.')
      } else if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to create customers.')
      } else {
        setError('Could not create the customer. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/40 px-4"
      role="dialog"
      aria-modal="true"
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg"
      >
        <h2 className="mb-4 text-lg font-semibold text-slate-800">New customer</h2>

        {error && (
          <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Full name *" className="sm:col-span-2">
            <input
              required
              value={form.full_name}
              onChange={(e) => update('full_name', e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={form.email ?? ''}
              onChange={(e) => update('email', e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </Field>
          <Field label="Phone">
            <input
              value={form.phone ?? ''}
              onChange={(e) => update('phone', e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </Field>
          <Field label="Suburb">
            <input
              value={form.suburb ?? ''}
              onChange={(e) => update('suburb', e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </Field>
          <Field label="Postcode">
            <input
              value={form.postcode ?? ''}
              onChange={(e) => update('postcode', e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </Field>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded-md bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-60"
          >
            {createMutation.isPending ? 'Creating…' : 'Create customer'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <label className={`block text-sm ${className ?? ''}`}>
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}
