// Compact, read-only label chips for dense rows (the Jobs list). Shows the first
// `max` labels then a "+N" overflow chip; the full label list is available via the
// hover title. Presentational only — no fetching, no add/remove (that lives in
// JobLabelChips on the Job detail page).

import type { JobLabelChip } from '@/types'

// Dark-tuned translucent chip styles, keyed by the label's colour token.
const SLATE = 'bg-slate-500/15 text-slate-300 ring-slate-400/25'
const COLOR_CLASSES: Record<string, string> = {
  green: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/25',
  amber: 'bg-amber-500/15 text-amber-300 ring-amber-400/25',
  red: 'bg-red-500/15 text-red-300 ring-red-400/25',
  orange: 'bg-orange-500/15 text-orange-300 ring-orange-400/25',
  blue: 'bg-sky-500/15 text-sky-300 ring-sky-400/25',
  slate: SLATE,
}

function colorClass(token: string): string {
  return COLOR_CLASSES[token] ?? SLATE
}

const CHIP = 'inline-flex max-w-[10rem] items-center truncate rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset'

export function LabelChips({ labels, max = 3 }: { labels?: JobLabelChip[] | null; max?: number }) {
  const list = labels ?? []
  if (list.length === 0) return <span className="text-faint">—</span>

  const shown = list.slice(0, max)
  const extra = list.length - shown.length
  const allNames = list.map((l) => l.name).join(', ')

  return (
    <div className="flex flex-wrap items-center gap-1" title={allNames}>
      {shown.map((l) => (
        <span key={l.key} className={`${CHIP} ${colorClass(l.color)}`} title={l.name}>
          {l.name}
        </span>
      ))}
      {extra > 0 && (
        <span className={`${CHIP} ${SLATE}`} title={allNames}>
          +{extra}
        </span>
      )}
    </div>
  )
}
