// "Hardware notes" — a small READ-ONLY area for uncertain / ambiguous / warning / manual-review /
// unmatched hardware evidence from the Job.details.hardware snapshot (Hardware Parser lane).
//
// CONFIRMED parsed hardware shows as normal System fields (see lib/hardwareDisplay + the System
// section); only review-worthy evidence lands here. Replaces the former separate "Hardware" /
// "System hardware" editor card — editing the structured snapshot is deferred (the snapshot stays
// the durable, editable-via-API store; this view never reads the catalogue or live-updates).

export function HardwareNotes({ notes }: { notes: string[] }) {
  if (notes.length === 0) return null
  return (
    <div className="rounded-md border border-amber-500/20 bg-amber-500/5 p-3">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-300/80">
        Hardware notes
      </h4>
      <ul className="flex flex-col gap-1 text-xs text-muted">
        {notes.map((n, i) => (
          <li key={i}>{n}</li>
        ))}
      </ul>
    </div>
  )
}
