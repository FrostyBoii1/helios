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
  [key: string]: unknown
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
  reviewer_id: number | null
  reviewed_at: string | null
  committed_customer_id: number | null
  committed_job_id: number | null
  issues: ImportIssue[]
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
}

// The scalar (string) editable fields, in display order. emails/phones/
// review_notes are handled with dedicated controls.
export const PARSED_TEXT_FIELDS: { key: keyof ImportRowEdit; label: string }[] = [
  { key: 'customer_name', label: 'Customer name' },
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
