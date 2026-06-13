// Friendly labels for the backend reverse block reasons (C3).

const REVERSE_REASON_LABELS: Record<string, string> = {
  job_modified: 'the created job has been edited',
  customer_modified: 'the created customer has been edited',
  job_has_tasks: 'the job has tasks attached',
  job_has_documents: 'the job has documents attached',
  job_has_activity: 'the job has timeline activity',
  status_changed: 'the job status has changed',
  customer_has_other_jobs: 'the customer has other jobs',
  legacy_reference_mismatch: 'the job reference no longer matches',
  already_reversed: 'it has already been reversed',
  not_committed: 'the row was not committed',
  job_missing_or_deleted: 'the job no longer exists',
  customer_missing_or_deleted: 'the customer no longer exists',
}

export function reverseReasonLabel(reason: string | null): string {
  if (!reason) return 'it is no longer reversible'
  return REVERSE_REASON_LABELS[reason] ?? reason.replace(/_/g, ' ')
}
