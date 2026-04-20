"""Ownership Certificates A / B / C / D — TCPA DMPO 2015 Art.14.

Every 1APP planning application must be accompanied by an ownership
certificate under **Article 14 of the Town and Country Planning
(Development Management Procedure) (England) Order 2015 (SI 2015/595)**.
The applicant picks exactly one of four certificates depending on their
knowledge of the land ownership and whether notice has been served:

* **Certificate A.** Applicant is the sole owner (freehold or leasehold
  with at least 7 years left to run) of the whole application site, and
  no part is a tenancy of an agricultural holding at the date of
  application. No notice to anyone else is required.
* **Certificate B.** Applicant is an owner but other owners have been
  identified. The applicant has served notice under Art.14(1)(b) on
  every known owner **at least 21 days** before the application date.
* **Certificate C.** Some owners cannot be identified despite reasonable
  enquiry. Notice has been served on every known owner **and** a press
  advertisement has been published under Art.14(2).
* **Certificate D.** No owners can be identified despite reasonable
  enquiry. A press advertisement has been published under Art.14(2)
  and the applicant has taken reasonable steps to ascertain ownership.

For each certificate the declaration that the applicant must sign is
prescribed by Schedule 2 of the DMPO 2015. This module builds a
structured dict that the template renders and that a human signatory
completes at submission.

Default heuristic:

1. If ``override`` is supplied (``"A"|"B"|"C"|"D"``), honour it.
2. Else if a single parcel with ``owner_confirmed=True`` → Certificate A.
3. Else if any parcel has ``owner_confirmed=True`` → Certificate B.
4. Else if there are parcels but no confirmed owners → Certificate C.
5. Else → Certificate D.

The override is read from ``projects.metadata.ownership_cert`` per the
COUNCIL-1 spec.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# Notice window — Art.14(1)(b) DMPO 2015 requires at least 21 days.
ARTICLE_14_NOTICE_DAYS: int = 21

_CERTIFICATE_LABELS: dict[str, str] = {
    "A": "Certificate A — sole owner",
    "B": "Certificate B — notice served on known owners",
    "C": "Certificate C — notice + press advertisement (some owners unknown)",
    "D": "Certificate D — press advertisement only (no owners identifiable)",
}

# Prescribed declaration wording (condensed — full Schedule 2 wording
# remains the legally operative text). Each declaration is stamped into
# the final PDF so the signatory sees what they attest to.
_CERTIFICATE_DECLARATIONS: dict[str, str] = {
    "A": (
        "I certify that on the day 21 days before the date of this application "
        "nobody except the applicant was the owner (as defined in Article 2(1) "
        "of the Town and Country Planning (Development Management Procedure) "
        "(England) Order 2015) of any part of the land to which the application "
        "relates, and no part of the land constitutes or forms part of an "
        "agricultural holding."
    ),
    "B": (
        "I certify that the applicant has given the requisite notice (in "
        "accordance with Article 14(1)(b) of the Town and Country Planning "
        "(Development Management Procedure) (England) Order 2015) to everyone "
        "else who, on the day 21 days before the date of this application, was "
        "the owner of any part of the land to which the application relates, "
        "as listed below."
    ),
    "C": (
        "I certify that the applicant cannot issue a certificate A or B because "
        "some of the owners of the land to which the application relates are "
        "unknown to the applicant. The applicant has taken such steps as are "
        "reasonably open to the applicant (including the publication of a notice "
        "in a newspaper circulating in the locality) to ascertain the names and "
        "addresses of those owners and has been unable to do so."
    ),
    "D": (
        "I certify that the applicant cannot issue a certificate A, B or C "
        "because none of the owners of the land to which the application "
        "relates is known to the applicant. The applicant has taken such steps "
        "as are reasonably open to the applicant (including the publication of "
        "a notice in a newspaper circulating in the locality) to ascertain the "
        "names and addresses of those owners and has been unable to do so."
    ),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_iso() -> str:
    return _now().strftime("%Y-%m-%d")


def _notice_date_iso(days_back: int = ARTICLE_14_NOTICE_DAYS) -> str:
    return (_now() - timedelta(days=days_back)).strftime("%Y-%m-%d")


def _select_certificate(
    parcels: Iterable[dict] | None,
    override: str | None,
) -> tuple[str, str]:
    """Return ``(code, rationale)`` for the selected certificate."""
    if override:
        code = override.strip().upper()
        if code in _CERTIFICATE_LABELS:
            return code, f"Certificate {code} selected via projects.metadata.ownership_cert override."

    parcels = list(parcels or [])
    if not parcels:
        # No parcel data to reason over — fall back to Certificate D (safest
        # worst-case so the press-advertisement step is prepared).
        return "D", "No parcel data linked — press advertisement route flagged for solicitor confirmation."

    n = len(parcels)
    confirmed = [p for p in parcels if p.get("owner_confirmed")]
    if n == 1 and confirmed:
        return "A", "Single parcel with confirmed sole ownership."
    if confirmed:
        return "B", (
            f"Applicant is an owner of {len(confirmed)}/{n} parcels; Article 14(1)(b) "
            "notice required on remaining known owners."
        )
    if any(p.get("owner_partial") or p.get("title_number") for p in parcels):
        return "C", (
            f"{n} parcels linked; some owners identifiable but others unknown — "
            "notice to known owners + press advertisement under Art.14(2)."
        )
    return "D", (
        f"{n} parcels linked without identifiable owners — press advertisement "
        "under Art.14(2); reasonable steps to ascertain ownership required."
    )


def build_ownership_certificate(
    *,
    parcels: Iterable[dict] | None = None,
    applicant: dict | None = None,
    metadata: dict | None = None,
    override: str | None = None,
) -> dict[str, Any]:
    """Build the ownership-certificate sub-form for the planning bundle.

    Args:
        parcels: list of parcel dicts with (optionally) ``owner_confirmed``,
            ``owner_partial``, ``title_number``, ``owner_name``, ``owner_address``.
        applicant: applicant dict — used to populate the signatory block.
        metadata: project metadata dict — the override is read from
            ``ownership_cert`` when supplied.
        override: explicit override of the selected certificate (A/B/C/D).
            Taken from ``metadata.ownership_cert`` when not passed
            directly.

    Returns:
        Dict with:
            * ``certificate_code`` — ``"A"|"B"|"C"|"D"``
            * ``certificate_label`` — human-readable label
            * ``rationale`` — selection rationale
            * ``declaration`` — prescribed wording
            * ``notices_to_owners`` — list of notice records (B/C)
            * ``press_advertisement`` — press-ad record (C/D)
            * ``signatory``, ``signed_on``, ``declaration_made`` — signature block
            * ``article_14_notice_days`` — canonical 21-day window
    """
    applicant = applicant or {}
    metadata = metadata or {}
    override = override or metadata.get("ownership_cert")

    code, rationale = _select_certificate(parcels, override)
    declaration = _CERTIFICATE_DECLARATIONS[code]
    label = _CERTIFICATE_LABELS[code]

    notices: list[dict[str, Any]] | None = None
    if code in ("B", "C"):
        # Build a schedule of notices served on known owners — the
        # signatory adds real names/addresses/dates at submission.
        notice_date = _notice_date_iso()
        notices = []
        for p in (parcels or []):
            if p.get("owner_confirmed") or p.get("owner_partial"):
                notices.append({
                    "owner_name": p.get("owner_name") or "[owner name — to confirm]",
                    "owner_address": p.get("owner_address") or "[owner address — to confirm]",
                    "title_number": p.get("title_number") or "[HMLR title — to confirm]",
                    "notice_served_on": notice_date,
                    "notice_method": "First-class post / hand delivery",
                    "article": "Article 14(1)(b) DMPO 2015",
                })
        if not notices:
            notices.append({
                "owner_name": "[owner name — to confirm]",
                "owner_address": "[owner address — to confirm]",
                "title_number": "[HMLR title — to confirm]",
                "notice_served_on": notice_date,
                "notice_method": "First-class post / hand delivery",
                "article": "Article 14(1)(b) DMPO 2015",
            })

    press_ad: dict[str, Any] | None = None
    if code in ("C", "D"):
        press_ad = {
            "newspaper": metadata.get("press_newspaper") or "[local newspaper — to confirm]",
            "publication_date": metadata.get("press_publication_date") or _today_iso(),
            "copy_attached": bool(metadata.get("press_copy_attached", False)),
            "article": "Article 14(2) DMPO 2015",
            "notes": "Tear-sheet / proof-of-publication must be lodged with the LPA.",
        }

    signatory = applicant.get("name") or metadata.get("signatory_name") or "[signatory — to confirm]"
    return {
        "certificate_code": code,
        "certificate_label": label,
        "rationale": rationale,
        "declaration": declaration,
        "notices_to_owners": notices,
        "press_advertisement": press_ad,
        "signatory": signatory,
        "signatory_role": applicant.get("role") or metadata.get("signatory_role") or "Agent",
        "signed_on": _today_iso(),
        "declaration_made": True,
        "article_14_notice_days": ARTICLE_14_NOTICE_DAYS,
        "regulation_ref": "Town and Country Planning (DMPO) (England) Order 2015 (SI 2015/595) Art.14",
        "generated_at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "disclaimer": (
            "Auto-generated ownership certificate — solicitor must verify "
            "Land Registry OC1 entries and confirm the selected certificate "
            "before submission."
        ),
    }


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    for override in (None, "A", "B", "C", "D"):
        out = build_ownership_certificate(
            parcels=[{"area_m2": 960_000, "owner_confirmed": True}],
            applicant={"name": "Hinton Solar Ltd", "role": "Applicant"},
            override=override,
        )
        print(override or "(auto)", "→", out["certificate_code"], out["rationale"])
    print(json.dumps(
        build_ownership_certificate(parcels=[], applicant={"name": "Test"}, override="C"),
        indent=2,
    ))
