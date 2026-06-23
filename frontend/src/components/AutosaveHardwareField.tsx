// Autosave variant of a Job Detail hardware System field (Panel / Inverter / Battery / Metering),
// Hardware Parser lane H5C. Combines `useFieldAutosave` (per-field draft + no-clobber + retain-on-
// error) with the `HardwareSearchInput` autocomplete:
//   • typing free text invalidates any prior catalogue pick (so a stale canonical id is never kept)
//     and saves on BLUR;
//   • clicking a catalogue suggestion saves IMMEDIATELY, stamping provenance
//     (canonical_hardware_id_at_parse_time + confidence=manual_correction).
// The actual one-subsection PATCH is the injected `onSave(value, selection)` (see JobDetailPage).

import { useRef } from 'react'
import { AutosaveStatusChip, describeSaveError } from '@/components/AutosaveControl'
import { HardwareSearchInput } from '@/components/HardwareSearchInput'
import { useFieldAutosave } from '@/hooks/useFieldAutosave'
import type { HardwareSelection, SystemHardwareField } from '@/lib/hardwareDisplay'
import type { HardwareSearchResult } from '@/types'

export function AutosaveHardwareField({
  field,
  onSave,
}: {
  field: SystemHardwareField
  onSave: (value: string, selection: HardwareSelection | undefined) => Promise<void>
}) {
  // The catalogue pick (if any) for the value currently being committed. Held in a ref so the save
  // closure always reads the latest: typing clears it (free text), a pick sets it (stamps provenance).
  const selectionRef = useRef<HardwareSelection | undefined>(undefined)
  const fa = useFieldAutosave(field.value, (v) => onSave(v, selectionRef.current), describeSaveError)

  function onText(text: string) {
    selectionRef.current = undefined // free text drops stale catalogue provenance
    fa.onChange(text)
  }
  function onPick(result: HardwareSearchResult, filledText: string) {
    selectionRef.current = {
      id: result.id,
      confidence: 'manual_correction',
      model: result.canonical_model ?? null,
    }
    // Force-commit: a selection persists even if the visible text is unchanged (provenance changed).
    fa.commit(filledText, { force: true })
  }

  return (
    <div className="flex flex-col">
      <HardwareSearchInput
        value={fa.draft}
        category={field.category}
        onChange={onText}
        onSelect={onPick}
        onBlur={() => fa.commit()}
      />
      <AutosaveStatusChip status={fa.status} error={fa.error} onRetry={fa.retry} />
    </div>
  )
}
