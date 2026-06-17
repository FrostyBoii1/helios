// TanStack Query hooks for customers.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCustomer,
  deleteCustomer,
  getCustomer,
  listCustomers,
  updateCustomer,
  type ListCustomersParams,
} from '@/lib/customers'
import type { CustomerInput } from '@/types'

const keys = {
  all: ['customers'] as const,
  list: (params: ListCustomersParams) => ['customers', 'list', params] as const,
  detail: (id: number) => ['customers', 'detail', id] as const,
}

export function useCustomers(params: ListCustomersParams, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: keys.list(params),
    queryFn: () => listCustomers(params),
    enabled: options?.enabled ?? true,
  })
}

export function useCustomer(id: number) {
  return useQuery({
    queryKey: keys.detail(id),
    queryFn: () => getCustomer(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

export function useCreateCustomer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: CustomerInput) => createCustomer(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useUpdateCustomer(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: Partial<CustomerInput>) => updateCustomer(id, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
      void qc.invalidateQueries({ queryKey: keys.detail(id) })
    },
  })
}

export function useDeleteCustomer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteCustomer(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}
