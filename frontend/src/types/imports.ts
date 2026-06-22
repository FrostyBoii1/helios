// Import staging/review domain types. Mirror backend/app/schemas/import_staging
// and backend/app/models/enums. Keep in sync until a type-generation step lands.

export type ImportBatchStatus =
  | 'parsing'
  | 'parsed'
  | 'reviewing'
  | 'failed'
  | 'committing'
  | 'committed'

export type ImportRowClass = 'blank' | 'divider' | 'job' | 'ambiguous'

export type ImportRowReviewStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'skipped'
  | 'committed'
  | 'reversed'

export type ImportIssueSeverity = 'info' | 'warning' | 'error'

export interface ImportBatch {
  id: number
  source_filename: string
  sheet_name: string
  file_sha256: string | null
  status: ImportBatchStatus
  total_rows: number
  job_rows: number
  divider_rows: number
  blank_rows: number
  ambiguous_rows: number
  issue_count: number
  notes: string | null
  created_by_id: number | null
  created_at: string
}

export interface ImportBatchList {
  items: ImportBatch[]
  total: number
}

export interface ImportIssue {
  id: number
  kind: string
  severity: ImportIssueSeverity
  field: string | null
  message: string
  resolved: boolean
  resolution_note: string | null
  resolved_by_id: number | null
  resolved_at: string | null
}

export interface PhoneEntry {
  number: string
  label: string
}

// Parsed candidate is free-form JSON; these are the keys the reviewer can edit
// (the whitelisted ImportRowEdit schema). Other keys may exist read-only.
export interface ParsedCandidate {
  customer_name?: string | null
  // Preserved meaningful non-name text from the Customer Name cell (editable).
  customer_name_notes?: string | null
  // Old-system removal / decommission signal (display-only flag + matched text).
  removes_old_system?: boolean | null
  decommission_marker?: string | null
  address?: string | null
  salesperson?: string | null
  sale_date?: string | null
  install_date?: string | null
  install_day?: string | null
  install_time?: string | null
  approval_state?: string | null
  approval_pending_date?: string | null
  distributor_inferred?: string | null
  retailer_raw?: string | null
  nmi_raw?: string | null
  meter_no?: string | null
  no_of_panels?: string | null
  panel_raw?: string | null
  inverter_raw?: string | null
  msb_state?: string | null
  notes_raw?: string | null
  emails?: string[] | null
  phones?: PhoneEntry[] | null
  // Phase 2a/2b structured candidate (grouped sections). Free-form nested JSON;
  // the registry describes its shape. Present on rows parsed after Phase 2a.
  details?: ParsedDetails | null
  [key: string]: unknown
}

// Structured details object (registry-shaped). Sections are nested dicts of
// individual fields; misfiled holds diverted text labelled with its source column.
export interface MisfiledNote {
  source_column?: string | null
  text?: string | null
}
// G (Stage 1): the per-job/site address, derived from the parsed Address cell and
// stored on Job.details.site (JSONB; no DB column). `structured` is false when the
// address could not be confidently split (then `line1` holds the raw line).
export interface SiteAddress {
  line1?: string | null
  line2?: string | null
  suburb?: string | null
  state?: string | null
  postcode?: string | null
  note?: string | null
  structured?: boolean
  raw?: string | null
}
// ---- Job hardware snapshot (Job.details.hardware; Hardware Parser lane, Stage 3) ----
// Mirrors backend/app/schemas/job_hardware.py. A Job-owned, editable SNAPSHOT — NOT a live
// reference to the hardware catalogue. Field sets must match the backend exactly (the backend
// rejects unknown fields), so a loaded item can be re-sent on save without an "extra field".
export interface JobHardwareItem {
  model_text?: string | null
  quantity?: number | null
  confidence?: string | null
  parser_owned?: boolean | null
  source_fragment?: string | null
  source_type?: string | null
  source_field?: string | null
  // Provenance/debug only — NEVER display truth.
  canonical_hardware_id_at_parse_time?: number | null
  parser_rule_version?: string | null
}

export interface JobHardwarePanel {
  quantity?: number | null
  brand?: string | null
  display_name?: string | null
  model?: string | null
  model_options?: string[] | null
  canonical_hardware_id_at_parse_time?: number | null
  wattage_w?: number | null
  panel_array_kw?: number | null
  confidence?: string | null
  parser_owned?: boolean | null
  source_fragment?: string | null
  parser_rule_version?: string | null
}

export interface JobHardwareSiteNotes {
  // List-based (Stage 4A) — faithful to the parser spec (a cell may carry several fragments).
  ct?: string[] | null
  export_limit?: string[] | null
  underground?: string[] | null
  comms?: string[] | null
  raw_misc?: string[] | null
}

export interface JobHardwareSnapshot {
  inverters?: JobHardwareItem[] | null
  batteries?: JobHardwareItem[] | null
  metering?: JobHardwareItem[] | null
  panel?: JobHardwarePanel | null
  site_notes?: JobHardwareSiteNotes | null
  warnings?: string[] | null
}

export interface ParsedDetails {
  _v?: number
  notes?: {
    customer_name_notes?: string | null
    misfiled?: MisfiledNote[]
    review_notes?: MisfiledNote[]
  } & Record<string, unknown>
  flags?: { removes_old_system?: boolean; decommission_marker?: string | null } & Record<string, unknown>
  approval?: { pending_date?: string | null } & Record<string, unknown>
  // G (Stage 1): per-job site address (display-only).
  site?: SiteAddress | null
  // Stage 3: Job-owned editable hardware snapshot (does NOT live-update from the catalogue).
  hardware?: JobHardwareSnapshot | null
  [section: string]: unknown
}

// ---- Field registry (GET /imports/field-registry); drives the structured UI ----
export interface FieldSpec {
  key: string
  label: string
  section: string
  entity: 'customer' | 'job'
  storage: string
  input_type:
    | 'text'
    | 'textarea'
    | 'number'
    | 'currency'
    | 'date'
    | 'select'
    | 'contact_list'
    | 'flag'
    | 'readonly'
  visible_when_blank: boolean
  category: 'core' | 'legacy' | 'derived'
  editable: boolean
  source_columns: string[]
  captured: string
  validation: Record<string, unknown>
}

export interface FieldRegistry {
  sections: { key: string; label: string }[]
  fields: FieldSpec[]
  editable_details_paths: string[]
}

export interface ImportRow {
  id: number
  source_row_index: number
  row_class: ImportRowClass
  legacy_reference: string | null
  raw: Record<string, unknown> | null
  parsed: ParsedCandidate | null
  original_parsed: ParsedCandidate | null
  context_text: string | null
  review_status: ImportRowReviewStatus
  review_notes: string | null
  // Reviewer override of the seeded Job.internal_notes: null = generated default,
  // "" = commit blank, text = commit verbatim.
  internal_notes_override: string | null
  reviewer_id: number | null
  reviewed_at: string | null
  committed_customer_id: number | null
  committed_job_id: number | null
  // B2-1/B2-2: manual same-customer resolution intent. mode: null = unresolved
  // (a new customer is created at commit), 'new' = explicit new, 'existing' =
  // attach the job to resolved_customer_id. Editable only while pending.
  resolved_customer_id: number | null
  customer_resolution_mode: CustomerResolutionMode | null
  customer_resolution_reason: string | null
  resolved_by_id: number | null
  resolved_at: string | null
  // B3-2/B3-4: membership in a pending-row group (mode === 'group').
  customer_group_id: number | null
  issues: ImportIssue[]
}

// Stored resolution mode on a row (null = unresolved). 'group' = member of a
// pending-row group (B3). The resolve REQUEST also accepts 'clear' to reset.
export type CustomerResolutionMode = 'existing' | 'new' | 'group'

export interface CustomerResolutionRequest {
  mode: 'existing' | 'new' | 'clear'
  customer_id?: number | null
  reason?: string | null
}

// ---- B3: pending-row groups (become one future customer at commit) ----
export interface CustomerGroupMember {
  row_id: number
  source_row_index: number
  customer_name: string | null
  is_primary: boolean
  // Read-only group-status visibility (committed/reversed members + re-promoted primary).
  review_status: ImportRowReviewStatus
  committed_customer_id: number | null
}

export interface CustomerGroupRead {
  id: number
  batch_id: number
  primary_row_id: number
  committed_customer_id: number | null
  created_by_id: number | null
  created_at: string
  reason: string | null
  member_row_ids: number[]
  members: CustomerGroupMember[]
}

// remove-row / dissolve may dissolve the group (group: null).
export interface CustomerGroupMutationResult {
  dissolved: boolean
  group: CustomerGroupRead | null
}

export interface ImportRowList {
  items: ImportRow[]
  total: number
  limit: number
  offset: number
}

// Whitelisted, typed edits. Mirrors backend ImportRowEdit (extra="forbid").
export interface ImportRowEdit {
  customer_name?: string | null
  customer_name_notes?: string | null
  address?: string | null
  salesperson?: string | null
  sale_date?: string | null
  install_date?: string | null
  install_day?: string | null
  install_time?: string | null
  approval_state?: string | null
  approval_pending_date?: string | null
  distributor_inferred?: string | null
  retailer_raw?: string | null
  nmi_raw?: string | null
  meter_no?: string | null
  no_of_panels?: string | null
  panel_raw?: string | null
  inverter_raw?: string | null
  msb_state?: string | null
  notes_raw?: string | null
  emails?: string[] | null
  phones?: PhoneEntry[] | null
  review_notes?: string | null
  // Override of the seeded Job.internal_notes. Send null to reset to the generated
  // default, "" to commit blank, or text to commit verbatim. Sent only when changed.
  internal_notes_override?: string | null
  // Phase 3b-2: path-restricted structured patch (nested section → key → value).
  // The backend whitelists allowed job.details.* paths and deep-merges a copy.
  details?: Record<string, unknown> | null
}

// The scalar (string) editable fields, in display order. emails/phones/
// review_notes are handled with dedicated controls.
export const PARSED_TEXT_FIELDS: { key: keyof ImportRowEdit; label: string }[] = [
  { key: 'customer_name', label: 'Customer name' },
  { key: 'customer_name_notes', label: 'Name-cell notes' },
  { key: 'address', label: 'Address' },
  { key: 'salesperson', label: 'Salesperson' },
  { key: 'sale_date', label: 'Sale date' },
  { key: 'install_date', label: 'Install date' },
  { key: 'install_day', label: 'Install day' },
  { key: 'install_time', label: 'Install time' },
  { key: 'approval_state', label: 'Approval state' },
  { key: 'approval_pending_date', label: 'Approval pending date' },
  { key: 'distributor_inferred', label: 'Distributor' },
  { key: 'retailer_raw', label: 'Retailer' },
  { key: 'nmi_raw', label: 'NMI' },
  { key: 'meter_no', label: 'Meter no.' },
  { key: 'no_of_panels', label: 'No. of panels' },
  { key: 'panel_raw', label: 'Panel' },
  { key: 'inverter_raw', label: 'Inverter' },
  { key: 'msb_state', label: 'MSB' },
  { key: 'notes_raw', label: 'Notes' },
]

export interface BulkApproveResult {
  approved: number
  eligible_examined: number
}

export interface ImportBatchSummary {
  batch_id: number
  by_review_status: Record<string, number>
  by_row_class: Record<string, number>
  issues_by_severity: Record<string, number>
  unresolved_error_rows: number
  eligible_clean_count: number
}

export interface ListRowsParams {
  row_class?: ImportRowClass
  review_status?: ImportRowReviewStatus
  severity?: ImportIssueSeverity
  unresolved_only?: boolean
  q?: string
  limit?: number
  offset?: number
}

// ---- Commit preview (C0, read-only) ----
export interface CommitCustomerPreview {
  full_name: string
  email: string | null
  phone: string | null
  address_line1: string | null
  extra_emails: string[]
  extra_phones: string[]
}

export interface CommitJobPreview {
  predicted_case_number: string
  legacy_reference: string | null
  status: string
  sale_date: string | null
  install_date: string | null
  salesperson_text: string | null
  system_details: string | null
  install_details: string | null
  approval_details: string | null
  notes: string | null
  removes_old_system?: boolean
  customer_name_notes?: string | null
}

export interface CommitRowPreview {
  row_id: number
  source_row_index: number
  legacy_reference: string | null
  case_year: number
  predicted_case_number: string
  customer: CommitCustomerPreview
  job: CommitJobPreview
}

export interface CommitExcludedCounts {
  already_committed: number
  blank_or_divider: number
  not_approved: number
  unresolved_error: number
  missing_customer_name: number
  invalid_case_year: number
}

export interface ImportCommitPreview {
  batch_id: number
  total_rows: number
  eligible_count: number
  excluded: CommitExcludedCounts
  would_create: { customers: number; jobs: number }
  predicted_case_numbers_by_year: Record<string, number>
  sample_limit: number
  sample_truncated: boolean
  samples: CommitRowPreview[]
}

// ---- Commit-to-live (C1) ----
export interface CommitRowResult {
  row_id: number
  source_row_index: number | null
  legacy_reference: string | null
  status: 'committed' | 'skipped' | 'failed'
  reason: string | null
  error: string | null
  case_number: string | null
  customer_id: number | null
  job_id: number | null
}

export interface ImportCommitResult {
  batch_id: number
  batch_status: string
  attempted: number
  committed: number
  skipped: number
  failed: number
  remaining_eligible: number
  cap: number
  capped_out: number
  results: CommitRowResult[]
}

// ---- Reverse (C3) ----
export interface ReverseCheck {
  row_id: number
  reversible: boolean
  reason: string | null
  customer_id: number | null
  job_id: number | null
  case_number: string | null
}

export interface ReverseResult {
  row_id: number
  status: 'reversed' | 'blocked'
  reason: string | null
  customer_id: number | null
  job_id: number | null
  case_number: string | null
}

// Section B1: an advisory same-customer candidate for an import row. Advisory
// only — no action is implied (no merge/link/resolve yet).
export interface MatchCandidate {
  kind: 'batch_row' | 'live_customer'
  name: string
  confidence: 'strong' | 'medium' | 'weak'
  reasons: string[]
  row_id: number | null
  source_row_index: number | null
  customer_id: number | null
  // B (stabilization): the batch-row candidate's pending group (if any) — drives the
  // "Join this group" action instead of silently stealing the row. Null otherwise.
  customer_group_id: number | null
}
