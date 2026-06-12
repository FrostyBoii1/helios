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

export type JobStatus =
  | 'new'
  | 'awaiting_approval'
  | 'ready_to_schedule'
  | 'booked_for_install'
  | 'installed'
  | 'post_install_call_required'
  | 'review_request_required'
  | 'maintenance_required'
  | 'support'
  | 'completed'
  | 'cancelled'

export interface CustomerRef {
  id: number
  full_name: string
}

export interface Job {
  id: number
  case_number: string
  customer_id: number
  customer: CustomerRef
  status: JobStatus
  title: string | null
  system_details: string | null
  install_details: string | null
  approval_details: string | null
  notes: string | null
  sale_date: string | null
  install_date: string | null
  salesperson_id: number | null
  assigned_user_id: number | null
  created_at: string
  updated_at: string
}

// Fields accepted on create/update (customer_id required only on create).
export interface JobInput {
  title?: string | null
  system_details?: string | null
  install_details?: string | null
  approval_details?: string | null
  notes?: string | null
  sale_date?: string | null
  install_date?: string | null
  salesperson_id?: number | null
  assigned_user_id?: number | null
}

export interface JobListResponse {
  items: Job[]
  total: number
  limit: number
  offset: number
}

export type ActivityType =
  | 'job_created'
  | 'job_updated'
  | 'job_status_changed'
  | 'job_deleted'
  | 'install_rescheduled'
  | 'customer_created'
  | 'customer_updated'
  | 'customer_deleted'
  | 'task_assigned'
  | 'task_completed'
  | 'note_added'
  | 'file_uploaded'
  | 'file_deleted'
  | 'user_created'
  | 'user_updated'

export interface ActorRef {
  id: number
  full_name: string
}

export interface Activity {
  id: number
  activity_type: ActivityType
  description: string
  meta: Record<string, unknown> | null
  created_at: string
  actor: ActorRef | null
  customer_id: number | null
  job_id: number | null
}

export interface ActivityListResponse {
  items: Activity[]
  total: number
  limit: number
  offset: number
}
