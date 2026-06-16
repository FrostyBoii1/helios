import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '@/lib/api'
import { DevResetPanel } from '@/components/imports/DevResetPanel'
import { useImportBatches, useUploadBatch } from '@/hooks/useImports'
import type { ImportBatch } from '@/types/imports'

export function ImportsListPage() {
  const { data, isLoading, isError } = useImportBatches()
  const batches = data?.items ?? []

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-fg">Imports</h1>
        <UploadControl />
      </div>

      {isLoading && <div className="card p-6 text-sm text-muted">Loading batches…</div>}
      {isError && (
        <div className="card border-red-500/30 p-6 text-sm text-red-300">
          Could not load import batches. Please try again.
        </div>
      )}
      {!isLoading && !isError && batches.length === 0 && (
        <div className="card p-6 text-sm text-muted">
          No import batches yet. Upload an .xlsx workbook to stage it for review.
        </div>
      )}

      {batches.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Total</th>
                <th className="px-4 py-2 font-medium">Jobs</th>
                <th className="px-4 py-2 font-medium">Ambiguous</th>
                <th className="px-4 py-2 font-medium">Issues</th>
                <th className="px-4 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((batch) => (
                <BatchRow key={batch.id} batch={batch} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* System-admin-only dev reset tools (returns null for non-admins). */}
      <DevResetPanel />
    </div>
  )
}

function BatchRow({ batch }: { batch: ImportBatch }) {
  return (
    <tr className="border-b border-line/60 last:border-0 hover:bg-elevated">
      <td className="px-4 py-2">
        <Link to={`/imports/${batch.id}`} className="font-medium text-brand-400 hover:underline">
          {batch.source_filename}
        </Link>
        <div className="text-xs text-faint">{batch.sheet_name}</div>
      </td>
      <td className="px-4 py-2">
        <span className="rounded bg-elevated px-2 py-0.5 text-xs uppercase tracking-wide text-muted">
          {batch.status}
        </span>
      </td>
      <td className="px-4 py-2 text-fg">{batch.total_rows}</td>
      <td className="px-4 py-2 text-fg">{batch.job_rows}</td>
      <td className="px-4 py-2 text-fg">{batch.ambiguous_rows}</td>
      <td className="px-4 py-2 text-fg">{batch.issue_count}</td>
      <td className="px-4 py-2 text-muted">{new Date(batch.created_at).toLocaleString()}</td>
    </tr>
  )
}

function UploadControl() {
  const inputRef = useRef<HTMLInputElement>(null)
  const upload = useUploadBatch()
  const [message, setMessage] = useState<{ kind: 'error' | 'success'; text: string } | null>(null)

  async function handleFile(file: File) {
    setMessage(null)
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      setMessage({ kind: 'error', text: 'Please choose an .xlsx file.' })
      return
    }
    try {
      const batch = await upload.mutateAsync(file)
      setMessage({ kind: 'success', text: `Parsed “${batch.source_filename}” (${batch.total_rows} rows).` })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setMessage({ kind: 'error', text: 'This exact file has already been imported.' })
      } else if (err instanceof ApiError && err.status === 400) {
        setMessage({ kind: 'error', text: 'That file could not be parsed as an .xlsx workbook.' })
      } else if (err instanceof ApiError && err.status === 403) {
        setMessage({ kind: 'error', text: 'You do not have permission to upload imports.' })
      } else {
        setMessage({ kind: 'error', text: 'Upload failed. Please try again.' })
      }
    } finally {
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <input
        ref={inputRef}
        type="file"
        accept=".xlsx"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
        }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={upload.isPending}
        className="btn-primary disabled:opacity-50"
      >
        {upload.isPending ? 'Uploading…' : 'Upload workbook'}
      </button>
      {message && (
        <span
          className={`text-xs ${message.kind === 'error' ? 'text-red-300' : 'text-emerald-300'}`}
        >
          {message.text}
        </span>
      )}
    </div>
  )
}
