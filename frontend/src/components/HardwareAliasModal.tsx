// Manage the parser aliases of one hardware catalogue item (Settings > Hardware, admin-only —
// Stage 2B-3). Lists the item's aliases (active + deleted), with an inline add/edit form and
// per-alias soft-delete / restore. Alias types are exactly exact / loose / case_sensitive;
// source_examples are NOT aliases and never appear here.
//
// Removing an alias affects FUTURE parser matching only — it never mutates existing Job
// hardware snapshots (the catalogue has no link to/from Jobs). All alias routes are admin-only
// server-side; this surface is only reachable from the admin-gated Settings > Hardware screen.

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError } from '@/lib/api'
import {
  useCreateAlias,
  useDeleteAlias,
  useHardwareAliases,
  useRestoreAlias,
  useUpdateAlias,
} from '@/hooks/useHardware'
import type {
  HardwareAlias,
  HardwareAliasType,
  HardwareCatalogueEntry,
  HardwareDeletedMode,
} from '@/types'

interface HardwareAliasModalProps {
  hardware: HardwareCatalogueEntry
  onClose: () => void
}

const ALIAS_TYPES: HardwareAliasType[] = ['exact', 'loose', 'case_sensitive']

const SHOW_OPTIONS: { value: HardwareDeletedMode; label: string }[] = [
  { value: 'include', label: 'All' },
  { value: 'exclude', label: 'Active' },
  { value: 'only', label: 'Deleted' },
]

function hardwareName(h: HardwareCatalogueEntry): string {
  return h.display_name || h.canonical_model || h.spec_id
}

export function HardwareAliasModal({ hardware, onClose }: HardwareAliasModalProps) {
  const [show, setShow] = useState<HardwareDeletedMode>('include')
  const [formOpen, setFormOpen] = useState(false)
  const [editAlias, setEditAlias] = useState<HardwareAlias | null>(null)
  const [aliasValue, setAliasValue] = useState('')
  const [aliasType, setAliasType] = useState<HardwareAliasType>('exact')
  const [confidence, setConfidence] = useState('')
  const [decisionLog, setDecisionLog] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const aliasesQuery = useHardwareAliases(hardware.id, show)
  const createMutation = useCreateAlias(hardware.id)
  const updateMutation = useUpdateAlias(hardware.id)
  const deleteMutation = useDeleteAlias(hardware.id)
  const restoreMutation = useRestoreAlias(hardware.id)
  const formPending = createMutation.isPending || updateMutation.isPending
  const actionPending = deleteMutation.isPending || restoreMutation.isPending

  const aliases = aliasesQuery.data?.items ?? []

  function resetForm() {
    setAliasValue('')
    setAliasType('exact')
    setConfidence('')
    setDecisionLog('')
  }

  function openAdd() {
    setActionError(null)
    setFormError(null)
    setEditAlias(null)
    resetForm()
    setFormOpen(true)
  }

  function openEdit(a: HardwareAlias) {
    setActionError(null)
    setFormError(null)
    setEditAlias(a)
    setAliasValue(a.alias)
    setAliasType(a.alias_type)
    setConfidence(a.confidence_override ?? '')
    setDecisionLog(a.decision_log_id ?? '')
    setFormOpen(true)
  }

  function closeForm() {
    setFormOpen(false)
    setEditAlias(null)
    resetForm()
    setFormError(null)
  }

  async function submitForm(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    const alias = aliasValue.trim()
    if (!alias) {
      setFormError('Alias is required.')
      return
    }
    const input = {
      alias,
      alias_type: aliasType,
      confidence_override: confidence.trim() || null,
      decision_log_id: decisionLog.trim() || null,
    }
    try {
      if (editAlias) {
        await updateMutation.mutateAsync({ aliasId: editAlias.id, input })
      } else {
        await createMutation.mutateAsync(input)
      }
      closeForm()
    } catch (err) {
      setFormError(aliasMessage(err))
    }
  }

  async function handleDelete(a: HardwareAlias) {
    setActionError(null)
    if (
      !window.confirm(
        `Soft-delete alias “${a.alias}”? It can be restored. Removing it affects future parser ` +
          'matching only — existing Job hardware snapshots are unchanged.',
      )
    ) {
      return
    }
    try {
      await deleteMutation.mutateAsync(a.id)
    } catch (err) {
      setActionError(aliasMessage(err))
    }
  }

  async function handleRestore(a: HardwareAlias) {
    setActionError(null)
    try {
      await restoreMutation.mutateAsync(a.id)
    } catch (err) {
      setActionError(aliasMessage(err))
    }
  }

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card max-h-[90vh] w-full max-w-3xl overflow-y-auto p-6 shadow-2xl shadow-black/40">
        <div className="mb-1 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-fg">Aliases</h2>
            <p className="text-sm text-muted">
              {hardwareName(hardware)}{' '}
              <span className="text-faint">· {hardware.spec_id}</span>
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn-secondary text-sm">
            Close
          </button>
        </div>
        <p className="mb-4 max-w-2xl text-xs text-faint">
          Removing an alias affects future parser matching only — existing Job hardware
          snapshots do not change.
        </p>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm text-muted">
            Show
            <select
              value={show}
              onChange={(e) => setShow(e.target.value as HardwareDeletedMode)}
              className="input w-auto"
            >
              {SHOW_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {!formOpen && (
            <button onClick={openAdd} className="btn-primary text-sm">
              Add alias
            </button>
          )}
        </div>

        {formOpen && (
          <form
            onSubmit={submitForm}
            className="mb-4 rounded-md border border-line bg-elevated/40 p-4"
          >
            <h3 className="mb-3 text-sm font-semibold text-fg">
              {editAlias ? 'Edit alias' : 'Add alias'}
            </h3>
            {formError && (
              <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {formError}
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field label="Alias *">
                <input
                  required
                  value={aliasValue}
                  onChange={(e) => setAliasValue(e.target.value)}
                  className="input"
                />
              </Field>
              <Field label="Type *">
                <select
                  value={aliasType}
                  onChange={(e) => setAliasType(e.target.value as HardwareAliasType)}
                  className="input"
                >
                  {ALIAS_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {labelType(t)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Confidence override">
                <input
                  value={confidence}
                  onChange={(e) => setConfidence(e.target.value)}
                  placeholder="optional"
                  className="input"
                />
              </Field>
              <Field label="Decision log id">
                <input
                  value={decisionLog}
                  onChange={(e) => setDecisionLog(e.target.value)}
                  placeholder="optional"
                  className="input"
                />
              </Field>
            </div>
            <div className="mt-4 flex justify-end gap-3">
              <button type="button" onClick={closeForm} className="btn-secondary text-sm">
                Cancel
              </button>
              <button type="submit" disabled={formPending} className="btn-primary text-sm">
                {formPending ? 'Saving…' : editAlias ? 'Save alias' : 'Add alias'}
              </button>
            </div>
          </form>
        )}

        {actionError && (
          <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {actionError}
          </div>
        )}

        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-line bg-elevated text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Alias</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Confidence</th>
                <th className="px-3 py-2 font-medium">Decision log</th>
                <th className="px-3 py-2 font-medium">State</th>
                <th className="px-3 py-2 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {aliasesQuery.isLoading ? (
                <RowMessage>Loading aliases…</RowMessage>
              ) : aliasesQuery.isError ? (
                <RowMessage className="text-red-400">Failed to load aliases.</RowMessage>
              ) : aliases.length === 0 ? (
                <RowMessage>No aliases{show === 'only' ? ' deleted' : ''} yet.</RowMessage>
              ) : (
                aliases.map((a) => (
                  <tr key={a.id} className="border-b border-line/60 last:border-0">
                    <td className="px-3 py-2 font-medium text-fg">{a.alias}</td>
                    <td className="px-3 py-2 text-muted">{labelType(a.alias_type)}</td>
                    <td className="px-3 py-2 text-muted">{a.confidence_override ?? '—'}</td>
                    <td className="px-3 py-2 text-muted">{a.decision_log_id ?? '—'}</td>
                    <td className="px-3 py-2">
                      <StateBadge deleted={a.deleted_at != null} />
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex justify-end gap-3">
                        {a.deleted_at == null ? (
                          <>
                            <button
                              onClick={() => openEdit(a)}
                              disabled={actionPending}
                              className="text-xs font-medium text-brand-400 hover:text-brand-300 disabled:opacity-50"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDelete(a)}
                              disabled={actionPending}
                              className="text-xs font-medium text-red-300 hover:text-red-200 disabled:opacity-50"
                            >
                              Delete
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => handleRestore(a)}
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
      </div>
    </div>
  )
}

function aliasMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return 'An alias with that value and type already exists for this hardware.'
    }
    if (err.status === 400) return 'Alias is required.'
    if (err.status === 403) return 'You do not have permission to manage aliases.'
    if (err.status === 404) return 'That alias no longer exists. Refresh and try again.'
    if (err.status === 422) return 'Please check the form — one of the values is invalid.'
  }
  return 'Could not save the alias. Please try again.'
}

// "case_sensitive" -> "Case sensitive"
function labelType(t: string): string {
  const s = t.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
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

function StateBadge({ deleted }: { deleted: boolean }) {
  return deleted ? (
    <span className="rounded bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-300">
      Deleted
    </span>
  ) : (
    <span className="rounded bg-elevated px-2 py-0.5 text-xs font-medium text-muted">Active</span>
  )
}

function RowMessage({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <tr>
      <td colSpan={6} className={`px-3 py-6 text-center text-muted ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}
