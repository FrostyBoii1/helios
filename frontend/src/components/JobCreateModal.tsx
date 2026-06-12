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
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <form onSubmit={handleSubmit} className="card w-full max-w-lg p-6 shadow-2xl shadow-black/40">
        <h2 className="text-lg font-semibold text-fg">New job</h2>
        <p className="mb-4 text-sm text-muted">
          for <span className="font-medium text-fg">{customerName}</span> — a case number is
          assigned automatically.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <Field label="Title">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. 6.6kW solar install"
            className="input"
          />
        </Field>
        <Field label="Sale date">
          <input
            type="date"
            value={saleDate}
            onChange={(e) => setSaleDate(e.target.value)}
            className="input"
          />
        </Field>
        <Field label="Notes">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="input"
          />
        </Field>

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={createMutation.isPending} className="btn-primary">
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
      <span className="mb-1 block font-medium text-fg">{label}</span>
      {children}
    </label>
  )
}
