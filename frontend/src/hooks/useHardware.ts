// TanStack Query hooks for the hardware catalogue (Settings > Hardware, admin-only).
// Stage 2B-1: read-only list. Mutations (create / edit / soft-delete / restore, and
// aliases) land with their UI in later 2B stages and will reuse these query keys.

import { useQuery } from '@tanstack/react-query'
import { listHardware, type ListHardwareParams } from '@/lib/hardware'

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
