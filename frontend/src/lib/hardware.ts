// Hardware catalogue API calls (thin wrappers over apiFetch). Settings > Hardware
// is admin-only — the backend enforces `require_admin` on every hardware route, so a
// non-admin request here returns 403 (surfaced as an ApiError).
//
// Stage 2B-1 shipped the READ path (list + search/filter/deleted view). Stage 2B-2 adds
// the catalogue WRITE path (create / edit / soft-delete / restore). Alias management is
// still Stage 2B-3, so no alias calls live here yet.

import { apiFetch } from '@/lib/api'
import type {
  HardwareCatalogueEntry,
  HardwareCatalogueListResponse,
  HardwareCategory,
  HardwareCreateInput,
  HardwareDeletedMode,
  HardwareUpdateInput,
} from '@/types'

export interface ListHardwareParams {
  q?: string
  category?: HardwareCategory
  brand?: string
  phase?: string
  nominal_kw?: number
  capacity_kwh?: number
  wattage_w?: number
  /** active only (default) / DELETED section / both. */
  deleted?: HardwareDeletedMode
  limit?: number
  offset?: number
}

export function listHardware(
  params: ListHardwareParams = {},
): Promise<HardwareCatalogueListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.category) search.set('category', params.category)
  if (params.brand) search.set('brand', params.brand)
  if (params.phase) search.set('phase', params.phase)
  if (params.nominal_kw != null) search.set('nominal_kw', String(params.nominal_kw))
  if (params.capacity_kwh != null) search.set('capacity_kwh', String(params.capacity_kwh))
  if (params.wattage_w != null) search.set('wattage_w', String(params.wattage_w))
  if (params.deleted) search.set('deleted', params.deleted)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  const qs = search.toString()
  return apiFetch<HardwareCatalogueListResponse>(`/hardware${qs ? `?${qs}` : ''}`)
}

export function createHardware(input: HardwareCreateInput): Promise<HardwareCatalogueEntry> {
  return apiFetch<HardwareCatalogueEntry>('/hardware', { method: 'POST', body: input })
}

export function updateHardware(
  id: number,
  input: HardwareUpdateInput,
): Promise<HardwareCatalogueEntry> {
  return apiFetch<HardwareCatalogueEntry>(`/hardware/${id}`, { method: 'PATCH', body: input })
}

// Soft-delete (moves the entry to the DELETED view; never hard-deletes). Returns the
// updated entry (now carrying deleted_at).
export function deleteHardware(id: number): Promise<HardwareCatalogueEntry> {
  return apiFetch<HardwareCatalogueEntry>(`/hardware/${id}`, { method: 'DELETE' })
}

export function restoreHardware(id: number): Promise<HardwareCatalogueEntry> {
  return apiFetch<HardwareCatalogueEntry>(`/hardware/${id}/restore`, { method: 'POST' })
}
