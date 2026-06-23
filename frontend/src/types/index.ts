// Shared domain types. These mirror the backend Pydantic schemas. Keep in sync
// with backend/app/schemas until/unless a type-generation step is added.

// Registry-shaped structured details (same shape on import rows and live jobs).
import type { ParsedDetails } from './imports'

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
  internal_notes: string | null
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
  internal_notes?: string | null
}

export interface CustomerListResponse {
  items: Customer[]
  total: number
  limit: number
  offset: number
}

// B4-2 customer merge result (mirrors backend schemas.customer.CustomerMergeResult).
// `ids` is empty for kinds reported count-only (e.g. moved activities).
export interface MergeMovedCount {
  count: number
  ids: number[]
}

export interface CustomerMergeResult {
  winner: Customer
  loser_id: number
  merged_at: string
  moved: Record<string, MergeMovedCount>            // jobs / tasks / documents / activities
  repointed_import: Record<string, MergeMovedCount> // rows_committed / rows_resolved / groups_committed
  notes_appended: boolean
}

// B4-4: the structured detail body on a 404 for a MERGED loser customer (GET
// /customers/{id}). Lets the detail page show a "merged into X" notice + link
// instead of a mystery "Customer not found".
export interface CustomerMergedDetail {
  reason: 'merged'
  merged_into_customer_id: number
  merged_into_name: string
}

// Stage 2: an alternate customer-level identity/contact/address set (read-only).
// Primary Customer fields stay authoritative; variants are additive context.
export interface CustomerContactVariant {
  id: number
  customer_id: number
  label: string | null
  display_name: string | null
  email: string | null
  phone: string | null
  address_line1: string | null
  address_line2: string | null
  suburb: string | null
  state: string | null
  postcode: string | null
  source_type: string // merged_customer | import_row | manual | document
  // Source FK ids are deliberately NOT returned by the API (a merged loser's id stays
  // hidden); only the non-identifying source_type label is exposed.
  note: string | null
  created_at: string
  updated_at: string
  // Set when a user has edited this detail (null => pristine snapshot).
  edited_at: string | null
  // SAFE, API-computed source provenance for an import_row variant (which import row/job
  // contributed it, whether that row was reversed) — NOT raw internal FK ids. Null/false
  // for manual/merged/document variants.
  source_row_number: number | null
  source_job_case_number: string | null
  source_job_id: number | null
  source_reversed: boolean
}

export interface CustomerContactVariantList {
  items: CustomerContactVariant[]
  total: number
}

// Add/edit input for a Known Customer Detail. For add, source_type is forced to 'manual'
// by the backend; for edit (PATCH) the source_type + source FK ids are immutable and not
// part of this shape.
export interface ContactVariantInput {
  label?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  address_line1?: string | null
  address_line2?: string | null
  suburb?: string | null
  state?: string | null
  postcode?: string | null
  note?: string | null
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
  // Present on the Jobs list (Suburb/State column); may be absent on older refs.
  suburb?: string | null
  state?: string | null
}

// Lightweight label info embedded per job in the Jobs list (chips + filtering).
export interface JobLabelChip {
  key: string
  name: string
  color: string
  category: JobLabelCategory
  is_system: boolean
}

export interface Job {
  id: number
  case_number: string
  customer_id: number
  customer: CustomerRef
  // Read-only, API-computed: the ORIGINAL/source customer name when a merge moved this job
  // into its current customer under a DIFFERENT name (else null). The job's real customer
  // (above) is unchanged — this is display-only merge provenance.
  source_customer_name?: string | null
  status: JobStatus
  // Operational label chips for the Jobs list. Empty/absent on the detail fetch
  // (the Job detail page loads labels via /jobs/{id}/labels instead).
  labels?: JobLabelChip[]
  title: string | null
  system_details: string | null
  install_details: string | null
  approval_details: string | null
  notes: string | null
  internal_notes: string | null
  // Phase 4: structured, registry-shaped attributes. Null for jobs imported
  // before the structured commit mapping (currently all live jobs) — those fall
  // back to the legacy *_details blobs above.
  details: ParsedDetails | null
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
  internal_notes?: string | null
  sale_date?: string | null
  install_date?: string | null
  salesperson_id?: number | null
  assigned_user_id?: number | null
  // Phase 4c: path-restricted structured details patch (nested section → key →
  // value). The backend whitelists allowed job.details.* paths and deep-merges.
  details?: Record<string, unknown> | null
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
  // Spreadsheet-import provenance (Sections C/D) — emitted by commit / reverse /
  // prepare-recommit and shown on customer/job timelines.
  | 'record_imported'
  | 'record_import_reversed'
  | 'record_import_recommit_prepared'

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

export type TaskStatus = 'open' | 'in_progress' | 'completed' | 'cancelled'
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface JobRef {
  id: number
  case_number: string
}

export interface Task {
  id: number
  title: string
  description: string | null
  status: TaskStatus
  priority: TaskPriority
  due_date: string | null
  is_overdue: boolean
  customer_id: number | null
  job_id: number | null
  assigned_to_id: number | null
  created_by_id: number | null
  assigned_to: ActorRef | null
  created_by: ActorRef | null
  completed_by: ActorRef | null
  customer: CustomerRef | null
  job: JobRef | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface TaskInput {
  title?: string
  description?: string | null
  priority?: TaskPriority
  due_date?: string | null
  customer_id?: number | null
  job_id?: number | null
  assigned_to_id?: number | null
}

export interface TaskListResponse {
  items: Task[]
  total: number
  limit: number
  offset: number
}

export interface SelectableUser {
  id: number
  full_name: string
  role: RoleName
}

// ---- Job labels (operational flags) ----
export type JobLabelCategory = 'approval' | 'operational' | 'system' | 'custom'
export type JobLabelSource = 'import_auto' | 'manual' | 'system'

export interface JobLabelDefinition {
  id: number
  key: string
  name: string
  category: JobLabelCategory
  color: string
  description: string | null
  is_system: boolean
  is_auto: boolean
  sort_order: number
}

export interface JobLabelAssignment {
  id: number
  job_id: number
  label_id: number
  source: JobLabelSource
  assigned_by_id: number | null
  note: string | null
  created_at: string
  label: JobLabelDefinition
}

export type JobApprovalState = 'none' | 'required' | 'pending' | 'approved'

export interface JobApprovalRead {
  state: JobApprovalState
  pending_date: string | null
}

// ---- Hardware catalogue (Settings > Hardware; admin-only) ----
// Mirrors backend/app/schemas/hardware.py (HardwareCatalogueRead) + enums.py.
export type HardwareCategory = 'inverter' | 'battery' | 'panel' | 'metering'
export type HardwareAliasType = 'exact' | 'loose' | 'case_sensitive'
// Visibility for soft-deletable rows: active only / the DELETED section / both.
// Mirrors the backend `deleted` query param.
export type HardwareDeletedMode = 'exclude' | 'only' | 'include'

export interface HardwareCatalogueEntry {
  id: number
  spec_id: string
  category: HardwareCategory
  canonical_model: string | null
  display_name: string | null
  brand: string | null
  phases: string | null
  nominal_kw: number | null
  capacity_kwh: number | null
  wattage_w: number | null
  model_options: string[] | null
  attributes: Record<string, unknown> | null
  spec_source: string
  is_active: boolean
  // Active (non-deleted) alias count, computed server-side.
  alias_count: number
  created_at: string
  updated_at: string
  // Set when the entry is soft-deleted (DELETED section); null = active.
  deleted_at: string | null
}

export interface HardwareCatalogueListResponse {
  items: HardwareCatalogueEntry[]
  total: number
  limit: number
  offset: number
}

// Lean, authenticated-staff search result (GET /hardware/search) — active canonical hardware ONLY,
// for hardware-textbox autocomplete (import review now; Job Detail later). Mirrors the backend
// HardwareSearchResult: NO aliases / alias_count / attributes / spec_source / is_active / timestamps.
export interface HardwareSearchResult {
  id: number
  spec_id: string
  category: HardwareCategory
  display_name: string | null
  canonical_model: string | null
  brand: string | null
  phases: string | null
  nominal_kw: number | null
  capacity_kwh: number | null
  wattage_w: number | null
  model_options: string[] | null
}

export interface HardwareSearchListResponse {
  items: HardwareSearchResult[]
  total: number
  limit: number
  offset: number
}

// Create payload (mirrors HardwareCatalogueCreate). spec_id is the stable id, set on
// create and immutable thereafter; spec_source/attributes/is_active are server-managed
// or advanced and not edited from this UI.
export interface HardwareCreateInput {
  spec_id: string
  category: HardwareCategory
  canonical_model?: string | null
  display_name?: string | null
  brand?: string | null
  phases?: string | null
  nominal_kw?: number | null
  capacity_kwh?: number | null
  wattage_w?: number | null
  model_options?: string[] | null
}

// Partial update (mirrors HardwareCatalogueUpdate). spec_id is immutable, so it is not
// part of the update shape.
export type HardwareUpdateInput = Partial<Omit<HardwareCreateInput, 'spec_id'>>

// ---- Hardware aliases (Settings > Hardware; admin-only) ----
// Mirrors backend/app/schemas/hardware.py (HardwareAliasRead). alias_type vocabulary is
// exactly exact / loose / case_sensitive (HardwareAliasType) — source_examples are NEVER
// aliases. Aliases are admin-only and never exposed to normal users.
export interface HardwareAlias {
  id: number
  hardware_id: number
  alias: string
  alias_type: HardwareAliasType
  confidence_override: string | null
  decision_log_id: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  deleted_at: string | null
}

export interface HardwareAliasListResponse {
  items: HardwareAlias[]
  total: number
}

export interface HardwareAliasCreateInput {
  alias: string
  alias_type: HardwareAliasType
  confidence_override?: string | null
  decision_log_id?: string | null
}

export type HardwareAliasUpdateInput = Partial<HardwareAliasCreateInput>
