interface ImportedSourceNotesProps {
  /**
   * Legacy/imported free-text notes (Customer.notes, or a details=NULL Job.notes).
   * For details-BACKED jobs this component is NOT used — their imported source
   * text comes from the structured details (StructuredDetailsView's misfiled /
   * name-cell fields), never from the rendered legacy blob.
   */
  text: string | null
}

// Pure provenance lines ("Imported from legacy workbook (batch …, row …, ref …).")
// are an audit footer, not a note — never surfaced here.
const PROVENANCE_RE = /^imported from legacy workbook/i

/**
 * Read-only display of imported source notes for records WITHOUT structured
 * details (customers, and any legacy details=NULL job). Shows the preserved
 * source text minus the provenance footer. Kept clearly separate from — and
 * visually secondary to — the manual internal-notes panel. Renders nothing when
 * there is no real content left after filtering.
 */
export function ImportedSourceNotes({ text }: ImportedSourceNotesProps) {
  const cleaned = (text ?? '')
    .split('\n')
    .filter((line) => !PROVENANCE_RE.test(line.trim()))
    .join('\n')
    .trim()
  if (!cleaned) return null
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h2 className="eyebrow mb-1">Imported source notes</h2>
      <p className="mb-2 text-xs text-faint">
        Original imported source text, preserved — read-only. Not staff notes.
      </p>
      <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-muted">
        {cleaned}
      </pre>
    </div>
  )
}
