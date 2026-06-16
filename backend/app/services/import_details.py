"""Build the registry-shaped structured ``details`` object for an import row.

Pure and DB-free (Phase 2a). Reshapes a row's flat ``parsed`` candidate (plus
its ``raw`` cells, for columns the flat parse doesn't surface) into the grouped
sections declared by ``import_field_registry``, applying the owner's
"validate-or-divert-to-notes" rule:

  * a valid value goes to its structured field;
  * extra/misfiled text is preserved in ``details.notes.misfiled[]`` tagged with
    its source column;
  * the field stays blank when there is no valid value — text is never coerced
    into a typed field and never silently dropped.

This does NOT write to the DB and does NOT change commit-to-live behaviour. The
parser stamps the result onto ``parsed["details"]``; the commit-preview surfaces
it read-only.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.import_parser import parse_date_maybe

DETAILS_VERSION = 2

# Sections present in the structured object (mirrors the registry's sections;
# customer/contact + FC fields are mapped elsewhere, not inside details).
_SECTIONS = (
    "sales", "system", "electrical", "install", "payment",
    "compliance", "approval", "post_install", "legacy", "flags", "contacts", "notes",
)


def _s(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


# --------------------------------------------------------------------------- #
# Coercers: each returns (value_or_None, leftover_text). Leftover non-empty text
# is diverted to misfiled notes by the caller; value None means "no valid value".
# --------------------------------------------------------------------------- #
def _coerce_int(s: str) -> tuple[int | None, str]:
    t = s.strip().replace(",", "")
    if re.fullmatch(r"\d+", t):
        return int(t), ""
    m = re.match(r"(\d+)\b(.*)", t)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, s.strip()


def _coerce_currency(s: str) -> tuple[str | None, str]:
    t = s.strip()
    m = re.match(r"\$?\s*([\d,]+(?:\.\d+)?)\b(.*)", t)
    if m:
        return m.group(1).replace(",", ""), m.group(2).strip()
    return None, t


def _coerce_phase(s: str) -> tuple[str | None, str]:
    t = s.strip().lower()
    if t in ("1", "single", "single phase", "1 phase", "1ph", "sp"):
        return "single", ""
    if t in ("2", "two", "two phase", "2 phase", "2ph"):
        return "two", ""
    if t in ("3", "three", "three phase", "3 phase", "3ph", "tp"):
        return "three", ""
    return None, s.strip()


def _msb_status(s: str) -> str | None:
    """Recognised MSB status, or None for free text (caller diverts to notes).

    Unlike the legacy ``parse_msb`` (which defaults unknown -> 'maybe'), an
    unrecognised instruction (e.g. a do-not-call note) yields None here so the
    structured status stays blank and the text is preserved as a misfiled note.
    """
    t = s.strip().lower()
    if t in ("no", "requested"):
        return "no"
    if t in ("yes?", "??", "?"):
        return "maybe"
    if t.startswith("yes") or "in drive" in t or "in file" in t or "drive" in t:
        return "yes"
    return None


def build_details(parsed: dict | None, raw: dict | None) -> dict[str, Any]:
    """Return the registry-shaped ``details`` object for one row (pure)."""
    parsed = parsed or {}
    raw = raw or {}
    d: dict[str, dict] = {s: {} for s in _SECTIONS}
    misfiled: list[dict[str, str]] = []
    review_notes: list[dict[str, str]] = []

    def divert(col: str, text: Any) -> None:
        t = _s(text).strip()
        if t:
            misfiled.append({"source_column": col, "text": t})

    def review_note(col: str, text: Any) -> None:
        """Preserve recognized-but-unstructured context — a distributor approval
        phrase, a sales-cell DOB / free-note remainder, or non-numeric panel text —
        verbatim in a NEUTRAL bucket. Shown calmly as "imported review notes", never
        as a scary "misfiled" warning. Same {source_column, text} shape as misfiled;
        like misfiled it rides in details.notes, so it commits into Job.details."""
        t = _s(text).strip()
        if t:
            review_notes.append({"source_column": col, "text": t})

    def put_text(section: str, key: str, value: Any) -> None:
        v = _s(value).strip()
        if v:
            d[section][key] = v

    def put_number(
        section: str, key: str, col: str, raw_value: Any, *, currency: bool, review: bool = False
    ) -> None:
        rv = _s(raw_value)
        if not rv.strip():
            return
        # `review=True` routes leftover / non-numeric text to the neutral review-note
        # bucket instead of the misfiled warning bucket (used for panel counts so a
        # battery/inverter-only job's "existing system" text reads as context, not
        # an error).
        sink = review_note if review else divert
        value, leftover = (_coerce_currency(rv) if currency else _coerce_int(rv))
        if value is not None:
            d[section][key] = value
            if leftover:
                sink(col, leftover)
        else:
            sink(col, rv)

    # --- Sales ---
    put_text("sales", "salesperson_text", parsed.get("salesperson"))
    # Non-name suffix lifted off the Sales Consultant cell (a DOB / payment / system
    # / free-note remainder after any leading sale date was extracted) — preserved
    # verbatim as neutral review context, never coerced into the salesperson field.
    review_note("Sales Consultant", parsed.get("sales_consultant_misfiled"))

    # --- System ---
    put_text("system", "panel", parsed.get("panel_raw"))
    put_text("system", "inverter", parsed.get("inverter_raw"))
    # Non-numeric panel text (battery/inverter-only jobs: "existing system", "-",
    # …) is NEVER an error — route it to neutral review notes, not a warning.
    put_number("system", "panel_count", "No of Panels", parsed.get("no_of_panels"),
               currency=False, review=True)
    put_text("system", "storey", raw.get("storey"))
    phase_rv = _s(raw.get("phase"))
    if phase_rv.strip():
        ph, _left = _coerce_phase(phase_rv)
        if ph:
            d["system"]["phase"] = ph
        else:
            divert("Phase", phase_rv)
    put_text("system", "roof_type", raw.get("roof_type"))

    # --- Electrical / network ---
    put_text("electrical", "nmi", parsed.get("nmi_raw"))
    put_text("electrical", "meter_no", parsed.get("meter_no"))
    put_text("electrical", "distributor", parsed.get("distributor_inferred") or parsed.get("distributor_raw"))
    put_text("electrical", "retailer", parsed.get("retailer_raw"))

    # --- Install (install_date is a first-class Job column, not in details) ---
    put_text("install", "day", parsed.get("install_day"))
    put_text("install", "time", parsed.get("install_time"))
    put_text("install", "installer", parsed.get("installer_raw"))

    # --- Payment ---
    pay = parsed.get("payment") or {}
    put_number("payment", "total", "Total", pay.get("total"), currency=True)
    put_number("payment", "deposit", "Deposit", pay.get("deposit"), currency=True)
    put_number("payment", "balance", "Balance", pay.get("balance"), currency=True)
    put_text("payment", "result", pay.get("result"))
    put_text("payment", "notes", pay.get("notes"))
    put_number("payment", "stc_amount", "STC Amount", raw.get("stc_amount"), currency=True)

    # --- Compliance / admin ---
    msb_rv = _s(parsed.get("msb_raw") or raw.get("msb"))
    if msb_rv.strip():
        status = _msb_status(msb_rv)
        if status:
            d["compliance"]["msb_status"] = status
        else:
            # Owner rule: free text in the MSB column -> blank status + misfiled.
            divert("MSB/SB PICS IN FILE?", msb_rv)
    comp = parsed.get("compliance") or {}
    put_text("compliance", "welcome_call", comp.get("welcome_call"))
    put_text("compliance", "accreditation", comp.get("accreditation_code"))
    put_text("compliance", "ces_ecoc_email", raw.get("ces_ecoc_email"))

    # --- Approval (structured) ---
    # The approval STATE is represented by a label on commit (approval_approved /
    # approval_pending), and any reference phrase ("Jemena Approval # …") is kept
    # as a review note. The only structured approval datum is the pending date,
    # stored here so the live Approval control can read/write it.
    if str(parsed.get("approval_state") or "").lower() == "pending":
        pending_date = _s(parsed.get("approval_pending_date")).strip()
        if pending_date:
            d["approval"]["pending_date"] = pending_date

    # --- Post-install ---
    # The Post-Install Call/Review column holds a date, a completion status
    # ("DONE"), or a status + date ("Done 8/3/2023"). A pure date -> review_date;
    # anything else -> review_status (with any embedded date pulled into
    # review_date). The column is never misfiled — its value is always captured.
    pir = _s(raw.get("post_install_review")).strip()
    if pir:
        dt = parse_date_maybe(pir)
        if dt:
            d["post_install"]["review_date"] = dt.isoformat()
        else:
            m = re.search(r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", pir)
            if m:
                edt = parse_date_maybe(m.group(0))
                if edt:
                    d["post_install"]["review_date"] = edt.isoformat()
                status = (pir[: m.start()] + pir[m.end():]).strip(" -,:;|")
            else:
                status = pir
            if status:
                d["post_install"]["review_status"] = status
    # Post-install status columns — preserved verbatim as text (no date coercion);
    # blanks are omitted by put_text.
    put_text("post_install", "warranty_rego_completed", raw.get("warranty_rego_completed"))
    put_text("post_install", "post_install_email_sent", raw.get("post_install_email_sent"))

    # --- Legacy / import-only (only when populated) ---
    put_text("legacy", "solar_vic", raw.get("solar_vic"))
    put_text("legacy", "ces_submission", raw.get("ces_submission"))

    # --- Flags ---
    if parsed.get("removes_old_system"):
        d["flags"]["removes_old_system"] = True
        marker = _s(parsed.get("decommission_marker")).strip()
        if marker:
            d["flags"]["decommission_marker"] = marker

    # --- Contacts (extras beyond the primary phone/email) ---
    phones = parsed.get("phones") or []
    if len(phones) > 1:
        d["contacts"]["extra_phones"] = phones[1:]
    emails = parsed.get("emails") or []
    if len(emails) > 1:
        d["contacts"]["extra_emails"] = emails[1:]

    # --- Notes ---
    # Suffixes lifted off the Customer Name cell, preserved verbatim with their
    # source column: a land/legal parcel descriptor ("Lot 7 DP 123") and/or a
    # distributor approval/reference phrase ("Jemena Approval # 000…"). Neither is
    # part of the person's name; both are kept here instead of polluting it.
    # Land/legal parcel descriptor ("Lot 7 DP 123") stays a misfiled source note
    # (it genuinely didn't belong in the name). A distributor approval/reference
    # phrase ("Jemena Approval # 000…", "ERGON APPROVED") is recognized review
    # context, not junk — it goes to the neutral review-note bucket. The approval
    # STATUS it implies is still captured separately in parsed.approval_state.
    divert("Customer Name", parsed.get("name_cell_land_descriptor"))
    review_note("Customer Name", parsed.get("name_cell_approval_phrase"))
    cnn = _s(parsed.get("customer_name_notes")).strip()
    if cnn:
        d["notes"]["customer_name_notes"] = cnn
    if misfiled:
        d["notes"]["misfiled"] = misfiled
    if review_notes:
        d["notes"]["review_notes"] = review_notes

    # Prune empty sections; legacy/flags/etc. are omitted when blank.
    out: dict[str, Any] = {"_v": DETAILS_VERSION}
    for section in _SECTIONS:
        if d[section]:
            out[section] = d[section]
    return out


# --------------------------------------------------------------------------- #
# Derived legacy text blobs (Phase 2b) — rendered FROM the structured details so
# the legacy *_details / notes fields stay populated and consistent with what
# commit writes. Pure; the single source of truth for both commit and preview.
# --------------------------------------------------------------------------- #
def _join_bits(bits: list[tuple[str, Any]]) -> str | None:
    parts = [f"{label}: {_s(v).strip()}" for label, v in bits if _s(v).strip()]
    return " | ".join(parts) or None


# Explicit approval/approved/approving wording. Deliberately narrow — keyed on
# the approval word itself so the predicate never swallows useful unrelated
# context (a "finalise"/admin remark, a DOB, a Lot/DP descriptor, "export
# limited", "pillar", …). The reference/status it implies belongs in structured
# approval (label + details.approval), so it is dropped from the junk bucket.
_APPROVAL_CONTEXT_RE = re.compile(r"\bapprov(?:al|als|ed|e|ing)?\b", re.IGNORECASE)

# Bare no-value placeholders that carry no information (a lone dash, a blank,
# "n/a", "no panels"). Used to drop "No of Panels: -" style junk: having no
# panels is unambiguous and is not internal-note context.
_PANEL_PLACEHOLDER_VALUES = {"n/a", "na", "nil", "none", "no panels", "no panel"}

# A genuine distributor approval REFERENCE number — a #/No/Ref/Number marker
# followed by digits, or a standalone 6+ digit run (long enough not to be a year
# or DOB). The owner (R2) wants this kept in internal notes as useful operational
# context, UNLIKE a bare "ERGON APPROVED" status marker (which the label captures).
_APPROVAL_REF_NUMBER_RE = re.compile(
    r"(?:#|\bno\b\.?|\bref(?:erence)?\b\.?|\bnumber\b)\s*\.?\s*\d{3,}|\b\d{6,}\b",
    re.IGNORECASE,
)


def is_approval_context_note(text: Any) -> bool:
    """True when a preserved note is a BARE network-approval / status marker
    ("ERGON APPROVED", "approval pending") whose STATE is captured structurally
    (the approval label + ``details.approval``) — such text must not pollute the
    internal-notes safety bucket.

    EXCEPTION (owner R2): a note carrying an approval REFERENCE NUMBER ("Jemena
    Approval number 000410056") is useful operational context, so it is preserved
    in internal notes and is NOT treated as excludable approval context. A generic
    approval marker without a reference number stays excluded."""
    t = _s(text)
    if not _APPROVAL_CONTEXT_RE.search(t):
        return False
    if _APPROVAL_REF_NUMBER_RE.search(t):
        return False  # keep: a real reference number is useful context
    return True


def is_empty_panel_placeholder(text: Any) -> bool:
    """True when a preserved note is a bare no-value placeholder (a lone dash, a
    blank, "n/a", "no panels"). Owner P2 rule 4: having no panels is unambiguous
    and should not be imported as internal-note junk."""
    t = _s(text).strip().lower()
    # Strip surrounding dashes / dots / whitespace; a residue-free string is a
    # placeholder ("-", "--", "—", "", ".").
    stripped = t.strip(" \t-–—.")
    if stripped == "":
        return True
    return stripped in _PANEL_PLACEHOLDER_VALUES


def needs_approval_from_panels(details: dict | None) -> bool:
    """True when a system has a NUMERIC panel count > 0 AND an inverter — a real
    solar+inverter job that still needs network approval when there is no explicit
    approval evidence. Pure; reads only ``details.system``.

    The numeric ``panel_count`` is populated by ``build_details`` ONLY when the
    parser coerced a real count, so battery-only / inverter-only / no-panel /
    non-numeric-panel jobs have no numeric ``panel_count`` and return False — no
    extra check needed.

    This is the SINGLE source of truth for the "Needs approval" heuristic, shared by
    the parser (which derives the review-time ``approval_state``) and
    ``job_labels.auto_label_keys`` (the commit-time label), so the import-review UI
    and the committed label can never disagree. It is intentionally a heuristic on
    the imported sheet — later, stronger evidence (an explicit approval phrase now,
    or NAS-detected approval documents later) takes precedence and is never
    downgraded by this rule."""
    system = (details or {}).get("system") or {}
    panel_count = system.get("panel_count")
    inverter = str(system.get("inverter") or "").strip()
    return isinstance(panel_count, int) and panel_count > 0 and bool(inverter)


def build_imported_notes(details: dict | None) -> str | None:
    """Readable SAFETY-NET summary of USEFUL preserved imported context, for
    seeding ``Job.internal_notes`` on commit when it is blank. Returns None when
    there is nothing useful to preserve.

    The principle: if source text was stripped / diverted / preserved from the
    workbook, staff should be able to see it in internal notes — better duplicated
    in a readable place than effectively lost in a hidden panel. So this gathers,
    in order:
      * the name-cell notes (extra text kept off the Customer Name cell),
      * the neutral review notes (a DOB / free-note remainder, substantive panel
        remarks),
      * the misfiled source notes (Lot/DP / legal descriptors and other diverted
        column text).

    Owner P2 mapping rules:
      * the heading is "Uncategorised Data on Import";
      * the EXACT source text is kept, but its source-column label is NOT rendered
        (no "Customer Name:" / "Name cell:" / "No of Panels:" prefixes);
      * bare approval / status markers are EXCLUDED (structured by the label — see
        ``is_approval_context_note``), but an approval REFERENCE NUMBER is KEPT
        (owner R2: it is useful operational context);
      * bare no-value / no-panel placeholders are EXCLUDED
        (see ``is_empty_panel_placeholder``);
      * identical lines are de-duplicated.
    Structured field values, generated approval-state text, and provenance noise
    are NOT included — those have dedicated fields / are not in details.notes.
    This is a safety net, not the authoritative state (labels/fields remain
    authoritative)."""
    notes = (details or {}).get("notes", {}) or {}
    lines: list[str] = []
    seen: set[str] = set()

    def add(text: Any) -> None:
        t = _s(text).strip()
        if not t:
            return
        # Drop approval/reference context and bare no-value placeholders; keep the
        # exact source text WITHOUT its source-column label; de-dup identical text.
        if is_approval_context_note(t) or is_empty_panel_placeholder(t):
            return
        line = f"- {t}"
        if line not in seen:
            seen.add(line)
            lines.append(line)

    add(notes.get("customer_name_notes"))
    for m in notes.get("review_notes") or []:
        add(m.get("text"))
    for m in notes.get("misfiled") or []:
        add(m.get("text"))

    if not lines:
        return None
    return "Uncategorised Data on Import\n" + "\n".join(lines)


def render_structured_blobs(details: dict | None) -> dict[str, str | None]:
    """Render the two legacy blobs that are 100% derived from structured details
    (``system_details``, ``install_details``).

    Shared by ``render_legacy_blobs`` (commit/preview) and by live ``Job.details``
    edits (Phase 4b) — re-rendering just these two keeps them consistent with
    ``details`` without needing the ``parsed`` / batch context that
    ``approval_details`` and ``notes`` require. Empty fields are omitted.
    """
    details = details or {}
    system = details.get("system", {})
    electrical = details.get("electrical", {})
    install = details.get("install", {})
    compliance = details.get("compliance", {})

    system_details = _join_bits([
        ("Panels", system.get("panel_count")),
        ("Panel", system.get("panel")),
        ("Inverter", system.get("inverter")),
        ("Storey", system.get("storey")),
        ("Phase", system.get("phase")),
        ("Roof", system.get("roof_type")),
        ("Meter", electrical.get("meter_no")),
        ("NMI", electrical.get("nmi")),
        ("Distributor", electrical.get("distributor")),
        ("Retailer", electrical.get("retailer")),
        ("MSB", compliance.get("msb_status")),
    ])
    install_details = _join_bits([
        ("Day", install.get("day")),
        ("Time", install.get("time")),
        ("Installer", install.get("installer")),
    ])
    return {"system_details": system_details, "install_details": install_details}


def render_legacy_blobs(
    details: dict | None,
    parsed: dict | None,
    *,
    batch_id: int,
    source_row_index: int,
    legacy_reference: str | None,
) -> dict[str, str | None]:
    """Render the legacy text blobs from structured ``details`` (+ ``parsed`` for
    approval, which is not yet a registry field). Empty fields are omitted."""
    details = details or {}
    parsed = parsed or {}
    compliance = details.get("compliance", {})
    payment = details.get("payment", {})
    flags = details.get("flags", {})
    notes_sec = details.get("notes", {})
    sales = details.get("sales", {})
    legacy = details.get("legacy", {})

    structured = render_structured_blobs(details)
    system_details = structured["system_details"]
    install_details = structured["install_details"]
    # Approval preserves current behaviour (sourced from parsed, not details).
    approval_details = _join_bits([
        ("Approval", parsed.get("approval_state")),
        ("Pending date", parsed.get("approval_pending_date")),
    ])

    lines: list[str] = []
    # 1. Decommission first — operationally critical, never buried.
    if flags.get("removes_old_system"):
        marker = _s(flags.get("decommission_marker")).strip()
        lines.append(
            "REMOVE OLD SYSTEM - decommission the existing system"
            + (f" (flagged: {marker})" if marker else "")
            + "."
        )
    # 2. Name-cell notes.
    cnn = _s(notes_sec.get("customer_name_notes")).strip()
    if cnn:
        lines.append("From name cell: " + cnn)
    # 3. Salesperson.
    sp = _s(sales.get("salesperson_text")).strip()
    if sp:
        lines.append("Salesperson: " + sp)
    # 4. Payment summary.
    pay_bits = [
        f"{k}: {_s(payment.get(k)).strip()}"
        for k in ("total", "deposit", "balance", "result", "notes", "stc_amount")
        if _s(payment.get(k)).strip()
    ]
    if pay_bits:
        lines.append("Payment — " + ", ".join(pay_bits))
    # 5. Compliance / admin summary.
    comp_bits = [
        f"{k}: {_s(compliance.get(k)).strip()}"
        for k in ("accreditation", "welcome_call", "ces_ecoc_email")
        if _s(compliance.get(k)).strip()
    ]
    if comp_bits:
        lines.append("Compliance — " + ", ".join(comp_bits))
    # 6. Free-text Notes column.
    raw_notes = _s(parsed.get("notes_raw")).strip()
    if raw_notes:
        lines.append("Notes: " + raw_notes)
    # 7. Imported source/review notes — preserved text, labelled with its source
    #    column. Both are benign preserved context (not errors); review notes are
    #    recognized context (approval phrases, DOB/panel remainders), source notes
    #    are other leftover column text.
    for m in notes_sec.get("review_notes") or []:
        col = _s(m.get("source_column")).strip()
        txt = _s(m.get("text")).strip()
        if txt:
            lines.append(f"Imported review note — {col}: {txt}" if col else "Imported review note: " + txt)
    for m in notes_sec.get("misfiled") or []:
        col = _s(m.get("source_column")).strip()
        txt = _s(m.get("text")).strip()
        if txt:
            lines.append(f"Imported source note — {col}: {txt}" if col else "Imported source note: " + txt)
    # 8. Legacy / import-only — only when populated.
    leg_bits = [
        f"{k}: {_s(legacy.get(k)).strip()}"
        for k in ("solar_vic", "ces_submission")
        if _s(legacy.get(k)).strip()
    ]
    if leg_bits:
        lines.append("Legacy — " + ", ".join(leg_bits))
    # 9. Provenance (preserved verbatim).
    lines.append(
        f"Imported from legacy workbook (batch {batch_id}, row {source_row_index}"
        + (f", ref {legacy_reference}" if legacy_reference else "")
        + ")."
    )

    return {
        "system_details": system_details,
        "install_details": install_details,
        "approval_details": approval_details,
        "notes": "\n".join(lines) or None,
    }
