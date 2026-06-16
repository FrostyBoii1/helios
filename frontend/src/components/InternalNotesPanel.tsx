import { useEffect, useState } from 'react'

interface InternalNotesPanelProps {
  /** Heading, e.g. "Customer internal notes" / "Job internal notes". */
  title: string
  /** Current saved value (null when empty). */
  value: string | null
  /** Whether the current user may edit. Read-only viewers still SEE the text. */
  canWrite: boolean
  /** True while a save is in flight (drives the button label). */
  saving?: boolean
  /** Persist the text. Resolves on success, rejects on failure. */
  onSave: (text: string) => Promise<void>
}

/**
 * A tall, always-visible manual-notes panel — a shared staff scratchpad
 * (lightweight Google-Doc feel) for operational communication. Note: Job internal
 * notes may be seeded from preserved import context on commit, then freely edited,
 * so this is NOT claimed to be free of imported text.
 *
 * Visible in read mode (the textarea always shows the saved text); editable +
 * savable when the user has write permission. A background refetch never
 * clobbers in-progress typing (the external value only syncs into the draft
 * while the field is not dirty).
 */
export function InternalNotesPanel({ title, value, canWrite, saving = false, onSave }: InternalNotesPanelProps) {
  const [draft, setDraft] = useState(value ?? '')
  const [dirty, setDirty] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Sync the saved value into the draft only when the user is not mid-edit.
  useEffect(() => {
    if (!dirty) setDraft(value ?? '')
  }, [value, dirty])

  async function handleSave() {
    setError(null)
    try {
      await onSave(draft)
      setDirty(false)
      setJustSaved(true)
      window.setTimeout(() => setJustSaved(false), 2000)
    } catch {
      setError('Could not save notes.')
    }
  }

  return (
    <div className="flex flex-col rounded-lg border border-line bg-surface p-4">
      <div className="mb-1 flex items-center justify-between">
        <h2 className="eyebrow">{title}</h2>
        {dirty ? (
          <span className="text-xs text-faint">Unsaved</span>
        ) : justSaved ? (
          <span className="text-xs text-emerald-400">Saved ✓</span>
        ) : null}
      </div>
      <p className="mb-2 text-xs text-faint">Shared staff notes — operational communication for the team.</p>
      <textarea
        value={draft}
        readOnly={!canWrite}
        onChange={(e) => {
          setDraft(e.target.value)
          setDirty(true)
          setJustSaved(false)
        }}
        placeholder={canWrite ? 'Add notes for the team…' : 'No notes yet.'}
        className="input min-h-[60vh] flex-1 resize-none px-3 py-2 text-sm leading-relaxed"
      />
      {error && <p className="mt-2 text-xs text-red-300">{error}</p>}
      {canWrite && (
        <div className="mt-3 flex items-center justify-end gap-3">
          {dirty && (
            <button
              onClick={() => {
                setDraft(value ?? '')
                setDirty(false)
                setError(null)
              }}
              className="text-sm text-muted underline hover:text-fg"
            >
              Discard
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="btn-primary px-4 py-1.5 text-sm disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save notes'}
          </button>
        </div>
      )}
    </div>
  )
}
