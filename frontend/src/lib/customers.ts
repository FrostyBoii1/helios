// Customer API calls (thin wrappers over apiFetch).

import { apiFetch } from '@/lib/api'
import type {
  Customer,
  CustomerContactVariantList,
  CustomerInput,
  CustomerListResponse,
  CustomerMergeResult,
} from '@/types'

export interface ListCustomersParams {
  q?: string
  limit?: number
  offset?: number
}

export function listCustomers(params: ListCustomersParams = {}): Promise<CustomerListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiFetch<CustomerListResponse>(`/customers${qs ? `?${qs}` : ''}`)
}

export function getCustomer(id: number): Promise<Customer> {
  return apiFetch<Customer>(`/customers/${id}`)
}

export function createCustomer(input: CustomerInput): Promise<Customer> {
  return apiFetch<Customer>('/customers', { method: 'POST', body: input })
}

export function updateCustomer(id: number, input: Partial<CustomerInput>): Promise<Customer> {
  return apiFetch<Customer>(`/customers/${id}`, { method: 'PATCH', body: input })
}

export function deleteCustomer(id: number): Promise<void> {
  return apiFetch<void>(`/customers/${id}`, { method: 'DELETE' })
}

// B4-2: explicitly merge the loser customer into the winner (admin-only on the
// backend). Returns the merge summary (surviving winner + moved/repointed counts).
export function mergeCustomer(loserId: number, winnerId: number): Promise<CustomerMergeResult> {
  return apiFetch<CustomerMergeResult>(`/customers/${loserId}/merge-into/${winnerId}`, {
    method: 'POST',
  })
}

// Stage 2: read-only alternate contact/address variants for an active customer.
export function listCustomerContactVariants(id: number): Promise<CustomerContactVariantList> {
  return apiFetch<CustomerContactVariantList>(`/customers/${id}/contact-variants`)
}
