// Settings > Hardware (admin-only) — Stage 2B-1: read-only catalogue list.
//
// Surfaces the Stage-2A hardware catalogue in the app: debounced search, filters by
// category / brand / phase / category-aware size, an Active / Deleted / All view, a
// scannable table (name, category, brand, phase, size, alias count, state), and
// pagination. No create/edit/delete/restore or alias controls yet — those are 2B-2 /
// 2B-3. Every hardware route is admin-only server-side; the route is also admin-gated.

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useHardwareList } from '@/hooks/useHardware'
import type {
  HardwareCatalogueEntry,
  HardwareCategory,
  HardwareDeletedMode,
} from '@/types'

const PAGE_SIZE = 25
// The whole catalogue (~167 rows today) fits under the backend's max page size, so a
// single facet query yields every brand/phase option. Revisit if the catalogue ever
// grows past FACET_LIMIT (options would then reflect only the first page).
const FACET_LIMIT = 200

const CATEGORIES: HardwareCategory[] = ['inverter', 'battery', 'panel', 'metering']

const DELETED_OPTIONS: { value: HardwareDeletedMode; label: string }[] = [
  { value: 'exclude', label: 'Active' },
  { value: 'only', label: 'Deleted' },
  { value: 'include', label: 'All' },
]

// Which numeric field a category's "size" filter maps to (metering has no size).
function sizeFieldFor(
  category: HardwareCategory | '',
): { key: 'nominal_kw' | 'capacity_kwh' | 'wattage_w'; unit: string } | null {
  if (category === 'inverter') return { key: 'nominal_kw', unit: 'kW' }
  if (category === 'battery') return { key: 'capacity_kwh', unit: 'kWh' }
  if (category === 'panel') return { key: 'wattage_w', unit: 'W' }
  return null
}

function hardwareName(h: HardwareCatalogueEntry): string {
  return h.display_name || h.canonical_model || h.spec_id
}

function hardwareSize(h: HardwareCatalogueEntry): string {
  if (h.nominal_kw != null) return `${h.nominal_kw} kW`
  if (h.capacity_kwh != null) return `${h.capacity_kwh} kWh`
  if (h.wattage_w != null) return `${h.wattage_w} W`
  return '—'
}

export function SettingsHardwarePage() {
  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<HardwareCategory | ''>('')
  const [brand, setBrand] = useState('')
  const [phase, setPhase] = useState('')
  const [size, setSize] = useState('')
  const [deleted, setDeleted] = useState<HardwareDeletedMode>('exclude')
  const [offset, setOffset] = useState(0)

  // Debounce the search box; reset to the first page on a new query.
  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const sizeField = sizeFieldFor(category)
  const sizeTrimmed = size.trim()
  const sizeNum = sizeTrimmed === '' ? undefined : Number(sizeTrimmed)
  const sizeVal =
    sizeField && sizeNum != null && Number.isFinite(sizeNum) ? sizeNum : undefined

  const { data, isLoading, isError, isFetching } = useHardwareList({
    q: q || undefined,
    category: category || undefined,
    brand: brand || undefined,
    phase: phase || undefined,
    nominal_kw: sizeField?.key === 'nominal_kw' ? sizeVal : undefined,
    capacity_kwh: sizeField?.key === 'capacity_kwh' ? sizeVal : undefined,
    wattage_w: sizeField?.key === 'wattage_w' ? sizeVal : undefined,
    deleted,
    limit: PAGE_SIZE,
    offset,
  })

  // Brand + phase dropdown options, derived from the catalogue under the current
  // category + deleted scope only (so choosing a brand never hides the other brands).
  const facets = useHardwareList({
    category: category || undefined,
    deleted,
    limit: FACET_LIMIT,
  })
  const brandOptions = useMemo(
    () => uniqueSorted((facets.data?.items ?? []).map((h) => h.brand)),
    [facets.data],
  )
  const phaseOptions = useMemo(
    () => uniqueSorted((facets.data?.items ?? []).map((h) => h.phases)),
    [facets.data],
  )

  const total = data?.total ?? 0
  const items = data?.items ?? []
  const pageInfo = useMemo(() => {
    if (total === 0) return '0 hardware items'
    const start = offset + 1
    const end = Math.min(offset + PAGE_SIZE, total)
    return `${start}–${end} of ${total}`
  }, [offset, total])

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-fg">Hardware catalogue</h2>
        <span className="rounded bg-elevated px-2 py-0.5 text-xs uppercase tracking-wide text-faint">
          Admin only
        </span>
      </div>
      <p className="mb-4 max-w-3xl text-sm text-muted">
        Catalogue and alias changes affect future parser matching only. Existing Job
        hardware snapshots do not change.
      </p>

      <input
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Search model, name, brand, spec id…"
        className="input mb-3"
      />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Field label="Category">
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value as HardwareCategory | '')
              setBrand('')
              setPhase('')
              setSize('')
              setOffset(0)
            }}
            className="input"
          >
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {titleCase(c)}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Brand">
          <select
            value={brand}
            onChange={(e) => {
              setBrand(e.target.value)
              setOffset(0)
            }}
            className="input"
          >
            <option value="">All brands</option>
            {brandOptions.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Phase">
          <select
            value={phase}
            onChange={(e) => {
              setPhase(e.target.value)
              setOffset(0)
            }}
            className="input"
          >
            <option value="">Any phase</option>
            {phaseOptions.map((p) => (
              <option key={p} value={p}>
                {labelPhase(p)}
              </option>
            ))}
          </select>
        </Field>

        <Field label={sizeField ? `Size (${sizeField.unit})` : 'Size'}>
          <input
            type="number"
            value={size}
            onChange={(e) => {
              setSize(e.target.value)
              setOffset(0)
            }}
            placeholder={sizeField ? 'e.g. 5' : 'Pick a category'}
            className="input"
            disabled={!sizeField}
          />
        </Field>

        <Field label="Show">
          <select
            value={deleted}
            onChange={(e) => {
              setDeleted(e.target.value as HardwareDeletedMode)
              setOffset(0)
            }}
            className="input"
          >
            {DELETED_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[48rem] text-left text-sm">
          <thead className="border-b border-line bg-elevated text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Category</th>
              <th className="px-4 py-2 font-medium">Brand</th>
              <th className="px-4 py-2 font-medium">Phase</th>
              <th className="px-4 py-2 font-medium">Size</th>
              <th className="px-4 py-2 font-medium">Aliases</th>
              <th className="px-4 py-2 font-medium">State</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <RowMessage>Loading hardware…</RowMessage>
            ) : isError ? (
              <RowMessage className="text-red-400">Failed to load hardware.</RowMessage>
            ) : items.length === 0 ? (
              <RowMessage>No hardware matches these filters.</RowMessage>
            ) : (
              items.map((h) => (
                <tr key={h.id} className="border-b border-line/60 last:border-0">
                  <td className="px-4 py-2 font-medium text-fg">
                    {hardwareName(h)}
                    {h.canonical_model &&
                      h.display_name &&
                      h.canonical_model !== h.display_name && (
                        <span className="ml-2 text-xs text-faint">{h.canonical_model}</span>
                      )}
                  </td>
                  <td className="px-4 py-2 text-muted">{titleCase(h.category)}</td>
                  <td className="px-4 py-2 text-muted">{h.brand ?? '—'}</td>
                  <td className="px-4 py-2 text-muted">
                    {h.phases ? labelPhase(h.phases) : '—'}
                  </td>
                  <td className="px-4 py-2 text-muted">{hardwareSize(h)}</td>
                  <td className="px-4 py-2 text-muted">{h.alias_count}</td>
                  <td className="px-4 py-2">
                    <StateBadge deleted={h.deleted_at != null} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-sm text-muted">
        <span>
          {pageInfo}
          {isFetching && !isLoading ? ' · updating…' : ''}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md border border-line-strong px-3 py-1 text-fg hover:bg-elevated disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="eyebrow mb-1 block">{label}</span>
      {children}
    </label>
  )
}

function RowMessage({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <tr>
      <td colSpan={7} className={`px-4 py-8 text-center text-muted ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}

function StateBadge({ deleted }: { deleted: boolean }) {
  return deleted ? (
    <span className="rounded bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-300">
      Deleted
    </span>
  ) : (
    <span className="rounded bg-elevated px-2 py-0.5 text-xs font-medium text-muted">
      Active
    </span>
  )
}

function uniqueSorted(values: (string | null)[]): string[] {
  return Array.from(new Set(values.filter((v): v is string => !!v))).sort((a, b) =>
    a.localeCompare(b),
  )
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// "single_phase" -> "Single phase"
function labelPhase(p: string): string {
  const t = p.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}
