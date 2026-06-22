// Settings > Hardware (admin-only) — catalogue browser + write actions.
//
// 2B-1 added the read view (debounced search, filters by category / brand / phase /
// category-aware size, an Active / Deleted / All view, a scannable table, pagination).
// 2B-2 adds the catalogue WRITE actions: a New hardware button, per-row Edit + Delete
// (active rows) / Restore (deleted rows), and the shared HardwareFormModal. Delete is a
// recoverable soft-delete (window.confirm); restore is explicit. 2B-3 adds a per-row
// Aliases action (active rows) opening HardwareAliasModal for that item. Every hardware
// route is admin-only server-side; the route is also admin-gated.

import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { HardwareFormModal } from '@/components/HardwareFormModal'
import { HardwareAliasModal } from '@/components/HardwareAliasModal'
import {
  useDeleteHardware,
  useHardwareList,
  useRestoreHardware,
} from '@/hooks/useHardware'
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

  // Create/edit modal: open with a null entry to create, or an entry to edit.
  const [formOpen, setFormOpen] = useState(false)
  const [formEntry, setFormEntry] = useState<HardwareCatalogueEntry | null>(null)
  // Alias-management modal: the hardware item whose aliases are open (null = closed).
  const [aliasHardware, setAliasHardware] = useState<HardwareCatalogueEntry | null>(null)
  // Inline banner for row-action (delete/restore) failures.
  const [actionError, setActionError] = useState<string | null>(null)

  const deleteMutation = useDeleteHardware()
  const restoreMutation = useRestoreHardware()
  const actionPending = deleteMutation.isPending || restoreMutation.isPending

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

  function openCreate() {
    setActionError(null)
    setFormEntry(null)
    setFormOpen(true)
  }

  function openEdit(h: HardwareCatalogueEntry) {
    setActionError(null)
    setFormEntry(h)
    setFormOpen(true)
  }

  async function handleDelete(h: HardwareCatalogueEntry) {
    setActionError(null)
    const name = hardwareName(h)
    if (
      !window.confirm(
        `Soft-delete “${name}”? It moves to the Deleted view and can be restored. ` +
          'Existing Job hardware snapshots are not affected.',
      )
    ) {
      return
    }
    try {
      await deleteMutation.mutateAsync(h.id)
    } catch (err) {
      setActionError(actionMessage(err, 'delete'))
    }
  }

  async function handleRestore(h: HardwareCatalogueEntry) {
    setActionError(null)
    try {
      await restoreMutation.mutateAsync(h.id)
    } catch (err) {
      setActionError(actionMessage(err, 'restore'))
    }
  }

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-fg">Hardware catalogue</h2>
        <div className="flex items-center gap-3">
          <span className="rounded bg-elevated px-2 py-0.5 text-xs uppercase tracking-wide text-faint">
            Admin only
          </span>
          <button onClick={openCreate} className="btn-primary text-sm">
            New hardware
          </button>
        </div>
      </div>
      <p className="mb-4 max-w-3xl text-sm text-muted">
        Catalogue and alias changes affect future parser matching only. Existing Job
        hardware snapshots do not change.
      </p>

      {actionError && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {actionError}
        </div>
      )}

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
              <th className="px-4 py-2 text-right font-medium">Actions</th>
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
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-3">
                      {h.deleted_at == null ? (
                        <>
                          <button
                            onClick={() => openEdit(h)}
                            disabled={actionPending}
                            className="text-xs font-medium text-brand-400 hover:text-brand-300 disabled:opacity-50"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => {
                              setActionError(null)
                              setAliasHardware(h)
                            }}
                            className="text-xs font-medium text-muted hover:text-fg"
                          >
                            Aliases
                          </button>
                          <button
                            onClick={() => handleDelete(h)}
                            disabled={actionPending}
                            className="text-xs font-medium text-red-300 hover:text-red-200 disabled:opacity-50"
                          >
                            Delete
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => handleRestore(h)}
                          disabled={actionPending}
                          className="text-xs font-medium text-brand-400 hover:text-brand-300 disabled:opacity-50"
                        >
                          Restore
                        </button>
                      )}
                    </div>
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

      {formOpen && (
        <HardwareFormModal
          entry={formEntry}
          onClose={() => setFormOpen(false)}
          onSaved={() => setFormOpen(false)}
        />
      )}

      {aliasHardware && (
        <HardwareAliasModal
          hardware={aliasHardware}
          onClose={() => setAliasHardware(null)}
        />
      )}
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
      <td colSpan={8} className={`px-4 py-8 text-center text-muted ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}

function actionMessage(err: unknown, action: 'delete' | 'restore'): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return 'You do not have permission to manage hardware.'
    if (err.status === 404) return 'That hardware entry no longer exists. Refresh and try again.'
  }
  return action === 'delete'
    ? 'Could not delete that hardware. Please try again.'
    : 'Could not restore that hardware. Please try again.'
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
