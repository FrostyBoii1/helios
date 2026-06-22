// TanStack Query hooks for the hardware catalogue (Settings > Hardware, admin-only).
// Stage 2B-1: read-only list. Stage 2B-2: catalogue create / edit / soft-delete /
// restore mutations (each invalidates the whole `hardware` key so the list AND the
// facet dropdowns refetch). Alias mutations are still Stage 2B-3.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createHardware,
  deleteHardware,
  listHardware,
  restoreHardware,
  updateHardware,
  type ListHardwareParams,
} from '@/lib/hardware'
import type { HardwareCreateInput, HardwareUpdateInput } from '@/types'

const keys = {
  all: ['hardware'] as const,
  list: (params: ListHardwareParams) => ['hardware', 'list', params] as const,
}

export function useHardwareList(params: ListHardwareParams, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: keys.list(params),
    queryFn: () => listHardware(params),
    enabled: options?.enabled ?? true,
  })
}

export function useCreateHardware() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: HardwareCreateInput) => createHardware(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useUpdateHardware() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: HardwareUpdateInput }) =>
      updateHardware(id, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useDeleteHardware() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteHardware(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useRestoreHardware() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => restoreHardware(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}
