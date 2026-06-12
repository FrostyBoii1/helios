import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { useCreateJob } from '@/hooks/useJobs'
import type { JobInput } from '@/types'

interface JobCreateModalProps {
  customerId: number
  customerName: string
  onClose: () => void
  onCreated: (jobId: number) => void
}

export function JobCreateModal({
  customerId,
  customerName,
  onClose,
  onCreated,
}: JobCreateModalProps) {
  const [title, setTitle] = useState('')
  const [saleDate, setSaleDate] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateJob()

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    const input: JobInput = {}
    if (title.trim()) input.title = title.trim()
    if (saleDate) input.sale_date = saleDate
    if (notes.trim()) input.notes = notes.trim()
    try {
      const created = await createMutation.mutateAsync({ customerId, input })
      onCreated(created.id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError('You do not have permission to create jobs.')
      } else {
        setError('Could not create the job. Please try again.')
      }
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/40 px-4"
      role="dialog"
      aria-modal="true"
    >
      <form onSubmit={handleSubmit} className="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-slate-800">New job</h2>
        <p className="mb-4 text-sm text-slate-500">
          for <span className="font-medium">{customerName}</span> — a case number is assigned
          automatically.
        </p>

        {error && (
          <div className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
        )}

        <Field label="Title">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. 6.6kW solar install"
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
        </Field>
        <Field label="Sale date">
          <input
            type="date"
            value={saleDate}
            onChange={(e) => setSaleDate(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
        </Field>
        <Field label="Notes">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
          />
        </Field>

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
            {createMutation.isPending ? 'Creating…' : 'Create job'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="mb-3 block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}
