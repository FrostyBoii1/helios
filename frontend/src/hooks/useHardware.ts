// TanStack Query hooks for the hardware catalogue (Settings > Hardware, admin-only).
// Stage 2B-1: read-only list. Stage 2B-2: catalogue create / edit / soft-delete /
// restore mutations. Stage 2B-3: nested alias list + create / edit / soft-delete /
// restore. Every mutation invalidates the whole `hardware` key, which prefix-matches the
// catalogue list, the facet dropdowns, AND each hardware item's alias list — so the list
// (incl. alias_count) and any open alias panel both refetch.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAlias,
  createHardware,
  deleteAlias,
  deleteHardware,
  listAliases,
  listHardware,
  restoreAlias,
  restoreHardware,
  updateAlias,
  updateHardware,
  type ListHardwareParams,
} from '@/lib/hardware'
import type {
  HardwareAliasCreateInput,
  HardwareAliasUpdateInput,
  HardwareCreateInput,
  HardwareDeletedMode,
  HardwareUpdateInput,
} from '@/types'

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

// --- Aliases (admin-only) -------------------------------------------------------- //

export function useHardwareAliases(
  hardwareId: number,
  deleted: HardwareDeletedMode,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: ['hardware', hardwareId, 'aliases', deleted] as const,
    queryFn: () => listAliases(hardwareId, deleted),
    enabled: (options?.enabled ?? true) && hardwareId > 0,
  })
}

export function useCreateAlias(hardwareId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: HardwareAliasCreateInput) => createAlias(hardwareId, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useUpdateAlias(hardwareId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ aliasId, input }: { aliasId: number; input: HardwareAliasUpdateInput }) =>
      updateAlias(hardwareId, aliasId, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useDeleteAlias(hardwareId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (aliasId: number) => deleteAlias(hardwareId, aliasId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useRestoreAlias(hardwareId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (aliasId: number) => restoreAlias(hardwareId, aliasId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}
