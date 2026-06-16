// Dev/test-only reset tools — a gated "danger zone" on the Imports page.
// System-admin only; the backend additionally refuses these in production and
// requires an exact typed confirmation phrase. Two scoped actions only — there is
// deliberately NO "clear everything".

import { useState } from 'react'

import { useAuth } from '@/auth/AuthContext'
import { canUseDevReset } from '@/auth/permissions'
import { useClearImports, useClearLiveCrm, useResetCounts } from '@/hooks/useDevReset'
import { ApiError } from '@/lib/api'
import type { ResetCounts, ResetResult } from '@/lib/devReset'

type ActionKind = 'imports' | 'live-crm'

const ACTIONS: Record<
  ActionKind,
  { title: string; phrase: string; button: string; blurb: string; countsKey: 'imports' | 'live_crm' }
> = {
  imports: {
    title: 'Clear imports only',
    phrase: 'DELETE ALL IMPORTS',
    button: 'Clear imports…',
    blurb:
      'Hard-deletes ALL import batches, rows, and issues. Live customers, jobs, tasks, activities, and labels are NOT touched.',
    countsKey: 'imports',
  },
  'live-crm': {
    title: 'Clear live CRM data',
    phrase: 'DELETE ALL LIVE CRM DATA',
    button: 'Clear live CRM…',
    blurb:
      'Hard-deletes ALL customers, jobs, tasks, activities, label assignments, and documents. Committed import rows are DETACHED (their links are cleared) and returned to Approved so they can be re-committed — import batches/rows/issues are NOT deleted.',
    countsKey: 'live_crm',
  },
}

const COUNT_LABELS: Record<string, string> = {
  import_issues: 'Import issues',
  import_rows: 'Import rows',
  import_batches: 'Import batches',
  job_label_assignments: 'Job label assignments',
  activities: 'Activities',
  tasks: 'Tasks',
  documents: 'Documents',
  jobs: 'Jobs',
  customers: 'Customers',
  import_rows_detached: 'Committed import rows DETACHED (not deleted)',
}

function CountList({ counts }: { counts: Record<string, number> | undefined }) {
  if (!counts) return null
  return (
    <ul className="space-y-0.5 text-xs text-faint">
      {Object.entries(counts).map(([k, v]) => (
        <li key={k} className="flex justify-between gap-2">
          <span>{COUNT_LABELS[k] ?? k}</span>
          <span className="font-mono text-fg">{v}</span>
        </li>
      ))}
    </ul>
  )
}

export function DevResetPanel() {
  const { user } = useAuth()
  const isAdmin = canUseDevReset(user?.role.name)
  const { data: counts } = useResetCounts(isAdmin)
  const [open, setOpen] = useState<ActionKind | null>(null)

  if (!isAdmin) return null

  return (
    <section className="mt-10 rounded-lg border border-red-500/40 bg-red-500/[0.06] p-5">
      <h2 className="text-lg font-semibold text-red-300">⚠ Danger zone — dev reset</h2>
      <p className="mt-1 max-w-2xl text-sm text-red-200/80">
        Destructive, hard-delete testing tools (disabled in production). There is no
        “clear everything” — only these two scoped actions, each requiring an exact
        typed confirmation phrase.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {(['imports', 'live-crm'] as ActionKind[]).map((kind) => {
          const a = ACTIONS[kind]
          return (
            <div key={kind} className="flex flex-col rounded-md border border-red-500/30 bg-surface p-4">
              <h3 className="font-semibold text-fg">{a.title}</h3>
              <p className="mt-1 flex-1 text-xs text-muted">{a.blurb}</p>
              <div className="mt-3 border-t border-line pt-2">
                <CountList counts={counts?.[a.countsKey]} />
              </div>
              <button
                onClick={() => setOpen(kind)}
                className="mt-3 self-start rounded-md border border-red-500/50 bg-red-500/10 px-3 py-1.5 text-sm font-medium text-red-200 hover:bg-red-500/20"
              >
                {a.button}
              </button>
            </div>
          )
        })}
      </div>
      {open && <ResetConfirmModal kind={open} counts={counts} onClose={() => setOpen(null)} />}
    </section>
  )
}

function ResetConfirmModal({
  kind,
  counts,
  onClose,
}: {
  kind: ActionKind
  counts: ResetCounts | undefined
  onClose: () => void
}) {
  const a = ACTIONS[kind]
  const importsMut = useClearImports()
  const crmMut = useClearLiveCrm()
  const mut = kind === 'imports' ? importsMut : crmMut

  const [phrase, setPhrase] = useState('')
  const [result, setResult] = useState<ResetResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const matches = phrase === a.phrase

  async function run() {
    setError(null)
    try {
      setResult(await mut.mutateAsync(a.phrase))
    } catch (err) {
      setError(
        err instanceof ApiError && typeof err.detail === 'string' ? err.detail : 'Reset failed.',
      )
    }
  }

  return (
    <div
      className="fixed inset-0 z-30 flex items-center justify-center bg-black/70 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card flex max-h-[90vh] w-full max-w-md flex-col border-red-500/40 p-6">
        <h2 className="text-lg font-semibold text-red-300">⚠ {a.title}</h2>

        {result ? (
          <div className="mt-3 flex min-h-0 flex-col text-sm">
            <p className="font-medium text-emerald-300">Done — rows affected:</p>
            <div className="mt-2 overflow-y-auto rounded border border-line bg-elevated px-3 py-2">
              <CountList counts={result.deleted} />
            </div>
            <div className="mt-5 flex justify-end">
              <button onClick={onClose} className="btn-secondary">
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <p className="mt-2 text-sm text-red-200/80">{a.blurb}</p>
            <div className="mt-3 rounded border border-line bg-elevated px-3 py-2">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Will affect
              </p>
              <CountList counts={counts?.[a.countsKey]} />
            </div>
            {error && (
              <div className="mt-3 rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {error}
              </div>
            )}
            <label className="mt-4 block text-sm">
              <span className="mb-1 block text-faint">
                Type <span className="select-all font-mono font-semibold text-red-300">{a.phrase}</span>{' '}
                to confirm
              </span>
              <input
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                className="input"
                autoFocus
                placeholder={a.phrase}
              />
            </label>
            <div className="mt-5 flex justify-end gap-3">
              <button onClick={onClose} className="btn-secondary">
                Cancel
              </button>
              <button
                onClick={run}
                disabled={!matches || mut.isPending}
                className="rounded-md border border-red-500/60 bg-red-500/15 px-3 py-1.5 text-sm font-medium text-red-200 hover:bg-red-500/25 disabled:opacity-40"
              >
                {mut.isPending ? 'Working…' : 'Permanently delete'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
