// Reusable hardware textbox with catalogue autocomplete (Hardware Parser lane, H3/H4).
// Shared by import review (ImportRowModal) and committed Job Detail (JobDetailPage).
//
// A free-text input that, as the user types, queries the lean staff search feed
// (GET /api/v1/hardware/search) and offers canonical-hardware suggestions. Typing free text is
// always allowed and saved as-is; clicking a suggestion autofills the box with the canonical
// display/model text (preserving any leading "N ×" quantity prefix) and emits `onSelect` so the
// caller can record provenance (canonical id + manual_correction). It writes only TEXT/provenance
// into the snapshot — never a live catalogue reference.

import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
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
  onBlur,
  category,
  disabled,
  placeholder,
}: {
  value: string
  onChange: (text: string) => void
  onSelect: (result: HardwareSearchResult, text: string) => void
  // Optional: called when the input loses focus (used by Job Detail autosave to save free text on
  // blur). Import review passes none. When provided, a suggestion click is prevented from blurring
  // the input first (so a pick doesn't trigger a premature free-text save before onSelect).
  onBlur?: () => void
  category?: HardwareCategory
  disabled?: boolean
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  // `value` drives the input; `query` is the debounced search term so we don't fire per keystroke.
  const [query, setQuery] = useState(value)
  // Keyboard-highlighted suggestion index (-1 = none). Additive: free-text / mouse behaviour unchanged.
  const [active, setActive] = useState(-1)
  const wrapRef = useRef<HTMLDivElement>(null)
  const listId = useId()

  useEffect(() => {
    const id = setTimeout(() => setQuery(value), 200)
    return () => clearTimeout(id)
  }, [value])

  const { data, isFetching } = useHardwareSearch(query, category, { enabled: open })
  const results = data?.items ?? []

  // Reset the keyboard highlight whenever the result set changes (new debounced query) or the menu
  // closes, so a stale index can never point at the wrong suggestion.
  useEffect(() => {
    setActive(-1)
  }, [query, open])

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
  // Clamp the highlight to the live result set (it may shrink between renders).
  const activeClamped = active >= 0 && active < results.length ? active : -1

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    // Escape closes the dropdown (without changing the typed value).
    if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
      }
      return
    }
    if (!showMenu || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1))
    } else if (e.key === 'Enter' && activeClamped >= 0) {
      // Enter only acts when a suggestion is HIGHLIGHTED (a new state reachable only via the Arrow
      // keys), so free-text typing and existing import-review behaviour are unchanged.
      const r = results[activeClamped]
      if (r) {
        e.preventDefault()
        pick(r)
      }
    }
  }

  return (
    <div ref={wrapRef} className="relative">
      <input
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={showMenu}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={activeClamped >= 0 ? `${listId}-opt-${activeClamped}` : undefined}
        onChange={(e) => {
          onChange(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={onBlur}
        onKeyDown={onKeyDown}
        className="input mt-0.5 px-2 py-1 text-sm"
      />
      {showMenu && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-md border border-line bg-elevated shadow-lg"
        >
          {isFetching && results.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-faint">Searching…</div>
          ) : results.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-faint">
              No catalogue match — free text is saved as typed.
            </div>
          ) : (
            results.map((r, i) => (
              <button
                key={r.id}
                id={`${listId}-opt-${i}`}
                type="button"
                role="option"
                aria-selected={i === activeClamped}
                // When autosave-on-blur is active, keep focus on mousedown so the pick (onSelect)
                // runs WITHOUT the input first blurring + committing the partial free text.
                onMouseDown={onBlur ? (e) => e.preventDefault() : undefined}
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(r)}
                className={`block w-full cursor-pointer px-2 py-1.5 text-left text-sm hover:bg-surface ${
                  i === activeClamped ? 'bg-surface' : ''
                }`}
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
