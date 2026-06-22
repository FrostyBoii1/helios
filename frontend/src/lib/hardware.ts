// Hardware catalogue API calls (thin wrappers over apiFetch). Settings > Hardware
// is admin-only — the backend enforces `require_admin` on every hardware route, so a
// non-admin request here returns 403 (surfaced as an ApiError).
//
// Stage 2B-1 ships the READ path only (list + search/filter/deleted view). Create /
// edit / soft-delete / restore land with their UI in Stage 2B-2, and alias management
// in Stage 2B-3 — each as its own gated slice, so this file grows with its consumers.

import { apiFetch } from '@/lib/api'
import type {
  HardwareCatalogueListResponse,
  HardwareCategory,
  HardwareDeletedMode,
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
