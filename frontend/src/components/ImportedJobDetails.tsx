// Structured, scannable rendering of an imported job's details (display only).
// Falls back implicitly: any value that didn't parse into a label keeps its raw
// text, and empty sections are hidden. Dark SunCentral theme.

import type { DetailRow, ImportedJobView } from '@/lib/importedJobDetails'

function Section({ title, rows }: { title: string; rows: DetailRow[] }) {
  if (rows.length === 0) return null
  return (
    <div>
      <h3 className="eyebrow mb-1.5 text-faint">{title}</h3>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {rows.map((row, i) => (
          <div key={i} className="flex flex-col">
            {row.label && <dt className="text-xs text-muted">{row.label}</dt>}
            <dd className="break-words text-sm text-fg">{row.value || '—'}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function ImportedJobDetails({ view }: { view: ImportedJobView }) {
  const provenanceRows: DetailRow[] = view.provenance.map((v) => ({ label: null, value: v }))
  return (
    <div className="flex flex-col gap-4">
      <Section title="System" rows={view.system} />
      <Section title="Install" rows={view.install} />
      <Section title="Approval" rows={view.approval} />
      <Section title="Payment" rows={view.payment} />
      <Section title="Compliance" rows={view.compliance} />
      <Section title="Other notes" rows={view.otherNotes} />
      {provenanceRows.length > 0 && (
        <div className="rounded-md border border-line bg-elevated px-3 py-2">
          <h3 className="eyebrow mb-1 text-faint">Import provenance</h3>
          {provenanceRows.map((row, i) => (
            <p key={i} className="text-xs text-muted">
              {row.value}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
