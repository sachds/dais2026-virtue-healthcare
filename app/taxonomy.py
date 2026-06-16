"""Clinical service-line taxonomy.

Classifies a facility's standardized `specialties` and free-text `procedure`
entries into seven service categories, and maps stated ward bed-counts to those
categories. Deterministic + rule-based so it's auditable (this is a data-readiness
feature — the planner must be able to see *why* a provider was categorized).

  medical · surgical · obgyn · pediatrics · dental · diagnostic · other
"""
from __future__ import annotations

import re

CATEGORIES = ["medical", "surgical", "obgyn", "pediatrics", "dental", "diagnostic", "other"]
CATEGORY_LABEL = {"medical": "Medical", "surgical": "Surgical", "obgyn": "OB/GYN",
                  "pediatrics": "Pediatrics", "dental": "Dental",
                  "diagnostic": "Diagnostic", "other": "Other"}

# Ordered rules on a normalized specialty (lowercased, alpha-only). First match wins.
# Specific buckets first (dental/obgyn/peds/diagnostic); then MEDICAL before SURGICAL —
# medical specialties carry an explicit keyword (neurolog/gastroenterolog/…), while true
# surgical ones don't, so this avoids greedy substrings (e.g. "urolog" ⊂ "ne-urolog-y").
_SPEC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("dent", "odont", "oralandmaxillofacial", "oralsurg", "oralpath", "prosthodont", "endodont"), "dental"),
    (("obstetr", "gynec", "gynaec", "reproductiveendocrin", "maternalfetal", "midwif", "fertility"), "obgyn"),
    (("pediatr", "paediatr", "neonat", "perinat"), "pediatrics"),
    (("radiolog", "patholog", "laborator", "nuclearmedicine", "cytolog", "microbiolog", "biochem"), "diagnostic"),
    (("internalmedicine", "familymedicine", "generalmedicine", "generalpractice", "cardiolog", "nephrolog",
      "gastroenterolog", "hepatolog", "neurolog", "endocrin", "diabet", "pulmonolog", "respiratory",
      "dermatolog", "oncolog", "hematolog", "haematolog", "rheumatolog", "infectious", "geriatr",
      "immunolog", "allerg", "psychiatr", "psycholog", "palliat", "painmedicine", "physicalmedicine",
      "rehabilitation", "sportsmedicine", "sleepmedicine", "criticalcare", "intensiv", "emergencymedicine",
      "anesthe", "anaesthe", "venereolog", "androlog", "hospitalmedicine"), "medical"),
    (("surg", "urolog", "otolaryngolog", "ophthalmolog", "orthopedic", "orthopaedic"), "surgical"),
]

# Ordered keyword rules on free-text procedure / capability descriptions.
_PROC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("cesarean", "caesarean", "c-section", "childbirth", "obstetric", "labour ward", "labor ward",
      "hysterectom", "prenatal", "antenatal", "gynaecolog", "gynecolog", "normal delivery", "lscs"), "obgyn"),
    (("root canal", "dental implant", "orthodont", "denture", "tooth extraction", "dental crown",
      "scaling and polishing", "oral and maxillofacial"), "dental"),
    (("neonat", "newborn", "paediatric", "pediatric", "nicu", "picu"), "pediatrics"),
    (("ct scan", "mri", "x-ray", "x ray", "ultrasound", "sonograph", "imaging", "mammogra", "biopsy",
      "endoscop", "colonoscop", "angiograph", "blood test", "lab test", "laboratory", "screening test",
      "diagnostic"), "diagnostic"),
    (("surgery", "surgical", "operating theat", "operation theat", "resection", "replacement", "transplant",
      "angioplasty", "bypass", "laparoscop", "arthroscop", "craniotom", "thrombectom", "stenting", "ablation",
      "grafting", "amputation", "fixation", "excision", "appendectom", "cholecystectom", "removal of"), "surgical"),
    (("chemotherap", "dialysis", "infusion", "radiation therap", "radiotherap", "vaccinat", "immuniz",
      "medication", "management of", "treatment for", "therapy"), "medical"),
]

# Ward / unit names (as they appear in bed-count text) → category, for mapping
# stated "N-bed <ward>" counts onto the service categories.
_WARD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("nicu", "picu", "paediatric", "pediatric", "neonat"), "pediatrics"),
    (("maternit", "obstetr", "labour", "labor ", "lying-in", "gynae", "gynec"), "obgyn"),
    (("dental",), "dental"),
    (("surgical", "surgery", "operation theat", "post-op", "postoperative"), "surgical"),
    (("icu", "hdu", "ccu", "intensive", "critical", "dialysis", "cardiac", "oncolog", "cancer",
      "medical", "general ward", "emergency", "casualty", "isolation", "ward"), "medical"),
]

# The six Trust-Desk capabilities → specialty keywords that corroborate them. Used
# for the cardinality cross-check: a capability claim is only as trustworthy as the
# number of relevant specialists on record (0 oncologists ⇒ "strong oncology" is hollow).
CAPABILITY_SPECIALTIES: dict[str, tuple[str, ...]] = {
    "icu": ("criticalcare", "intensiv", "anesthe", "anaesthe", "pulmonolog"),
    "maternity": ("obstetr", "gynec", "gynaec", "maternalfetal", "midwif"),
    "emergency": ("emergencymedicine", "criticalcare", "traumasurg"),
    "oncology": ("oncolog", "hematolog", "haematolog", "radiationoncolog"),
    "trauma": ("trauma", "orthopedic", "orthopaedic", "neurosurg", "generalsurg", "emergencymedicine"),
    "nicu": ("neonat", "perinat", "pediatr", "paediatr"),
}

_norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())  # noqa: E731


def classify_specialty(s: str) -> str:
    n = _norm(s)
    if not n:
        return "other"
    for keys, cat in _SPEC_RULES:
        if any(k in n for k in keys):
            return cat
    return "other"


def classify_procedure(text: str) -> str:
    t = (text or "").lower()
    if not t.strip():
        return "other"
    for keys, cat in _PROC_RULES:
        if any(k in t for k in keys):
            return cat
    return "other"


def count_capability_specialists(specialties: list[str]) -> dict[str, int]:
    """Per Trust-Desk capability, how many of the facility's specialties corroborate it
    — the cardinality cross-check. Dental specialties are excluded so a pediatric-dentist
    doesn't count toward NICU."""
    norm = [_norm(s) for s in specialties if _norm(s) and classify_specialty(s) != "dental"]
    return {cap: sum(1 for n in norm if any(k in n for k in keys))
            for cap, keys in CAPABILITY_SPECIALTIES.items()}


def _ward_category(label: str) -> str:
    t = (label or "").lower()
    for keys, cat in _WARD_RULES:
        if any(k in t for k in keys):
            return cat
    return "other"


_BED_RE = re.compile(r"(\d{1,4})\s*-?\s*bed(?:ded|s)?\s+([a-z/&\- ]{3,40})", re.I)


def extract_category_beds(text: str) -> dict[str, int]:
    """Pull stated '<N>-bed <ward>' counts from free text and map each ward to a
    category. Sparse by nature (only what the record states), but real."""
    out: dict[str, int] = {}
    for m in _BED_RE.finditer(text or ""):
        n = int(m.group(1))
        if 0 < n <= 5000:
            cat = _ward_category(m.group(2))
            out[cat] = out.get(cat, 0) + n
    return out
