"""Pure, DB-free parser for the legacy jobs workbook (COMPLETED sheet).

This module contains NO database access and NO real customer data. It takes an
openpyxl worksheet, classifies each row, and parses cells into a structured
candidate plus a list of data-quality issues. Both the read-only dry-run CLI
(`backend/scripts/import_dryrun.py`) and the staging ingest service use this, so
they parse identically. It is unit-testable with a synthetic in-memory workbook.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# --------------------------------------------------------------------------- #
# Reference rules (owner-provided NMI prefixes)
# --------------------------------------------------------------------------- #
NMI_PREFIX_RULES: list[tuple[str, str]] = [
    ("4001", "NSW Essential"),
    ("4407", "NSW Essential"),
    ("4204", "NSW Essential"),
    ("4508", "NSW Essential"),
    ("4301", "NSW Endeavour"),
    ("6305", "VIC AusNet"),
    ("6306", "VIC AusNet"),
    ("6407", "VIC United"),
    ("6408", "VIC United"),
    ("6203", "VIC Powercor"),
    ("6204", "VIC Powercor"),
    ("6001", "VIC Jemena"),
    ("410", "NSW Ausgrid"),
    ("304", "QLD Ergon"),
    ("305", "QLD Ergon"),
    ("31", "QLD Energex"),
]
NMI_ALNUM_RULES: list[tuple[str, str]] = [("QB", "QLD Energex")]

APPROVAL_APPROVED_RE = re.compile(r"\bAPPROVED\b", re.IGNORECASE)
APPROVAL_PENDING_RE = re.compile(r"\bPENDING\b\s*([0-3]?\d[/\-][0-1]?\d[/\-]\d{2,4})?", re.IGNORECASE)
# A distributor approval REFERENCE means the connection was approved, e.g.
# "Jemena Approval # 000413493", "ENERGEX APPROVAL No 12345", "Approval Ref 678901".
# Match "approv…" near either a #/No/Ref/Number marker + 3+ digits, OR a standalone
# 6+ digit reference number (long enough not to be a year). Checked AFTER the
# pending rule, so "pending approval 12/3/26" stays pending.
APPROVAL_REFERENCE_RE = re.compile(
    r"\bapprov\w*\b.{0,12}?(?:(?:#|\bno\b\.?|\bref(?:erence)?\b\.?|\bnumber\b)\s*\.?\s*\d{3,}|\d{6,})",
    re.IGNORECASE,
)
# Approval-ACTION phrases in the name cell ("DO APPROVAL", "NEED/NEEDS APPROVAL",
# "APPLY APPROVAL", "ORGANISE APPROVAL", "GET APPROVAL", or the reverse "approval
# needed/required"): an explicit instruction to OBTAIN approval — the connection is
# NOT yet approved. Distinct from a past-tense "APPROVED" (done) and from a
# reference number (done): this classifies the job as approval_required ("Needs
# approval"). The bare action phrase is then dropped from the preserved note (its
# meaning is carried by the label), while surrounding context is kept.
APPROVAL_ACTION_RE = re.compile(
    r"\b(?:do|need|needs|apply|organi[sz]e|get|require|requires|arrange|chase)\s+(?:the\s+)?approval\b"
    r"|\bapproval\s+(?:needed|required|to\s+do|outstanding)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"([0-3]?\d[/\-][0-1]?\d[/\-]\d{2,4})")
# Old-system removal / decommission markers. Operationally important: surfaced
# as a parsed flag so staff see it after import instead of it being buried in
# raw cells. `decom\w*` covers DECOM, decommission, and the decommision /
# decomission misspellings; plus the explicit "remove old system" phrase.
DECOMMISSION_RE = re.compile(r"\b(?:remove\s+old\s+system|decom\w*)\b", re.IGNORECASE)
# Network/distributor labels that commonly precede an approval-status word in the
# name cell (e.g. "ESSENTIAL APPROVED", "ENERGEX PENDING 19/08/2026"). They are
# removed ONLY as part of an approval phrase — a standalone label elsewhere in
# the note stays as meaningful content.
_NETWORK_LABELS = (
    "ESSENTIAL", "ENERGEX", "ERGON", "ENDEAVOUR", "AUSGRID", "AUSNET",
    "POWERCOR", "UNITED", "JEMENA", "SAPN",
)
# Approval-status phrases stripped from name-cell trailing text so the preserved
# note is "meaningful non-name text". An optional immediately-preceding network
# label is consumed as part of the phrase (so no bare "ESSENTIAL" residue).
_APPROVAL_TOKEN_RE = re.compile(
    r"\b(?:(?:" + "|".join(_NETWORK_LABELS) + r")\s+)?"
    r"(?:APPROVED|PENDING\b\s*(?:[0-3]?\d[/\-][0-1]?\d[/\-]\d{2,4})?)\b",
    re.IGNORECASE,
)
# Trailing-text markers in the Customer Name cell. Land/legal parcel descriptors
# (Lot/DP) are NOT here — they are handled by LAND_DESCRIPTOR_RE below, which
# requires a parcel number so it can't truncate surnames like "Lott" the way a
# loose " Lot" substring marker did.
NAME_STOP_MARKERS = [" - ", " DOB", " PENDING", " APPROVED", " Approved",
                     " #", " REF", " Ref"]
# Land/legal parcel descriptor trailing a customer name ("Jane - Lot 7 DP 123",
# "John-Lot 5"): a Lot/DP keyword followed by a number, however it is separated
# (space, bare hyphen, comma). Never part of the person's name — it is captured
# verbatim and diverted to a misfiled note (source_column 'Customer Name'). The
# required digit avoids matching surnames like "Lott" / initials like "DP".
LAND_DESCRIPTOR_RE = re.compile(r"\s*[-,]?\s*\b(?:lot|dp)\b\.?\s*\d[\w/.\- ]*$", re.IGNORECASE)
# Distributor approval / reference phrase appended to a name cell
# ("Jane - JEMENA APPROVAL #000445604", "ESSENTIAL APPROVED"): a network label
# that reaches an approval/approved/pending/ref keyword, captured to end of cell.
# Separated out so the phrase is preserved verbatim and the network label never
# becomes the customer name; status words are still read by parse_approval. A
# network word that is NOT followed by an approval keyword (e.g. "ESSENTIAL
# repairs needed") is left untouched.
_NAME_APPROVAL_PHRASE_RE = re.compile(
    r"\s*[-,]?\s*\b(?:" + "|".join(_NETWORK_LABELS) + r")\b.*?"
    r"\b(?:approval|approved|pending|ref)\b.*$",
    re.IGNORECASE | re.DOTALL,
)
# Name-cell suffixes that are NEVER part of a person's name. Each anchors to the
# END of the cell with an optional leading separator (space / hyphen / comma /
# semicolon / pipe), is captured VERBATIM and preserved as a name-cell note (no
# text loss — it flows to customer_name_notes and the post-commit internal_notes
# safety net), then removed from the name. NONE infers a structured field — there
# is no DOB concept in this model; a date here stays plain preserved text.
_NAME_SUFFIX_NOTE_RES = (
    # Date-of-birth phrase: "DATE OF BIRTH" (with or without a date), or a
    # "DOB" / "D.O.B" label FOLLOWED BY a date. A bare "DOB" with no date is left
    # to the existing NAME_STOP_MARKERS handling, keeping this change additive.
    re.compile(r"[\s\-,;|]*\bdate\s+of\s+birth\b.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"[\s\-,;|]*\bd\.?\s*o\.?\s*b\.?\b[\s:.\-]*" + DATE_RE.pattern + r".*$",
               re.IGNORECASE | re.DOTALL),
    # Network "pillar" reference ("pillar 111178023"): the keyword must reach a
    # digit, so a surname like "Pillar" is never stripped.
    re.compile(r"[\s\-,;|]*\bpillar\b[\s#:.]*\d.*$", re.IGNORECASE | re.DOTALL),
    # Export-limit annotation, with an optional leading "<n>kW"
    # ("2.28KW EXPORT LIMITED", "EXPORT LIMITED 5kw").
    re.compile(r"[\s\-,;|]*(?:\d+(?:\.\d+)?\s*kw\s+)?export\s+limit\w*\b.*$",
               re.IGNORECASE | re.DOTALL),
    # Retailer-admin "finalise to ..." instruction ("FINALISE TO AGL").
    re.compile(r"[\s\-,;|]*\bfinali[sz]e\b.*$", re.IGNORECASE | re.DOTALL),
    # Bare trailing date preceded by whitespace or a separator ("Carter- 18/4/75",
    # "Claire Joshua 11/05/2003"): a date at the very end of a name cell is a note,
    # never part of the name. LAST so a DOB / finalise phrase claims its own date.
    re.compile(r"[\s\-,;|]+" + DATE_RE.pattern + r"\s*$"),
)
# An email occupying the WHOLE Customer Name cell ("jjmckoz82@gmail.com") is not a
# person's name. parse_rows raises a BLOCKING email_only_name error so it cannot
# commit as a customer name; a mixed "Name <email>" cell is left untouched.
_EMAIL_TOKEN_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# A trailing date preceded by a PENDING / approval keyword ("Pat Lee - PENDING
# 19/08/2026") is the APPROVAL date, not a bare note: it must stay adjacent to the
# keyword so parse_approval can read approval_pending_date. Guards the bare-date
# stripper (the last entry of _NAME_SUFFIX_NOTE_RES) only.
_APPROVAL_DATE_TAIL_RE = re.compile(r"(?i)\b(?:pending|approv\w*)\b[\s:\-]*$")
# A bare date sitting MID-cell, glued to / following the name without a standard
# stop-marker ("Naomi Carter- 18/4/75 - DL - 11878134 - ... - NSW"): the date and
# everything after it are never part of the name. Used as an EXTRA name cut point —
# the bare-date suffix rule above only fires when the date ends the cell, so a date
# followed by more text (a licence/lot/state tail) would otherwise stay glued. The
# date is preserved verbatim (never inferred as a DOB) and is guarded by
# _APPROVAL_DATE_TAIL_RE so a PENDING / approval date is never cut here.
_NAME_DATE_SPLIT_RE = re.compile(r"(?:\s*[-,;|]\s*|\s+)" + DATE_RE.pattern)
# Australian address tail: a state code immediately followed by a 4-digit
# postcode (or the rarer postcode-then-state). Anchored to the END so we only
# structure an address when this reliable signal is present — everything before
# it is the street + suburb. Real workbook data: ~98.5% of addresses end exactly
# this way, so this is conservative, not a guess.
AU_STATES = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT")
_ADDR_TAIL_RE = re.compile(
    r"[\s,]*(?:"
    r"\b(?P<state1>" + "|".join(AU_STATES) + r")\b[\s,]+(?P<pc1>\d{4})"
    r"|(?P<pc2>\d{4})[\s,]+\b(?P<state2>" + "|".join(AU_STATES) + r")\b"
    r")\s*$",
    re.IGNORECASE,
)
DIVIDER_HINTS = ("FORTNIGHT", "WEEK ", "BELOW", "ABOVE", "MONTH", "TBC")
PANEL_BRAND_HINTS = ("longi", "trina", "ae", "tw", "jinko", "ja ", "canadian", "risen", "qcell",
                     "rec", "sunpower", "hyundai", "seraphim", "phono")
INVERTER_BRAND_HINTS = ("goodwe", "sungrow", "solis", "saj", "alpha", "sigenergy", "solax", "fronius",
                        "growatt", "huawei", "tesla", "sma", "enphase", "redback")
REF_RE = re.compile(r"^SCS?\d{3,4}\b", re.IGNORECASE)

# header (normalised, trailing '?'/':' stripped) -> canonical field key
WANTED_HEADERS = {
    "sales consultant": "sales_consultant",
    "customer name": "customer_name",
    "address": "address",
    "phone": "phone",
    "notes": "notes",
    "msb/sb pics in file": "msb",
    "email": "email",
    "distributor": "distributor",
    "retailer": "retailer",
    "nmi": "nmi",
    "meter no": "meter_no",
    "no of panels": "no_of_panels",
    "panel brand/ wattage": "panel_brand",
    "inverter brand/model": "inverter",
    "storey": "storey",
    "phase": "phase",
    "roof type": "roof_type",
    "date": "date",
    "day": "day",
    "time": "time",
    "installer": "installer",
    "welcome call": "welcome_call",
    "total": "total",
    "deposit": "deposit",
    "balance": "balance",
    "result of payment": "result_of_payment",
    "notes on payment": "notes_on_payment",
    "accreditation code": "accreditation_code",
    # Phase 2a: columns confirmed present in the real workbook header row but not
    # previously captured. Header strings match import_field_registry source_columns.
    "stc amount": "stc_amount",
    "solar vic payment": "solar_vic",
    "date of post installation call/review request": "post_install_review",
    "ces/ecoc/ccew to retailer email - all other distributors": "ces_ecoc_email",
    "ces submission to distributor ausnet/powercor/united/jemena": "ces_submission",
    # Post-install status columns (Phase 7 owner request): captured as structured
    # post_install fields instead of falling through to raw['_unmapped'].
    "warranty rego completed": "warranty_rego_completed",
    "post installation email sent": "post_install_email_sent",
}


@dataclass
class ParsedRow:
    source_row_index: int
    row_class: str
    legacy_reference: str
    raw: dict[str, Any]
    parsed: dict[str, Any]
    context_text: str | None = None
    issues: list[dict[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cell + field helpers (pure)
# --------------------------------------------------------------------------- #
def norm_cell(v: Any) -> str:
    if v is None:
        return ""
    text = str(v).strip()
    if re.fullmatch(r"-?\d+\.0", text):  # Excel coerces text-ints to floats
        text = text[:-2]
    return text


def infer_distributor(nmi_raw: str) -> tuple[str | None, str | None]:
    raw = nmi_raw.strip()
    if not raw or raw in {"-", "N/A", "n/a"}:
        return None, None
    upper = raw.upper()
    for prefix, name in NMI_ALNUM_RULES:
        if upper.startswith(prefix):
            return name, prefix
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None, None
    for prefix, name in sorted(NMI_PREFIX_RULES, key=lambda x: -len(x[0])):
        if digits.startswith(prefix):
            return name, prefix
    if digits.startswith("2"):
        return "SA SAPN", "2"
    return None, None


def parse_msb(raw: str) -> str:
    t = raw.strip().lower()
    if t in {"", "no", "requested"}:
        return "no"
    if t in {"yes?", "??", "?"}:
        return "maybe"
    if t.startswith("yes") or "in drive" in t or "in file" in t or "drive" in t:
        return "yes"
    return "maybe"


def parse_sales_consultant(raw: str) -> dict[str, Any]:
    """Split the Sales Consultant cell into the leading salesperson NAME and any
    trailing non-name suffix.

    Owner rule (Phase 7): only the actual salesperson name belongs in the
    structured field. Text after a ' - ' separator — payment/system/free-note text
    such as 'cash', '13.28kw Humm', or 'dob 14/05/1980' — is NOT part of the name;
    it is returned as ``misfiled`` so the caller preserves it verbatim under
    source_column 'Sales Consultant'.

    A suffix that is ONLY a date (e.g. 'Jane - 3/2/23') is taken as the sale date.
    A MIXED suffix that LEADS with a plain date (e.g. '4/4/2023 - dob 23/11/55') has
    that leading date extracted as the sale date and the remainder ('dob 23/11/55')
    preserved verbatim as ``misfiled``. A labelled / non-leading date (e.g.
    'dob 14/05/1980') is NEVER a sale date — there is no DOB concept in this model —
    so the whole suffix is preserved verbatim and no date is pulled out of it."""
    if not raw:
        return {"name": "", "sale_date": None, "misfiled": None}
    misfiled: str | None = None
    suffix_sale_date: str | None = None
    head = raw
    sep = raw.find(" - ")
    if sep != -1:
        suffix = raw[sep + 3:].strip()
        # Pure-date suffix -> leave it on `head` so the date extraction below takes
        # it as the sale date. A MIXED suffix is diverted verbatim — but first a
        # LEADING plain date is pulled out as the sale date (e.g.
        # "4/4/2023 - dob 23/11/55" -> sale_date 4/4/2023, note "dob 23/11/55"). A
        # non-leading / labelled date ("dob 14/05/1980") is preserved whole and
        # never becomes a sale_date.
        if suffix and DATE_RE.sub("", suffix).strip(" -,;|"):
            head = raw[:sep]
            lead = re.match(r"\s*" + DATE_RE.pattern + r"\s*[-,;|]?\s*(.*)$", suffix, re.DOTALL)
            if lead:
                suffix_sale_date = lead.group(1)
                misfiled = lead.group(2).strip() or None
            else:
                misfiled = suffix
    date_m = DATE_RE.search(head)
    sale_date = date_m.group(1) if date_m else suffix_sale_date
    name = head
    if date_m:
        name = head[: date_m.start()] + head[date_m.end():]
    name = name.strip().rstrip("-").strip().strip("-").strip()
    return {"name": name, "sale_date": sale_date, "misfiled": misfiled or None}


def parse_customer_name(raw: str) -> dict[str, Any]:
    if not raw:
        return {"name": "", "extracted": "", "looks_like_name": False,
                "land_descriptor": None, "approval_phrase": None, "email_only": False}
    work = raw
    # 1) Distributor approval / reference phrase appended to the name cell
    #    ("Jane - JEMENA APPROVAL #123", "ESSENTIAL APPROVED"): captured verbatim,
    #    never left in the name. Status words are still read by parse_approval (the
    #    caller passes approval_phrase to it). A reference-only phrase (e.g.
    #    "Jemena Approval # 000…") yields no status but is preserved as a note.
    approval_phrase: str | None = None
    am = _NAME_APPROVAL_PHRASE_RE.search(work)
    if am:
        approval_phrase = work[am.start():].strip(" -,;|")
        work = work[: am.start()].rstrip(" -,;|")
    # 2) Land/legal parcel descriptor ("- Lot 7 DP 123", "-Lot 5"): never part of
    #    the name; captured verbatim regardless of separator style.
    land_descriptor: str | None = None
    lm = LAND_DESCRIPTOR_RE.search(work)
    if lm:
        land_descriptor = work[lm.start():].strip(" -,;|")
        work = work[: lm.start()].rstrip(" -,;|")
    # 2b) Generic non-name suffixes (DOB / date-of-birth, a bare trailing date,
    #     "pillar <id>", an export-limit annotation, a "finalise to <retailer>"
    #     instruction): peeled off the END of the name, preserved VERBATIM, and
    #     never coerced into a structured field. Looped so several can be removed;
    #     accumulated right-to-left then reversed back to reading order.
    suffix_notes: list[str] = []
    _trailing_date_rx = _NAME_SUFFIX_NOTE_RES[-1]
    for _ in range(8):
        for rx in _NAME_SUFFIX_NOTE_RES:
            sm = rx.search(work)
            if not (sm and work[sm.start():].strip(" -,;|")):
                continue
            # A trailing date that follows PENDING / approval is the approval date,
            # not a bare note — leave it adjacent so parse_approval keeps it.
            if rx is _trailing_date_rx and _APPROVAL_DATE_TAIL_RE.search(work[: sm.start()]):
                continue
            suffix_notes.append(work[sm.start():].strip(" -,;|"))
            work = work[: sm.start()].rstrip(" -,;|")
            break
        else:
            break
    suffix_notes.reverse()
    # 3) Remaining trailing notes via the existing stop-marker split.
    idxs = [work.find(m) for m in NAME_STOP_MARKERS if work.find(m) > 0]
    # A1: a bare date still sitting mid-cell (glued to / following the name without
    # a standard stop-marker, e.g. "Naomi Carter- 18/4/75 - DL ...") is never part
    # of the name — cut at the date's separator so the date + trailing text become a
    # preserved note. Skip when the date is the approval PENDING date (it must stay
    # adjacent to its keyword for parse_approval to read it).
    dm = _NAME_DATE_SPLIT_RE.search(work)
    if dm and dm.start() > 0 and not _APPROVAL_DATE_TAIL_RE.search(work[: dm.start(1)]):
        idxs.append(dm.start())
    cut = min(idxs) if idxs else len(work)
    name = work[:cut].strip()
    extracted = work[cut:].strip(" -")
    # Fold the generic suffix notes into the preserved trailing text so they flow
    # to customer_name_notes (and thus the post-commit internal_notes safety net).
    if suffix_notes:
        joined = " - ".join(suffix_notes)
        extracted = f"{extracted} - {joined}" if extracted else joined
    # The remove-old-system / decommission marker is detected separately (and the
    # flag/banner set) — it must never remain in the customer name. It can be glued
    # to the name without a stop-marker (e.g. "Jane Roe -remove old system"), which
    # the NAME_STOP_MARKERS split does not catch, so strip it here + any orphaned
    # separator. Non-marker name text and standalone dates are preserved.
    if DECOMMISSION_RE.search(name):
        name = re.sub(r"\s+", " ", DECOMMISSION_RE.sub(" ", name)).strip(" -,;|")
    # An email address filling the WHOLE name cell is a data-quality error, not a
    # name: parse_rows flags it blocking so it cannot commit as a customer name.
    email_only = bool(_EMAIL_TOKEN_RE.search(name)) and not _EMAIL_TOKEN_RE.sub("", name).strip(" -,;|")
    looks_like_name = (
        bool(name) and name[0].isalpha()
        and not re.match(r"(?i)^(ref|essential|ergon|energex|approved|pending|lot)\b", name)
        and not email_only
    )
    return {
        "name": name,
        "extracted": extracted,
        "looks_like_name": looks_like_name,
        "land_descriptor": land_descriptor or None,
        "approval_phrase": approval_phrase or None,
        "email_only": email_only,
    }


def clean_name_cell_notes(extracted: str) -> str:
    """Strip pure approval tokens (APPROVED / PENDING[date]) AND decommission /
    remove-old-system markers from the name-cell trailing text, leaving the
    meaningful remainder (e.g. 'includes hot water timer', 'undersold Brighte
    fees, check after install'). The decommission flag is still detected
    independently by detect_decommission(); stripping here only stops the marker
    from being duplicated into customer_name_notes. All other text — including any
    standalone date — is preserved verbatim. Returns '' when nothing meaningful
    remains."""
    if not extracted:
        return ""
    cleaned = _APPROVAL_TOKEN_RE.sub(" ", extracted)
    # A3: an approval-ACTION phrase ("DO APPROVAL", "NEEDS APPROVAL", ...) is
    # classified as approval_required by parse_approval — drop the bare phrase here
    # so it is not ALSO preserved as a note. Surrounding operational context (e.g.
    # "TECHNAUS POWERCOR PORTAL", a contact name) is left intact.
    cleaned = APPROVAL_ACTION_RE.sub(" ", cleaned)
    # Remove the decommission/remove-old-system marker text only; the flag is set
    # separately, and any other note content (incl. standalone dates) is kept.
    cleaned = DECOMMISSION_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Collapse separators orphaned where a stripped phrase was removed from the
    # middle of the note ("timer - ESSENTIAL APPROVED - ref" -> "timer - ref").
    cleaned = re.sub(r"(?:\s*[-,;|]\s*){2,}", " - ", cleaned)
    return cleaned.strip(" -,;|")


def detect_decommission(*texts: str) -> str | None:
    """Return the matched old-system removal / decommission marker text found in
    any of the given cell texts (for reviewer visibility), else None. Purely
    additive signal — it never blocks a commit."""
    for t in texts:
        if not t:
            continue
        m = DECOMMISSION_RE.search(t)
        if m:
            return m.group(0)
    return None


def parse_approval(*texts: str) -> dict[str, Any]:
    """Approval state from any of the given texts (name-cell approval phrase,
    name-cell trailing notes, the Notes column).

    Order matters: an approval-ACTION phrase ("DO APPROVAL", "NEEDS APPROVAL", ...)
    means approval is still OUTSTANDING -> "required" and is checked first; then an
    explicit APPROVED word; then a PENDING word (with an optional date); then a
    distributor approval REFERENCE number (e.g. "Jemena Approval # 000413493") which
    also means approved. No evidence -> "none" (the caller assigns no approval
    label). DOB/other digit runs do not trip the reference rule — it needs a
    #/No/Ref marker or a long (6+ digit) number."""
    blob = " ".join(t for t in texts if t)
    # A3: an explicit instruction to OBTAIN approval ("DO APPROVAL", "NEEDS
    # APPROVAL", ...) means the connection is NOT yet approved -> approval_required.
    # Checked first so a name-cell action phrase is never mis-read as approved.
    if APPROVAL_ACTION_RE.search(blob):
        return {"state": "required", "pending_date": None}
    if APPROVAL_APPROVED_RE.search(blob):
        return {"state": "approved", "pending_date": None}
    pend = APPROVAL_PENDING_RE.search(blob)
    if pend:
        return {"state": "pending", "pending_date": pend.group(1)}
    if APPROVAL_REFERENCE_RE.search(blob):
        return {"state": "approved", "pending_date": None}
    return {"state": "none", "pending_date": None}


def parse_phones(raw: str) -> dict[str, Any]:
    if not raw:
        return {"numbers": [], "labelled": False}
    out: list[dict[str, str]] = []
    labelled = False
    for part in re.split(r"[/]", raw):
        part = part.strip()
        if not part:
            continue
        nums = re.findall(r"\+?\d[\d\s]{6,}\d", part)
        label = re.sub(r"\+?\d[\d\s]{6,}\d", "", part).strip(" -")
        if not nums:
            continue
        explicit = bool(label) and any(ch.isalpha() for ch in label)
        labelled = labelled or explicit
        for n in nums:
            out.append({"number": re.sub(r"\s+", "", n), "label": label if explicit else ""})
    return {"numbers": out, "labelled": labelled}


def parse_emails(raw: str) -> list[str]:
    if not raw:
        return []
    return [e.strip() for e in raw.split("/") if e.strip() and e.strip().lower() not in {"n/a", "na"}]


def parse_address(raw: str) -> dict[str, Any]:
    """Conservatively split an Australian address into line1 / suburb / state /
    postcode. Pure; never discards text.

    It ONLY structures when a reliable trailing "STATE POSTCODE" (or
    "POSTCODE STATE") anchor is present; otherwise it returns the whole raw string
    as ``line1`` with the other parts blank and ``structured=False`` (the owner's
    rule: keep the raw address rather than over-confidently mangle a weird one).

    With the anchor found, the suburb is the segment after the LAST comma in the
    remaining head; the street (incl. any Lot/DP/legal descriptor, preserved
    verbatim) is everything before that comma. If the head has no comma we cannot
    confidently separate suburb from street, so the whole head stays as ``line1``
    and ``suburb`` is left blank — never guessed. line1 + suburb + state +
    postcode always reconstruct the original (no text is lost)."""
    s = (raw or "").strip()
    out: dict[str, Any] = {
        "line1": s or None, "suburb": None, "state": None,
        "postcode": None, "structured": False,
    }
    if not s:
        out["line1"] = None
        return out
    m = _ADDR_TAIL_RE.search(s)
    if not m:
        return out  # no reliable anchor -> keep the raw line, structure nothing
    state = (m.group("state1") or m.group("state2") or "").upper()
    postcode = m.group("pc1") or m.group("pc2")
    head = s[: m.start()].strip().rstrip(",").strip()
    if "," in head:
        street, suburb = head.rsplit(",", 1)
        out["line1"] = street.strip().rstrip(",").strip() or None
        out["suburb"] = suburb.strip() or None
    else:
        # No comma: can't split suburb from street without guessing — keep head.
        out["line1"] = head or None
    out["state"] = state
    out["postcode"] = postcode
    out["structured"] = True
    return out


def parse_date_maybe(raw: str) -> date | None:
    raw = raw.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"([0-3]?\d)[/\-]([0-1]?\d)[/\-](\d{2,4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def hardware_confidence(raw: str, brand_hints: tuple[str, ...]) -> str:
    t = raw.strip().lower()
    if t in {"", "-", "/", "0", "n/a"}:
        return "none"
    has_brand = any(h in t for h in brand_hints)
    has_number = bool(re.search(r"\d", t))
    if has_brand and has_number:
        return "confident"
    return "uncertain"


# --------------------------------------------------------------------------- #
# Header detection + column mapping
# --------------------------------------------------------------------------- #
def find_header_row(ws, max_scan: int = 6) -> int | None:
    for r in range(1, max_scan + 1):
        seen = {
            norm_cell(ws.cell(r, c).value).lower().rstrip("?: ").strip()
            for c in range(1, ws.max_column + 1)
        }
        if "customer name" in seen and "nmi" in seen:
            return r
    return None


def build_colmap(ws, header_row: int) -> dict[str, int]:
    colmap: dict[str, int] = {"ref": 1}
    for c in range(1, ws.max_column + 1):
        key = norm_cell(ws.cell(header_row, c).value).lower().rstrip("?: ").strip()
        if key in WANTED_HEADERS:
            colmap[WANTED_HEADERS[key]] = c
    return colmap


# --------------------------------------------------------------------------- #
# Row classification + parsing
# --------------------------------------------------------------------------- #
def _classify(ref: str, nonempty: int, name_info: dict) -> str:
    if nonempty == 0:
        return "blank"
    if ref and not REF_RE.match(ref):
        if any(h in ref.upper() for h in DIVIDER_HINTS) or nonempty <= 2:
            return "divider"
    if REF_RE.match(ref):
        return "job"
    if name_info["name"] and nonempty <= 3:
        return "ambiguous"
    return "job" if nonempty >= 5 else "ambiguous"


def parse_rows(ws) -> Iterator[ParsedRow]:
    """Yield a ParsedRow per spreadsheet data row (after the header).

    Raises ValueError if the COMPLETED-style header cannot be located.
    """
    # Deferred import avoids a parser<->details import cycle.
    from app.services.import_details import build_details

    header_row = find_header_row(ws)
    if header_row is None:
        raise ValueError("Could not locate a header row (expected 'Customer Name' + 'NMI').")
    cm = build_colmap(ws, header_row)

    # Columns NOT mapped to a canonical key: preserved verbatim in raw['_unmapped']
    # so no workbook column is ever silently dropped (Phase 2a full-capture).
    mapped_cols = set(cm.values())
    unmapped_cols: dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        if c in mapped_cols:
            continue
        header = norm_cell(ws.cell(header_row, c).value)
        if header:
            unmapped_cols[header] = c

    def get(row: int, key: str) -> str:
        c = cm.get(key)
        return norm_cell(ws.cell(row, c).value) if c else ""

    current_context = ""
    for r in range(header_row + 1, ws.max_row + 1):
        raw = {key: get(r, key) for key in cm}
        extra = {h: norm_cell(ws.cell(r, c).value) for h, c in unmapped_cols.items()}
        extra = {h: v for h, v in extra.items() if v}
        if extra:
            raw["_unmapped"] = extra
        nonempty = sum(1 for c in range(1, min(ws.max_column, 40) + 1) if norm_cell(ws.cell(r, c).value))
        ref = raw.get("ref", "")
        name_info = parse_customer_name(get(r, "customer_name"))
        klass = _classify(ref, nonempty, name_info)

        if klass == "blank":
            yield ParsedRow(r, klass, ref, raw, {}, None, [])
            continue
        if klass == "divider":
            current_context = ref or name_info["name"]
            yield ParsedRow(r, klass, ref, raw, {}, current_context or None, [])
            continue

        sales = parse_sales_consultant(get(r, "sales_consultant"))
        phones = parse_phones(get(r, "phone"))
        emails = parse_emails(get(r, "email"))
        nmi_raw = get(r, "nmi")
        dist_inferred, _prefix = infer_distributor(nmi_raw)
        dist_raw = get(r, "distributor")
        # Include the name-cell approval phrase (e.g. "ESSENTIAL APPROVED",
        # "JEMENA PENDING 12/3/26") so status words still set approval_state even
        # though the phrase has been separated out of the customer name.
        approval = parse_approval(
            name_info.get("approval_phrase") or "", name_info["extracted"], get(r, "notes")
        )
        # Meaningful non-name trailing text from the Customer Name cell, with pure
        # approval status removed (the approval is captured separately above).
        name_cell_notes = clean_name_cell_notes(name_info["extracted"])
        # Old-system removal / decommission: scan the whole name cell + the notes
        # column so it is caught whether or not it followed a name stop-marker.
        decommission_marker = detect_decommission(
            get(r, "customer_name"), name_info["extracted"], get(r, "notes")
        )
        msb_raw = get(r, "msb")
        panel_raw = get(r, "panel_brand")
        inverter_raw = get(r, "inverter")

        parsed = {
            "legacy_reference": ref,
            "salesperson": sales["name"],
            "sale_date": sales["sale_date"],
            # Non-name suffix from the Sales Consultant cell (payment/system/note
            # text) — preserved verbatim as a misfiled note by build_details.
            "sales_consultant_misfiled": sales.get("misfiled"),
            "customer_name": name_info["name"],
            "name_extracted_notes": name_info["extracted"] or None,
            # Suffixes lifted out of the Customer Name cell — preserved verbatim as
            # misfiled notes (source_column 'Customer Name') by build_details.
            "name_cell_land_descriptor": name_info.get("land_descriptor"),
            "name_cell_approval_phrase": name_info.get("approval_phrase"),
            # Reviewer-visible/editable preserved note (approval status removed).
            "customer_name_notes": name_cell_notes or None,
            # Operationally important old-system removal flag + the matched text.
            "removes_old_system": decommission_marker is not None,
            "decommission_marker": decommission_marker,
            "address": get(r, "address") or None,
            # Conservatively split AU address (line1/suburb/state/postcode). The
            # commit mapping can populate Customer.suburb/state/postcode from this
            # on a future re-ingest; the raw `address` above is retained verbatim.
            "address_parts": parse_address(get(r, "address")),
            "approval_state": approval["state"],
            "approval_pending_date": approval["pending_date"],
            "phones": phones["numbers"],
            "emails": emails,
            "msb_state": parse_msb(msb_raw),
            "msb_raw": msb_raw or None,
            "distributor_raw": dist_raw or None,
            "distributor_inferred": dist_inferred,
            "retailer_raw": get(r, "retailer") or None,
            "nmi_raw": nmi_raw or None,
            "meter_no": get(r, "meter_no") or None,
            "no_of_panels": get(r, "no_of_panels") or None,
            "panel_raw": panel_raw or None,
            "panel_confidence": hardware_confidence(panel_raw, PANEL_BRAND_HINTS),
            "inverter_raw": inverter_raw or None,
            "inverter_confidence": hardware_confidence(inverter_raw, INVERTER_BRAND_HINTS),
            "install_date": get(r, "date") or None,
            "install_day": get(r, "day") or None,
            "install_time": get(r, "time") or None,
            "installer_raw": get(r, "installer") or None,
            "payment": {
                "total": get(r, "total") or None,
                "deposit": get(r, "deposit") or None,
                "balance": get(r, "balance") or None,
                "result": get(r, "result_of_payment") or None,
                "notes": get(r, "notes_on_payment") or None,
            },
            "compliance": {
                "accreditation_code": get(r, "accreditation_code") or None,
                "welcome_call": get(r, "welcome_call") or None,
            },
            "notes_raw": get(r, "notes") or None,
        }

        issues: list[dict[str, str]] = []

        def add(kind: str, severity: str, fld: str, msg: str) -> None:
            issues.append({"kind": kind, "severity": severity, "field": fld, "message": msg})

        if name_info.get("email_only"):
            add("email_only_name", "error", "customer_name",
                f"email-only name cell: {name_info['name']!r}")
        elif not name_info["looks_like_name"]:
            add("ambiguous_name", "error", "customer_name", f"name={name_info['name']!r}")
        if len(phones["numbers"]) > 1:
            add("multi_phone", "info", "phone", f"{len(phones['numbers'])} numbers")
        if len(emails) > 1:
            add("multi_email", "info", "email", f"{len(emails)} emails")
        if nmi_raw and dist_inferred is None:
            add("nmi_unmatched", "warning", "nmi", f"nmi={nmi_raw!r}")
        if dist_raw and dist_inferred and dist_inferred.split()[-1].lower() not in dist_raw.lower():
            add("distributor_mismatch", "warning", "distributor", f"{dist_raw!r} vs {dist_inferred!r}")
        if parsed["inverter_confidence"] == "uncertain" and inverter_raw:
            add("hardware_uncertain", "info", "inverter", f"{inverter_raw[:40]!r}")
        if approval["state"] == "pending" and not approval["pending_date"]:
            add("approval_pending_no_date", "warning", "approval", "pending with no date")
        d_parsed = parse_date_maybe(parsed["install_date"] or "")
        if d_parsed and parsed["install_day"]:
            if d_parsed.strftime("%A").lower() != parsed["install_day"].strip().lower():
                add("date_day_mismatch", "warning", "install_date",
                    f"{parsed['install_date']} is {d_parsed.strftime('%A')}, day says {parsed['install_day']!r}")

        # Phase 2a: registry-shaped structured candidate alongside the flat keys
        # (the flat keys stay for back-compat; commit-to-live is unchanged).
        parsed["details"] = build_details(parsed, raw)

        yield ParsedRow(r, klass, ref, raw, parsed, current_context or None, issues)
