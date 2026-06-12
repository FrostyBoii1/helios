// Shared domain types. These mirror the backend Pydantic schemas. Keep in sync
// with backend/app/schemas until/unless a type-generation step is added.

export type RoleName =
  | 'admin'
  | 'scheduling'
  | 'approvals'
  | 'support'
  | 'sales_admin'

export interface Role {
  id: number
  name: RoleName
  description: string | null
}

export interface User {
  id: number
  full_name: string
  email: string
  is_active: boolean
  role: Role
  created_at: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface Customer {
  id: number
  full_name: string
  email: string | null
  phone: string | null
  address_line1: string | null
  address_line2: string | null
  suburb: string | null
  state: string | null
  postcode: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

// Fields accepted on create/update. full_name required on create.
export interface CustomerInput {
  full_name: string
  email?: string | null
  phone?: string | null
  address_line1?: string | null
  address_line2?: string | null
  suburb?: string | null
  state?: string | null
  postcode?: string | null
  notes?: string | null
}

export interface CustomerListResponse {
  items: Customer[]
  total: number
  limit: number
  offset: number
}
