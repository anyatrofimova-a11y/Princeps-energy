"""
Planning NLP — Extract structured data from UK planning documents.

Industry-standard docket NLP targeting 95%+ precision on regulatory filings.
Handles: planning decisions, connection offers, EIA screening, G99 packs.
"""

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

log = logging.getLogger(__name__)

# ── Compiled regex patterns ──────────────────────────────────────────────────

# Planning references
RE_LPA_REF = re.compile(r'\b(\d{2}/\d{4,6}/[A-Z]{2,5})\b')
RE_PINS_REF = re.compile(r'\b(APP/[A-Z]\d{4}/[A-Z]/\d{2}/\d{5,7})\b')
RE_NSIP_REF = re.compile(r'\b(EN\d{6})\b')
RE_ANY_REF = re.compile(r'\b((?:\d{2}/\d{4,6}/[A-Z]{2,5})|(?:APP/[A-Z]\d{4}/[A-Z]/\d{2}/\d{5,7})|(?:EN\d{6}))\b')

# Capacity
RE_MW = re.compile(r'(\d+(?:\.\d+)?)\s*(?:MW|megawatt)s?\b', re.I)
RE_KW = re.compile(r'(\d+(?:\.\d+)?)\s*(?:kW|kilowatt)s?\b', re.I)
RE_MWH = re.compile(r'(\d+(?:\.\d+)?)\s*(?:MWh|megawatt[- ]?hour)s?\b', re.I)
RE_MWP = re.compile(r'(\d+(?:\.\d+)?)\s*(?:MWp|megawatt[- ]?peak)\b', re.I)
RE_GW = re.compile(r'(\d+(?:\.\d+)?)\s*(?:GW|gigawatt)s?\b', re.I)

# Voltage
RE_VOLTAGE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:kV|kilovolt)s?\b', re.I)
RE_VOLTAGE_NAMED = re.compile(r'(11|33|66|132|275|400)\s*kV', re.I)

# Technology
RE_SOLAR = re.compile(r'\b(?:solar|photovoltaic|PV|solar\s*farm|solar\s*park)\b', re.I)
RE_WIND = re.compile(r'\b(?:wind\s*(?:farm|turbine|energy)|onshore\s*wind|offshore\s*wind)\b', re.I)
RE_BESS = re.compile(r'\b(?:battery|BESS|energy\s*storage|battery\s*storage)\b', re.I)
RE_DC = re.compile(r'\b(?:data\s*cent(?:re|er)|hyperscale|colocation|colo)\b', re.I)

# Decision
RE_GRANTED = re.compile(r'\b(?:granted|approved|permission\s*granted|consent\s*granted)\b', re.I)
RE_REFUSED = re.compile(r'\b(?:refused|rejected|permission\s*refused|consent\s*refused)\b', re.I)
RE_WITHDRAWN = re.compile(r'\b(?:withdrawn|application\s*withdrawn)\b', re.I)
RE_APPEAL = re.compile(r'\b(?:appeal\s*(?:allowed|dismissed|decision))\b', re.I)

# Grid connection
RE_G99 = re.compile(r'\b(?:G99|G/99|ENA\s*G99)\b', re.I)
RE_G100 = re.compile(r'\b(?:G100|G/100|ENA\s*G100)\b', re.I)
RE_MPAN = re.compile(r'\b(\d{13})\b')
RE_MEC = re.compile(r'\bMEC[:\s]*(\d+(?:\.\d+)?)\s*(?:kW|MW)\b', re.I)
RE_MIC = re.compile(r'\bMIC[:\s]*(\d+(?:\.\d+)?)\s*(?:kW|MW)\b', re.I)

# EIA
RE_EIA_SCREENING = re.compile(r'\b(?:EIA\s*screening|screening\s*opinion|Schedule\s*2)\b', re.I)
RE_EIA_SCOPING = re.compile(r'\b(?:EIA\s*scoping|scoping\s*opinion|environmental\s*statement)\b', re.I)
RE_EIA_REQUIRED = re.compile(r'\b(?:EIA\s*(?:is\s*)?required|environmental\s*impact\s*assessment\s*required)\b', re.I)
RE_EIA_NOT_REQUIRED = re.compile(r'\b(?:EIA\s*(?:is\s*)?not\s*required|not\s*EIA\s*development)\b', re.I)

# BNG
RE_BNG = re.compile(r'\b(?:biodiversity\s*net\s*gain|BNG|biodiversity\s*metric)\b', re.I)
RE_BNG_SCORE = re.compile(r'BNG[^.]*?(\d+(?:\.\d+)?)\s*%', re.I)
RE_HABITAT_UNITS = re.compile(r'(\d+(?:\.\d+)?)\s*(?:habitat\s*units|biodiversity\s*units)', re.I)

# Dates
RE_UK_DATE = re.compile(r'\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{4})\b', re.I)
RE_DATE_SLASH = re.compile(r'\b(\d{2}/\d{2}/\d{4})\b')

# Conditions
RE_CONDITIONS = re.compile(r'(?:subject\s*to|conditions?\s*(?:\d+)?[:\s])(.*?)(?=\n\n|\Z)', re.I | re.S)

# LPA names
UK_LPAS = [
    "Westminster", "Camden", "Islington", "Tower Hamlets", "Hackney", "Southwark",
    "Lambeth", "Wandsworth", "Richmond", "Kingston", "Merton", "Sutton", "Croydon",
    "Bromley", "Greenwich", "Lewisham", "Bexley", "Barking", "Havering", "Newham",
    "Redbridge", "Waltham Forest", "Haringey", "Enfield", "Barnet", "Harrow",
    "Hillingdon", "Ealing", "Hounslow", "Hammersmith", "Kensington",
    "Birmingham", "Manchester", "Leeds", "Sheffield", "Bristol", "Liverpool",
    "Newcastle", "Nottingham", "Leicester", "Coventry", "Bradford", "Stoke",
    "Wolverhampton", "Plymouth", "Derby", "Southampton", "Portsmouth", "Oxford",
    "Cambridge", "York", "Bath", "Canterbury", "Chester", "Durham", "Exeter",
    "Gloucester", "Lancaster", "Lincoln", "Norwich", "Salisbury", "Winchester",
    "Worcester", "Carlisle", "Ely", "Hereford", "Lichfield", "Peterborough",
    "Preston", "Ripon", "Truro", "Wakefield", "Wells",
]

# DNO names
DNOS = ["UKPN", "SSEN", "NGED", "NPG", "ENWL", "SPEN", "SP Energy Networks",
        "UK Power Networks", "Scottish & Southern", "National Grid", "Northern Powergrid",
        "Electricity North West"]


@dataclass
class PlanningDecision:
    reference: Optional[str] = None
    application_type: Optional[str] = None
    site_address: Optional[str] = None
    applicant: Optional[str] = None
    lpa: Optional[str] = None
    decision: Optional[str] = None
    decision_date: Optional[str] = None
    technology: Optional[str] = None
    capacity_mw: Optional[float] = None
    capacity_mwh: Optional[float] = None
    voltage_kv: Optional[float] = None
    conditions_count: int = 0
    conditions_text: Optional[str] = None
    eia_required: Optional[bool] = None
    bng_score: Optional[float] = None
    g99_referenced: bool = False
    key_dates: list = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None and v != 0 and v != [] and v != False}


@dataclass
class ConnectionOffer:
    reference: Optional[str] = None
    dno: Optional[str] = None
    mpan: Optional[str] = None
    site_address: Optional[str] = None
    capacity_mw: Optional[float] = None
    voltage_kv: Optional[float] = None
    connection_charge_gbp: Optional[float] = None
    mec_kw: Optional[float] = None
    mic_kw: Optional[float] = None
    g99_applicable: bool = False
    estimated_completion: Optional[str] = None
    substation: Optional[str] = None
    confidence: float = 0.0

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None and v != 0 and v != False}


def _detect_technology(text: str) -> Optional[str]:
    if RE_SOLAR.search(text): return "solar"
    if RE_WIND.search(text): return "wind"
    if RE_BESS.search(text): return "bess"
    if RE_DC.search(text): return "data_centre"
    return None


def _extract_capacity(text: str) -> Optional[float]:
    for m in RE_GW.finditer(text):
        return float(m.group(1)) * 1000
    for m in RE_MWP.finditer(text):
        return float(m.group(1))
    for m in RE_MW.finditer(text):
        return float(m.group(1))
    for m in RE_KW.finditer(text):
        return float(m.group(1)) / 1000
    return None


def _extract_dates(text: str) -> list:
    dates = []
    for m in RE_UK_DATE.finditer(text):
        dates.append(f"{m.group(1)} {m.group(2)} {m.group(3)}")
    for m in RE_DATE_SLASH.finditer(text):
        dates.append(m.group(1))
    return dates[:10]


def _detect_lpa(text: str) -> Optional[str]:
    text_lower = text.lower()
    for lpa in UK_LPAS:
        if lpa.lower() in text_lower:
            # Check it's in context (e.g., "X Council", "X Borough")
            pattern = re.compile(rf'\b{re.escape(lpa)}\b.*?(?:Council|Borough|District|County|City)', re.I)
            m = pattern.search(text)
            if m:
                return m.group(0).strip()
    return None


def extract_planning_decision(text: str) -> dict:
    """Parse a UK planning decision notice into structured data."""
    result = PlanningDecision()
    fields_found = 0

    # Reference
    m = RE_PINS_REF.search(text)
    if m:
        result.reference = m.group(1)
        result.application_type = "appeal"
        fields_found += 1
    else:
        m = RE_NSIP_REF.search(text)
        if m:
            result.reference = m.group(1)
            result.application_type = "nsip"
            fields_found += 1
        else:
            m = RE_LPA_REF.search(text)
            if m:
                result.reference = m.group(1)
                result.application_type = "full" if "/FUL" in m.group(1) else "outline"
                fields_found += 1

    # Decision
    if RE_GRANTED.search(text):
        result.decision = "approved"
        fields_found += 1
    elif RE_REFUSED.search(text):
        result.decision = "refused"
        fields_found += 1
    elif RE_WITHDRAWN.search(text):
        result.decision = "withdrawn"
        fields_found += 1

    # Technology & capacity
    result.technology = _detect_technology(text)
    if result.technology:
        fields_found += 1
    result.capacity_mw = _extract_capacity(text)
    if result.capacity_mw:
        fields_found += 1

    # MWh (storage)
    m = RE_MWH.search(text)
    if m:
        result.capacity_mwh = float(m.group(1))

    # Voltage
    m = RE_VOLTAGE_NAMED.search(text)
    if m:
        result.voltage_kv = float(m.group(1))

    # LPA
    result.lpa = _detect_lpa(text)
    if result.lpa:
        fields_found += 1

    # EIA
    if RE_EIA_NOT_REQUIRED.search(text):
        result.eia_required = False
        fields_found += 1
    elif RE_EIA_REQUIRED.search(text):
        result.eia_required = True
        fields_found += 1

    # BNG
    m = RE_BNG_SCORE.search(text)
    if m:
        result.bng_score = float(m.group(1))

    # G99
    result.g99_referenced = bool(RE_G99.search(text))

    # Dates
    result.key_dates = _extract_dates(text)

    # Conditions
    conditions = RE_CONDITIONS.findall(text)
    if conditions:
        result.conditions_count = len(conditions)
        result.conditions_text = conditions[0][:500]

    # Confidence
    result.confidence = min(1.0, fields_found / 6)

    return result.to_dict()


def extract_connection_offer(text: str) -> dict:
    """Parse a grid connection offer document."""
    result = ConnectionOffer()

    # DNO
    text_lower = text.lower()
    for dno in DNOS:
        if dno.lower() in text_lower:
            result.dno = dno
            break

    # MPAN
    m = RE_MPAN.search(text)
    if m:
        result.mpan = m.group(1)

    # Capacity
    result.capacity_mw = _extract_capacity(text)

    # Voltage
    m = RE_VOLTAGE_NAMED.search(text)
    if m:
        result.voltage_kv = float(m.group(1))

    # MEC/MIC
    m = RE_MEC.search(text)
    if m:
        result.mec_kw = float(m.group(1))
    m = RE_MIC.search(text)
    if m:
        result.mic_kw = float(m.group(1))

    # G99
    result.g99_applicable = bool(RE_G99.search(text))

    # Connection charge
    charge_re = re.compile(r'£\s*([\d,]+(?:\.\d{2})?)', re.I)
    charges = charge_re.findall(text)
    if charges:
        result.connection_charge_gbp = float(charges[0].replace(",", ""))

    # Substation
    sub_re = re.compile(r'(?:substation|BSP|GSP)[:\s]+([A-Za-z\s]+?)(?:\.|,|\n)', re.I)
    m = sub_re.search(text)
    if m:
        result.substation = m.group(1).strip()

    result.confidence = sum(1 for v in [result.dno, result.mpan, result.capacity_mw, result.voltage_kv] if v) / 4

    return result.to_dict()


def classify_document(text: str) -> str:
    """Classify document type from text content."""
    scores = {
        "planning_decision": 0,
        "connection_offer": 0,
        "environmental_statement": 0,
        "screening_opinion": 0,
        "scoping_opinion": 0,
        "g99_application": 0,
        "unknown": 0,
    }

    if RE_ANY_REF.search(text): scores["planning_decision"] += 3
    if RE_GRANTED.search(text) or RE_REFUSED.search(text): scores["planning_decision"] += 3
    if RE_MPAN.search(text): scores["connection_offer"] += 3
    if RE_MEC.search(text) or RE_MIC.search(text): scores["connection_offer"] += 2
    if any(d.lower() in text.lower() for d in DNOS): scores["connection_offer"] += 2
    if RE_EIA_SCREENING.search(text): scores["screening_opinion"] += 4
    if RE_EIA_SCOPING.search(text): scores["scoping_opinion"] += 4
    if RE_G99.search(text) or RE_G100.search(text): scores["g99_application"] += 3
    if "environmental statement" in text.lower(): scores["environmental_statement"] += 4

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def extract_from_pdf(file_path: str) -> dict:
    """Extract structured data from a PDF file."""
    text = ""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        for page in doc:
            text += page.get_text()
        doc.close()
    except ImportError:
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
        except ImportError:
            return {"error": "Install PyMuPDF or pdfplumber: pip install pymupdf pdfplumber"}

    doc_type = classify_document(text)
    if doc_type == "connection_offer":
        result = extract_connection_offer(text)
    else:
        result = extract_planning_decision(text)

    result["document_type"] = doc_type
    result["pages"] = text.count("\f") + 1
    result["characters"] = len(text)
    return result


def batch_extract(file_paths: list) -> list:
    """Process multiple documents."""
    return [extract_from_pdf(f) for f in file_paths]


def extract_from_text(text: str) -> dict:
    """Auto-classify and extract from raw text."""
    doc_type = classify_document(text)
    if doc_type == "connection_offer":
        result = extract_connection_offer(text)
    else:
        result = extract_planning_decision(text)
    result["document_type"] = doc_type
    return result
