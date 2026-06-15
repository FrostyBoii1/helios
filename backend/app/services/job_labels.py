"""Job label services (Phase L1, read-only).

Pure read helpers over the label catalogue and a job's assignments. Write paths
(assign/remove, auto-assign on commit) arrive in later phases.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import JobLabelSource
from app.models.job_label import JobLabelAssignment, JobLabelDefinition


def list_label_definitions(
    db: Session, *, include_deleted: bool = False
) -> list[JobLabelDefinition]:
    """All label definitions in stable display order (sort_order, then id).

    Soft-deleted definitions are excluded unless ``include_deleted`` is True.
    """
    stmt = select(JobLabelDefinition)
    if not include_deleted:
        stmt = stmt.where(JobLabelDefinition.deleted_at.is_(None))
    stmt = stmt.order_by(JobLabelDefinition.sort_order, JobLabelDefinition.id)
    return list(db.scalars(stmt).all())


def get_label_by_key(db: Session, key: str) -> JobLabelDefinition | None:
    """A single active definition by its slug, or None."""
    return db.scalar(
        select(JobLabelDefinition).where(
            JobLabelDefinition.key == key,
            JobLabelDefinition.deleted_at.is_(None),
        )
    )


def list_job_labels(db: Session, job_id: int) -> list[JobLabelAssignment]:
    """A job's label assignments, ordered by their definition's display order.

    Assignments whose definition has been soft-deleted are excluded. Returns an
    empty list for a job with no labels.
    """
    stmt = (
        select(JobLabelAssignment)
        .join(JobLabelDefinition, JobLabelAssignment.label_id == JobLabelDefinition.id)
        .where(
            JobLabelAssignment.job_id == job_id,
            JobLabelDefinition.deleted_at.is_(None),
        )
        .order_by(JobLabelDefinition.sort_order, JobLabelAssignment.id)
    )
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Assignment (Phase L3) — idempotent assign + pure import auto-label derivation
# --------------------------------------------------------------------------- #
def assign_label_by_key(
    db: Session,
    *,
    job_id: int,
    key: str,
    source: JobLabelSource,
    assigned_by_id: int | None = None,
    note: str | None = None,
) -> JobLabelAssignment | None:
    """Idempotently assign the label ``key`` to a job.

    Returns the existing assignment if the (job, label) pair is already present
    (no duplicate is created), the new assignment on first creation, or ``None``
    if ``key`` is not a known active label. Caller commits.
    """
    label = get_label_by_key(db, key)
    if label is None:
        return None
    existing = db.scalar(
        select(JobLabelAssignment).where(
            JobLabelAssignment.job_id == job_id,
            JobLabelAssignment.label_id == label.id,
        )
    )
    if existing is not None:
        return existing
    assignment = JobLabelAssignment(
        job_id=job_id,
        label_id=label.id,
        source=source,
        assigned_by_id=assigned_by_id,
        note=note,
    )
    db.add(assignment)
    db.flush()
    return assignment


def remove_label_by_key(db: Session, *, job_id: int, key: str) -> bool:
    """Remove a job's assignment of the label ``key``.

    Hard-deletes the assignment row ONLY — the definition is never touched.
    Returns True if an assignment was removed, False if the label was unknown or
    not assigned to this job. Caller commits.
    """
    label = get_label_by_key(db, key)
    if label is None:
        return False
    assignment = db.scalar(
        select(JobLabelAssignment).where(
            JobLabelAssignment.job_id == job_id,
            JobLabelAssignment.label_id == label.id,
        )
    )
    if assignment is None:
        return False
    db.delete(assignment)
    db.flush()
    return True


# --------------------------------------------------------------------------- #
# Approval state — the authoritative structured control (Phase L2 / Slice 2).
# The approval STATE is "law": it is represented by at most one approval label,
# plus a pending date in details.approval.pending_date when pending.
# --------------------------------------------------------------------------- #
_APPROVAL_LABEL_BY_STATE = {
    "approved": "approval_approved",
    "pending": "approval_pending",
    "required": "approval_required",
}
_ALL_APPROVAL_KEYS = ("approval_approved", "approval_pending", "approval_required")


def _set_job_pending_date(job: Any, value: str | None) -> None:
    """Write/clear details.approval.pending_date on a job (reassigns the JSONB so
    SQLAlchemy detects the change). Prunes an empty approval section."""
    details = dict(job.details or {})
    approval = dict(details.get("approval") or {})
    if value:
        approval["pending_date"] = value
    else:
        approval.pop("pending_date", None)
    if approval:
        details["approval"] = approval
    else:
        details.pop("approval", None)
    job.details = details


def get_job_approval(db: Session, job: Any) -> dict[str, Any]:
    """Derive a job's approval state from its labels (+ pending date)."""
    keys = {a.label.key for a in list_job_labels(db, job.id)}
    if "approval_approved" in keys:
        state = "approved"
    elif "approval_pending" in keys:
        state = "pending"
    elif "approval_required" in keys:
        state = "required"
    else:
        state = "none"
    pending = ((job.details or {}).get("approval") or {}).get("pending_date")
    return {"state": state, "pending_date": pending if state == "pending" else None}


def set_job_approval(
    db: Session, *, job: Any, state: str, pending_date: str | None, assigned_by_id: int | None
) -> dict[str, Any]:
    """Authoritative approval-state edit. Syncs the (at most one) approval label
    and details.approval.pending_date; idempotent. Bypasses the casual system-lock
    because THIS is the structured control. Returns the resulting state plus the
    label changes (so the caller can log them). Caller commits."""
    target = _APPROVAL_LABEL_BY_STATE.get(state)  # None for "none"
    current = {a.label.key for a in list_job_labels(db, job.id)}
    added: list[str] = []
    removed: list[str] = []
    for key in _ALL_APPROVAL_KEYS:
        if key == target and key not in current:
            assign_label_by_key(
                db, job_id=job.id, key=key, source=JobLabelSource.SYSTEM, assigned_by_id=assigned_by_id
            )
            added.append(key)
        elif key != target and key in current:
            remove_label_by_key(db, job_id=job.id, key=key)
            removed.append(key)
    _set_job_pending_date(job, pending_date if state == "pending" else None)
    result = get_job_approval(db, job)
    result["changes"] = {"added": added, "removed": removed}
    return result


def auto_label_keys(
    parsed: dict[str, Any] | None, details: dict[str, Any] | None
) -> list[tuple[str, str | None]]:
    """Pure: the (label_key, note) pairs to auto-assign to a committed job from its
    parsed candidate + structured details.

    Rules:
      * approval_state == "approved" -> approval_approved
      * approval_state == "pending"  -> approval_pending (note carries pending date)
      * else (no approval evidence) AND a NUMERIC panel count > 0 AND an inverter is
        present -> approval_required ("Needs approval"). A real solar+inverter job
        with no recorded approval still needs network approval. Deliberately
        conservative: battery-only / no-panel / non-numeric-panel / inverter-only
        jobs have no numeric panel_count in details.system, so they never qualify;
        an already approved/pending job keeps that state and is never downgraded.
      * details.flags.removes_old_system -> decommission_pre_existing
        (note carries the decommission marker text)

    Labels are additive: the approval reference phrase and any source text stay in
    details.notes.review_notes — this never reads or mutates them.
    """
    parsed = parsed or {}
    details = details or {}
    out: list[tuple[str, str | None]] = []

    state = str(parsed.get("approval_state") or "").strip().lower()
    if state == "approved":
        out.append(("approval_approved", None))
    elif state == "pending":
        pending = str(parsed.get("approval_pending_date") or "").strip()
        out.append(("approval_pending", f"pending {pending}" if pending else None))
    else:
        # No approval evidence: a solar (numeric panels > 0) + inverter job still
        # needs network approval. panel_count is set in details.system ONLY when the
        # parser coerced a numeric count, so battery-only / inverter-only / no-panel
        # / non-numeric-panel jobs are excluded without any extra check.
        system = details.get("system") or {}
        panel_count = system.get("panel_count")
        inverter = str(system.get("inverter") or "").strip()
        if isinstance(panel_count, int) and panel_count > 0 and inverter:
            out.append(("approval_required", None))

    flags = details.get("flags") or {}
    if flags.get("removes_old_system"):
        marker = str(flags.get("decommission_marker") or "").strip()
        out.append(("decommission_pre_existing", marker or None))

    return out
