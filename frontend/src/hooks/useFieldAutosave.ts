// Field-level autosave state machine (Job Detail H5 overhaul, H5A foundation).
//
// One instance per editable field. The textbox text is the source of truth: the user types into a
// local `draft`, and the change is persisted when they finish interacting (blur for text, change for
// date/select) — never on every keystroke and never via a global Save button. A background refetch /
// window-focus refetch can NEVER clobber an in-progress edit (the draft is only re-synced from the
// server while the field is idle/saved). On save failure the typed value is RETAINED and a retry is
// offered, so nothing the user typed is ever silently lost.

import { useCallback, useEffect, useRef, useState } from 'react'

export type AutosaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

/** A server value may be adopted into the local draft ONLY when the field is not mid-edit, in
 *  flight, or errored — so a refetch never overwrites a dirty/saving/failed draft. (Pure; testable.) */
export function canAdoptServerValue(status: AutosaveStatus): boolean {
  return status === 'idle' || status === 'saved'
}

export interface FieldAutosave {
  draft: string
  status: AutosaveStatus
  error: string | null
  /** onChange — update the draft and mark dirty (idle if typed back to the saved value). No save. */
  onChange: (value: string) => void
  /** Commit (blur for text; immediately for date/select). Saves only if changed vs the last-saved
   *  value; pass an explicit value when the new value isn't in the draft state yet (e.g. date change). */
  commit: (explicit?: string) => void
  /** Re-attempt the last failed save with the current draft. */
  retry: () => void
}

export function useFieldAutosave(
  serverValue: string,
  save: (value: string) => Promise<void>,
  describeError?: (err: unknown) => string,
): FieldAutosave {
  const [draft, setDraft] = useState(serverValue)
  const [status, setStatus] = useState<AutosaveStatus>('idle')
  const [error, setError] = useState<string | null>(null)

  // Refs so handlers never read stale closures and the reconcile effect can branch on live status.
  const baselineRef = useRef(serverValue) // last value known-saved on the server
  const draftRef = useRef(draft)
  const statusRef = useRef(status)
  const saveRef = useRef(save)
  const describeRef = useRef(describeError)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  draftRef.current = draft
  statusRef.current = status
  saveRef.current = save
  describeRef.current = describeError

  // Reconcile the incoming server value into the draft — but ONLY when safe (no in-flight/dirty/error
  // edit to lose). This per-field guard replaces a global form-reset on refetch.
  useEffect(() => {
    baselineRef.current = serverValue
    if (canAdoptServerValue(statusRef.current)) setDraft(serverValue)
  }, [serverValue])

  useEffect(
    () => () => {
      if (savedTimer.current) clearTimeout(savedTimer.current)
    },
    [],
  )

  const doSave = useCallback(async (value: string) => {
    if (savedTimer.current) {
      clearTimeout(savedTimer.current)
      savedTimer.current = null
    }
    setStatus('saving')
    setError(null)
    try {
      await saveRef.current(value)
      baselineRef.current = value
      setStatus('saved')
      savedTimer.current = setTimeout(() => setStatus('idle'), 2000)
    } catch (err) {
      setError(describeRef.current?.(err) ?? 'Could not save.')
      setStatus('error') // draft is retained — the typed value is never lost
    }
  }, [])

  const onChange = useCallback((value: string) => {
    setDraft(value)
    setError(null)
    setStatus(value === baselineRef.current ? 'idle' : 'dirty')
  }, [])

  const commit = useCallback(
    (explicit?: string) => {
      const value = explicit ?? draftRef.current
      if (value === baselineRef.current) {
        setStatus('idle') // no-op: nothing changed since the last save
        return
      }
      void doSave(value)
    },
    [doSave],
  )

  const retry = useCallback(() => {
    void doSave(draftRef.current)
  }, [doSave])

  return { draft, status, error, onChange, commit, retry }
}
