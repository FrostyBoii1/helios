// Reusable hardware textbox with catalogue autocomplete (Hardware Parser lane, H3/H4).
// Shared by import review (ImportRowModal) and committed Job Detail (JobDetailPage).
//
// A free-text input that, as the user types, queries the lean staff search feed
// (GET /api/v1/hardware/search) and offers canonical-hardware suggestions. Typing free text is
// always allowed and saved as-is; clicking a suggestion autofills the box with the canonical
// display/model text (preserving any leading "N ×" quantity prefix) and emits `onSelect` so the
// caller can record provenance (canonical id + manual_correction). It writes only TEXT/provenance
// into the snapshot — never a live catalogue reference.

import { useEffect, useRef, useState } from 'react'
import { useHardwareSearch } from '@/hooks/useHardware'
import type { HardwareCategory, HardwareSearchResult } from '@/types'

const QTY_PREFIX_RE = /^\s*(\d+\s*[x×*]\s*)/i

/** Canonical job-facing label for a result (display_name, else model, else brand, else spec_id). */
function hardwareResultLabel(r: HardwareSearchResult): string {
  return (
    r.display_name?.trim() ||
    r.canonical_model?.trim() ||
    r.brand?.trim() ||
    r.spec_id
  )
}

function resultMeta(r: HardwareSearchResult): string {
  return [
    r.brand,
    r.canonical_model && r.canonical_model !== r.display_name ? r.canonical_model : null,
    r.nominal_kw != null ? `${r.nominal_kw}kW` : null,
    r.capacity_kwh != null ? `${r.capacity_kwh}kWh` : null,
    r.wattage_w != null ? `${r.wattage_w}W` : null,
    r.phases,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function HardwareSearchInput({
  value,
  onChange,
  onSelect,
  category,
  disabled,
  placeholder,
}: {
  value: string
  onChange: (text: string) => void
  onSelect: (result: HardwareSearchResult, text: string) => void
  category?: HardwareCategory
  disabled?: boolean
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  // `value` drives the input; `query` is the debounced search term so we don't fire per keystroke.
  const [query, setQuery] = useState(value)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const id = setTimeout(() => setQuery(value), 200)
    return () => clearTimeout(id)
  }, [value])

  const { data, isFetching } = useHardwareSearch(query, category, { enabled: open })
  const results = data?.items ?? []

  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [])

  function pick(r: HardwareSearchResult) {
    const label = hardwareResultLabel(r)
    // Preserve any "N ×" quantity prefix the user already typed; only the model part is replaced.
    const m = value.match(QTY_PREFIX_RE)
    const filled = m ? `${m[1]}${label}` : label
    onChange(filled)
    onSelect(r, filled)
    setOpen(false)
  }

  const showMenu = open && query.trim().length >= 2

  return (
    <div ref={wrapRef} className="relative">
      <input
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        className="input mt-0.5 px-2 py-1 text-sm"
      />
      {showMenu && (
        <div className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-line bg-elevated shadow-lg">
          {isFetching && results.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-faint">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-faint">
              No catalogue match — free text is saved as typed.
            </div>
          ) : (
            results.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => pick(r)}
                className="block w-full cursor-pointer px-2 py-1.5 text-left text-sm hover:bg-surface"
              >
                <span className="text-fg">{hardwareResultLabel(r)}</span>
                {resultMeta(r) && <span className="ml-1.5 text-xs text-faint">{resultMeta(r)}</span>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
