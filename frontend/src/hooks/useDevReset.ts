// TanStack Query hooks for the dev/test-only reset tools.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { clearImports, clearLiveCrm, getResetCounts } from '@/lib/devReset'

export function useResetCounts(enabled: boolean) {
  return useQuery({
    queryKey: ['dev-reset', 'counts'],
    queryFn: getResetCounts,
    enabled,
    staleTime: 0,
  })
}

export function useClearImports() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (confirm: string) => clearImports(confirm),
    // A reset invalidates almost every cache; refetch everything afterwards.
    onSuccess: () => void qc.invalidateQueries(),
  })
}

export function useClearLiveCrm() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (confirm: string) => clearLiveCrm(confirm),
    onSuccess: () => void qc.invalidateQueries(),
  })
}
