// Create / edit a hardware catalogue entry (Settings > Hardware, admin-only — Stage 2B-2).
//
// One modal serves both create and edit. `spec_id` is the stable id: required on create,
// shown read-only on edit (the backend rejects changing it). Fields are category-aware —
// only the spec fields meaningful for the chosen category are shown, and the payload nulls
// the others so an entry stays clean for its type. No alias controls here (that is 2B-3).

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import { useCreateHardware, useUpdateHardware } from '@/hooks/useHardware'
import type {
  HardwareCatalogueEntry,
  HardwareCategory,
  HardwareCreateInput,
  HardwareUpdateInput,
} from '@/types'

interface HardwareFormModalProps {
  /** The entry to edit, or null to create a new one. */
  entry: HardwareCatalogueEntry | null
  onClose: () => void
  onSaved: () => void
}

const CATEGORIES: HardwareCategory[] = ['inverter', 'battery', 'panel', 'metering']

interface FormState {
  spec_id: string
  category: HardwareCategory
  canonical_model: string
  display_name: string
  brand: string
  phases: string
  nominal_kw: string
  capacity_kwh: string
  wattage_w: string
  model_options: string // one per line (or comma-separated)
}

function initialState(entry: HardwareCatalogueEntry | null): FormState {
  return {
    spec_id: entry?.spec_id ?? '',
    category: entry?.category ?? 'inverter',
    canonical_model: entry?.canonical_model ?? '',
    display_name: entry?.display_name ?? '',
    brand: entry?.brand ?? '',
    phases: entry?.phases ?? '',
    nominal_kw: entry?.nominal_kw != null ? String(entry.nominal_kw) : '',
    capacity_kwh: entry?.capacity_kwh != null ? String(entry.capacity_kwh) : '',
    wattage_w: entry?.wattage_w != null ? String(entry.wattage_w) : '',
    model_options: entry?.model_options?.join('\n') ?? '',
  }
}

// '' -> null (omit); a finite number -> value; anything else -> not ok (form error).
function parseOptionalNumber(v: string): { ok: true; value: number | null } | { ok: false } {
  const t = v.trim()
  if (t === '') return { ok: true, value: null }
  const n = Number(t)
  return Number.isFinite(n) ? { ok: true, value: n } : { ok: false }
}

export function HardwareFormModal({ entry, onClose, onSaved }: HardwareFormModalProps) {
  const isEdit = entry != null
  const [form, setForm] = useState<FormState>(() => initialState(entry))
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateHardware()
  const updateMutation = useUpdateHardware()
  const pending = createMutation.isPending || updateMutation.isPending

  function update<K extends keyof FormState>(field: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const cat = form.category

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    const text = (v: string): string | null => {
      const t = v.trim()
      return t === '' ? null : t
    }

    // Only the category-relevant numeric field carries a value; the rest are nulled so
    // an entry never holds cross-category data (e.g. a battery with a wattage).
    const nominal = parseOptionalNumber(cat === 'inverter' ? form.nominal_kw : '')
    const capacity = parseOptionalNumber(cat === 'battery' ? form.capacity_kwh : '')
    const wattage = parseOptionalNumber(cat === 'panel' ? form.wattage_w : '')
    if (!nominal.ok || !capacity.ok || !wattage.ok) {
      setError('Size must be a valid number.')
      return
    }

    const modelOptions =
      cat === 'panel'
        ? form.model_options
            .split(/[\n,]/)
            .map((s) => s.trim())
            .filter(Boolean)
        : []

    // Typed with category required so the create payload below stays well-typed (it is also
    // assignable to the all-optional HardwareUpdateInput the edit path needs).
    const base: Omit<HardwareCreateInput, 'spec_id'> = {
      category: cat,
      canonical_model: text(form.canonical_model),
      display_name: text(form.display_name),
      brand: text(form.brand),
      phases: cat === 'inverter' ? text(form.phases) : null,
      nominal_kw: nominal.value,
      capacity_kwh: capacity.value,
      wattage_w: wattage.value,
      model_options: modelOptions.length > 0 ? modelOptions : null,
    }

    try {
      if (isEdit) {
        // True partial PATCH: send ONLY fields whose intended value differs from the loaded
        // entry, so an edit never rewrites — or silently wipes — a field the user did not
        // change. (The backend's exclude_unset drops omitted keys but NOT explicit nulls, so
        // a blanket-null payload would clear untouched fields.) A category change still nulls
        // the now-invalid old-category fields, because those differ from the entry.
        const patch: HardwareUpdateInput = {}
        if (base.category !== entry.category) patch.category = base.category
        if (base.canonical_model !== entry.canonical_model) patch.canonical_model = base.canonical_model
        if (base.display_name !== entry.display_name) patch.display_name = base.display_name
        if (base.brand !== entry.brand) patch.brand = base.brand
        if (base.phases !== entry.phases) patch.phases = base.phases
        if (base.nominal_kw !== entry.nominal_kw) patch.nominal_kw = base.nominal_kw
        if (base.capacity_kwh !== entry.capacity_kwh) patch.capacity_kwh = base.capacity_kwh
        if (base.wattage_w !== entry.wattage_w) patch.wattage_w = base.wattage_w
        if (!sameOptions(base.model_options, entry.model_options)) {
          patch.model_options = base.model_options
        }
        await updateMutation.mutateAsync({ id: entry.id, input: patch })
      } else {
        const specId = form.spec_id.trim()
        if (!specId) {
          setError('Spec id is required.')
          return
        }
        const payload: HardwareCreateInput = { spec_id: specId, ...base }
        await createMutation.mutateAsync(payload)
      }
      onSaved()
    } catch (err) {
      setError(messageFor(err, isEdit))
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <form
        onSubmit={handleSubmit}
        className="card max-h-[90vh] w-full max-w-2xl overflow-y-auto p-6 shadow-2xl shadow-black/40"
      >
        <h2 className="mb-1 text-lg font-semibold text-fg">
          {isEdit ? 'Edit hardware' : 'New hardware'}
        </h2>
        <p className="mb-4 text-xs text-faint">
          Changes affect future parser matching only — existing Job hardware snapshots do
          not change.
        </p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Category *">
            <select
              value={form.category}
              onChange={(e) => update('category', e.target.value as HardwareCategory)}
              className="input"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {titleCase(c)}
                </option>
              ))}
            </select>
          </Field>

          <Field label={isEdit ? 'Spec id (immutable)' : 'Spec id *'}>
            <input
              required={!isEdit}
              value={form.spec_id}
              onChange={(e) => update('spec_id', e.target.value)}
              disabled={isEdit}
              placeholder="e.g. fronius_primo_5kw"
              className="input disabled:opacity-60"
            />
          </Field>

          <Field label="Canonical model">
            <input
              value={form.canonical_model}
              onChange={(e) => update('canonical_model', e.target.value)}
              className="input"
            />
          </Field>

          <Field label="Display name">
            <input
              value={form.display_name}
              onChange={(e) => update('display_name', e.target.value)}
              className="input"
            />
          </Field>

          <Field label="Brand / manufacturer">
            <input
              value={form.brand}
              onChange={(e) => update('brand', e.target.value)}
              className="input"
            />
          </Field>

          {cat === 'inverter' && (
            <>
              <Field label="Phase">
                <input
                  value={form.phases}
                  onChange={(e) => update('phases', e.target.value)}
                  placeholder="e.g. three_phase"
                  className="input"
                />
              </Field>
              <Field label="Nominal size (kW)">
                <input
                  type="number"
                  step="any"
                  value={form.nominal_kw}
                  onChange={(e) => update('nominal_kw', e.target.value)}
                  className="input"
                />
              </Field>
            </>
          )}

          {cat === 'battery' && (
            <Field label="Capacity (kWh)">
              <input
                type="number"
                step="any"
                value={form.capacity_kwh}
                onChange={(e) => update('capacity_kwh', e.target.value)}
                className="input"
              />
            </Field>
          )}

          {cat === 'panel' && (
            <>
              <Field label="Wattage (W)">
                <input
                  type="number"
                  step="1"
                  value={form.wattage_w}
                  onChange={(e) => update('wattage_w', e.target.value)}
                  className="input"
                />
              </Field>
              <Field label="Model options (one per line)" className="sm:col-span-2">
                <textarea
                  value={form.model_options}
                  onChange={(e) => update('model_options', e.target.value)}
                  rows={3}
                  placeholder={'For ambiguous panels — one model per line'}
                  className="input"
                />
              </Field>
            </>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button type="submit" disabled={pending} className="btn-primary">
            {pending ? 'Saving…' : isEdit ? 'Save changes' : 'Create hardware'}
          </button>
        </div>
      </form>
    </div>
  )
}

function messageFor(err: unknown, isEdit: boolean): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return 'That spec id already exists. Choose a unique spec id.'
    }
    if (err.status === 400) {
      return 'Spec id is required.'
    }
    if (err.status === 403) {
      return 'You do not have permission to manage hardware.'
    }
    if (err.status === 404) {
      return 'That hardware entry no longer exists. Refresh and try again.'
    }
    if (err.status === 422) {
      return 'Please check the form — one of the values is invalid.'
    }
  }
  return isEdit
    ? 'Could not save changes. Please try again.'
    : 'Could not create the hardware. Please try again.'
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

// Order-sensitive equality for the panel model_options list (null/undefined == empty).
function sameOptions(a: string[] | null | undefined, b: string[] | null): boolean {
  const aa = a ?? []
  const bb = b ?? []
  if (aa.length !== bb.length) return false
  return aa.every((v, i) => v === bb[i])
}

function Field({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <label className={`block text-sm ${className ?? ''}`}>
      <span className="mb-1 block font-medium text-fg">{label}</span>
      {children}
    </label>
  )
}
