// TanStack Query hooks for customers.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  archiveCustomerContactVariant,
  createCustomer,
  createCustomerContactVariant,
  deleteCustomer,
  getCustomer,
  listCustomerContactVariants,
  listCustomers,
  mergeCustomer,
  updateCustomer,
  type ListCustomersParams,
} from '@/lib/customers'
import type { ContactVariantInput, CustomerInput } from '@/types'

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

// Stage 2: read-only alternate contact/address variants for a customer.
export function useCustomerContactVariants(id: number) {
  return useQuery({
    queryKey: ['customers', 'contact-variants', id] as const,
    queryFn: () => listCustomerContactVariants(id),
    enabled: Number.isFinite(id) && id > 0,
  })
}

// Stage 4: add a manual variant, then refresh this customer's variants + detail.
export function useCreateContactVariant(customerId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ContactVariantInput) => createCustomerContactVariant(customerId, input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['customers', 'contact-variants', customerId] })
      void qc.invalidateQueries({ queryKey: keys.detail(customerId) })
    },
  })
}

// Stage 4: archive (soft-delete) a manual variant, then refresh this customer's variants.
export function useArchiveContactVariant(customerId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (variantId: number) => archiveCustomerContactVariant(customerId, variantId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['customers', 'contact-variants', customerId] })
    },
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

// B4-2: merge `loserId` into the chosen winner. The backend moves the loser's
// jobs/tasks/documents/activities + import links to the winner and soft-deletes
// the loser, so refresh every affected list/detail (broad prefix invalidation).
export function useMergeCustomer(loserId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (winnerId: number) => mergeCustomer(loserId, winnerId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.all }) // ['customers']
      void qc.invalidateQueries({ queryKey: ['jobs'] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      void qc.invalidateQueries({ queryKey: ['activities'] })
      void qc.invalidateQueries({ queryKey: ['documents'] })
      void qc.invalidateQueries({ queryKey: ['imports'] })
    },
  })
}
