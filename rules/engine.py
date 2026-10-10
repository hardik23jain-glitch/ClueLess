# Deterministic Rules Engine (Backend / P2)

# Class A: Registrability hard stops (objective, refusal-ground style checks)
#   A1  POA used but no registered POA reference
#   A2  Property area / unit missing
#   A3  Property boundaries (N, E, S, W) incomplete
#   A4  Presentation outside the 4-month window after execution
#   A5  Seller / buyer name missing
#   A6  Consideration missing (skipped for gift / will / partition)
#   A7  ULPIN does not match the parent deed
#
# Class B: Title-intelligence advisories (NOT refusal grounds)
#   B0  Registry cross-check unavailable (reported, never silently skipped)
#   B1  Broken link: seller is not the registry's current owner
#   B2  Possible double sale (parallel conveyance in the registry index)
#   B3  Area conservation: draft area strictly greater than parent area
#
# No LLM, no network, no fuzzy matching, no third-party dependencies.

from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import sys
import os

# Hackathon fix: Add the project root to the Python path so it can find 'ledger'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ledger.mock_index import MockRegistry, normalize_name, normalize_ulpin

RULESET_VERSION = "v1.1"   # recorded in every ledger entry for reproducibility

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HARD_STOP = 'HARD_STOP'
WARNING = 'WARNING'

CATEGORY_REGISTRABILITY = 'registrability'
CATEGORY_TITLE_ADVISORY = 'title_advisory'

# [VERIFY] 4-month presentation window (Registration Act 1908 and the draft
# Registration Bill 2025 as far as we know). Change here if counsel disagrees.
PRESENTATION_WINDOW_MONTHS = 4

# Deed types that legitimately carry no monetary consideration.
NO_CONSIDERATION_DOC_TYPES = frozenset({'gift', 'will', 'partition'})

# Non-sale instruments that can legitimately explain an ownership gap (B1 decoy).
LINKING_DOC_TYPES = frozenset({'will', 'gift', 'partition', 'succession'})


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Flag:
    severity: str
    category: str
    code: str
    document_id: str
    title: str
    detail: str
    mitigation: str
    field_path: str = ''
    rule_id: str = ''

    @property
    def rule_class(self) -> str:
        return self.rule_id[:1] if self.rule_id else ''

    def to_dict(self) -> Dict[str, Any]:
        return dict(
            severity=self.severity,
            category=self.category,
            code=self.code,
            document_id=self.document_id,
            title=self.title,
            detail=self.detail,
            mitigation=self.mitigation,
            field_path=self.field_path,
            flag_id=self.rule_id,
            **{'class': self.rule_class},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _field(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split('.'):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == '')


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(',', '').strip())
        except ValueError:
            return None
    return None


def _names_match(a: Any, b: Any) -> bool:
    """Basic MVP matching: lower().strip() (plus whitespace collapse)."""
    na = normalize_name(a)
    return na != '' and na == normalize_name(b)


def _norm_unit(unit: Any) -> str:
    return '' if unit is None else str(unit).strip().lower()


def _doc_id(doc: Dict[str, Any]) -> str:
    value = doc.get('doc_id')
    return 'UNKNOWN' if _is_blank(value) else str(value)


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if _is_blank(value):
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _bundle_index(bundle: Any) -> Dict[str, Dict[str, Any]]:
    """Accepts {doc_id: doc} or [doc, doc, ...]; returns {doc_id: doc}."""
    if not bundle:
        return {}
    if isinstance(bundle, dict):
        return {str(k): v for k, v in bundle.items() if isinstance(v, dict)}
    index: Dict[str, Dict[str, Any]] = {}
    for item in bundle:
        if isinstance(item, dict) and not _is_blank(item.get('doc_id')):
            index[str(item['doc_id'])] = item
    return index


def _resolve_parent(doc: Dict[str, Any], bundle_idx: Dict[str, Dict[str, Any]]):
    """Returns (parent_ref dict, parent doc from the bundle or None)."""
    parent_ref = doc.get('parent_ref')
    if not isinstance(parent_ref, dict):
        return {}, None
    ref = parent_ref.get('doc_ref')
    parent_doc = None if _is_blank(ref) else bundle_idx.get(str(ref))
    return parent_ref, parent_doc


def _parent_attr(parent_ref: Dict[str, Any], parent_doc: Optional[Dict[str, Any]],
                 ref_key: str, doc_path: str) -> Any:
    """Prefer the value on parent_ref; else read it from the parent deed in the bundle."""
    value = parent_ref.get(ref_key)
    if not _is_blank(value):
        return value
    if parent_doc is not None:
        return _field(parent_doc, doc_path)
    return None


def _acting_through_poa(doc: Dict[str, Any]) -> bool:
    """Contract: acting_through_poa = {"used": bool, "poa_reg_no": str|null}.

    Also accepts the legacy bare True. A dict WITHOUT a 'used' key counts as
    POA-used only if it carries a poa_reg_no.
    """
    poa = doc.get('acting_through_poa')
    if poa is True:
        return True
    if isinstance(poa, dict):
        if 'used' in poa:
            return bool(poa.get('used'))
        return not _is_blank(poa.get('poa_reg_no'))
    return False


# ---------------------------------------------------------------------------
# Class A: Registrability - Hard Stops
# ---------------------------------------------------------------------------
class ClassAHardStops:
    def evaluate(self, doc: Dict[str, Any], bundle: Any = None,
                 as_of: Optional[date] = None) -> List[Flag]:
        doc_id = _doc_id(doc)
        bundle_idx = _bundle_index(bundle)
        flags: List[Flag] = []
        flags.extend(self._a1_poa(doc, doc_id))
        flags.extend(self._a2_area(doc, doc_id))
        flags.extend(self._a3_boundaries(doc, doc_id))
        flags.extend(self._a4_presentation_window(doc, doc_id, as_of))
        flags.extend(self._a5_party_names(doc, doc_id))
        flags.extend(self._a6_consideration(doc, doc_id))
        flags.extend(self._a7_ulpin_parent(doc, doc_id, bundle_idx))
        return flags

    # ---- A1: Missing POA registration --------------------------------------
    def _a1_poa(self, doc, doc_id):
        if not _acting_through_poa(doc):
            return []
        poa = doc.get('acting_through_poa')
        poa_reg_no = poa.get('poa_reg_no') if isinstance(poa, dict) else None
        if not _is_blank(poa_reg_no):
            return []
        return [Flag(
            severity=HARD_STOP,
            category=CATEGORY_REGISTRABILITY,
            code='POA_REGISTRATION_MISSING',
            document_id=doc_id,
            title='POA registration number missing',
            detail='Document is executed through a power of attorney but no POA registration number is present. '
                   'A POA authorising transfer of immovable property is expected to be registered.',
            mitigation='Obtain the registered POA and its registration number, then re-submit before presentation.',
            field_path='acting_through_poa.poa_reg_no',
            rule_id='A1',
        )]

    # ---- A2: Missing area ---------------------------------------------------
    def _a2_area(self, doc, doc_id):
        area_value = _to_number(_field(doc, 'property.area_value'))
        area_unit = _field(doc, 'property.area_unit')
        if area_value is not None and area_value > 0 and not _is_blank(area_unit):
            return []
        return [Flag(
            severity=HARD_STOP,
            category=CATEGORY_REGISTRABILITY,
            code='PROPERTY_AREA_MISSING',
            document_id=doc_id,
            title='Property area is missing',
            detail='property.area_value is missing, zero or not a number, or property.area_unit is undefined.',
            mitigation='Verify survey data and update property.area_value and property.area_unit.',
            field_path='property.area_value',
            rule_id='A2',
        )]

    # ---- A3: Boundary completeness -----------------------------------------
    def _a3_boundaries(self, doc, doc_id):
        boundaries = _field(doc, 'property.boundaries')
        if isinstance(boundaries, dict):
            missing = [side for side in (
                'N', 'E', 'S', 'W') if _is_blank(boundaries.get(side))]
            if not missing:
                return []
            detail = ('Property boundaries missing cardinal directions: '
                      + ', '.join(missing) + '. Requires N, E, S, W.')
            title = 'Property boundaries incomplete'
        else:
            detail = 'property.boundaries is not a JSON object. Requires N, E, S, W boundary descriptions.'
            title = 'Property boundaries missing'
        return [Flag(
            severity=HARD_STOP,
            category=CATEGORY_REGISTRABILITY,
            code='PROPERTY_BOUNDARIES_MISSING',
            document_id=doc_id,
            title=title,
            detail=detail,
            mitigation='Update property.boundaries with N, E, S, W from the survey map.',
            field_path='property.boundaries',
            rule_id='A3',
        )]

    # ---- A4: Presentation within the window after execution -----------------
    def _a4_presentation_window(self, doc, doc_id, as_of):
        execution = _parse_date(doc.get('execution_date'))
        if execution is None:
            return [Flag(
                severity=HARD_STOP,
                category=CATEGORY_REGISTRABILITY,
                code='EXECUTION_DATE_MISSING',
                document_id=doc_id,
                title='Execution date missing or invalid',
                detail='execution_date is missing or not a valid YYYY-MM-DD date, so the presentation window cannot be checked.',
                mitigation='Read the execution date from the deed and correct the extracted value.',
                field_path='execution_date',
                rule_id='A4',
            )]

        raw_presentation = doc.get('presentation_date')
        if _is_blank(raw_presentation):
            # Pre-registration: the deed is being presented now.
            presentation = _parse_date(as_of) or date.today()
        else:
            presentation = _parse_date(raw_presentation)
            if presentation is None:
                return [Flag(
                    severity=HARD_STOP,
                    category=CATEGORY_REGISTRABILITY,
                    code='PRESENTATION_DATE_INVALID',
                    document_id=doc_id,
                    title='Presentation date invalid',
                    detail='presentation_date is not a valid YYYY-MM-DD date.',
                    mitigation='Correct the presentation date.',
                    field_path='presentation_date',
                    rule_id='A4',
                )]

        if presentation < execution:
            return [Flag(
                severity=HARD_STOP,
                category=CATEGORY_REGISTRABILITY,
                code='PRESENTATION_BEFORE_EXECUTION',
                document_id=doc_id,
                title='Presentation date is before execution date',
                detail='Presentation date ' + presentation.isoformat() +
                ' is earlier than execution date '
                       + execution.isoformat() + '.',
                mitigation='Check both dates against the deed and the presentation record.',
                field_path='presentation_date',
                rule_id='A4',
            )]

        deadline = _add_months(execution, PRESENTATION_WINDOW_MONTHS)
        if presentation > deadline:
            return [Flag(
                severity=HARD_STOP,
                category=CATEGORY_REGISTRABILITY,
                code='PRESENTATION_WINDOW_EXCEEDED',
                document_id=doc_id,
                title='Presentation outside the ' +
                    str(PRESENTATION_WINDOW_MONTHS) + '-month window',
                    detail='Executed ' + execution.isoformat() + ', presented ' +
                    presentation.isoformat()
                    + '; the window closed on ' + deadline.isoformat() + '.',
                    mitigation='Late presentation is an objective ground for refusal; the parties may need to follow '
                           'the applicable late-presentation procedure.',
                    field_path='presentation_date',
                    rule_id='A4',
                    )]
        return []

    # ---- A5: Party names present --------------------------------------------
    def _a5_party_names(self, doc, doc_id):
        flags = []
        for role in ('seller', 'buyer'):
            if _is_blank(_field(doc, role + '.name')):
                flags.append(Flag(
                    severity=HARD_STOP,
                    category=CATEGORY_REGISTRABILITY,
                    code=role.upper() + '_NAME_MISSING',
                    document_id=doc_id,
                    title=role.capitalize() + ' name missing',
                    detail=role + '.name is missing or blank, so the party cannot be identified.',
                    mitigation='Read the ' + role +
                    ' name from the deed and correct the extracted value.',
                    field_path=role + '.name',
                    rule_id='A5',
                ))
        return flags

    # ---- A6: Consideration present ------------------------------------------
    def _a6_consideration(self, doc, doc_id):
        doc_type = str(doc.get('doc_type') or '').strip().lower()
        if doc_type in NO_CONSIDERATION_DOC_TYPES:
            return []
        value = _to_number(doc.get('consideration'))
        if value is not None and value > 0:
            return []
        return [Flag(
            severity=HARD_STOP,
            category=CATEGORY_REGISTRABILITY,
            code='CONSIDERATION_MISSING',
            document_id=doc_id,
            title='Consideration amount missing',
            detail='consideration is missing, zero or not a number for a ' +
                (doc_type or 'conveyance') + ' deed.',
                mitigation='Read the consideration (price) from the deed and correct the extracted value.',
                field_path='consideration',
                rule_id='A6',
                )]

    # ---- A7: ULPIN consistent with parent deed ------------------------------
    def _a7_ulpin_parent(self, doc, doc_id, bundle_idx):
        parcel_ulpin = _field(doc, 'property.ulpin')
        if _is_blank(parcel_ulpin):
            return []
        parent_ref, parent_doc = _resolve_parent(doc, bundle_idx)
        if not parent_ref:
            return []
        parent_ulpin = _parent_attr(
            parent_ref, parent_doc, 'ulpin', 'property.ulpin')
        if _is_blank(parent_ulpin):
            logger.info(
                'A7 skipped for %s: parent ULPIN not available', doc_id)
            return []
        if normalize_ulpin(parcel_ulpin) == normalize_ulpin(parent_ulpin):
            return []
        return [Flag(
            severity=HARD_STOP,
            category=CATEGORY_REGISTRABILITY,
            code='ULPIN_PARENT_MISMATCH',
            document_id=doc_id,
            title='ULPIN does not match parent deed',
            detail='property.ulpin=' +
                repr(parcel_ulpin) + ' != parent ulpin=' + repr(parent_ulpin),
                mitigation='Reconcile the parcel ULPIN against the parent deed registration details.',
                field_path='property.ulpin',
                rule_id='A7',
                )]


# ---------------------------------------------------------------------------
# Class B: Title-intelligence advisories (not refusal grounds)
# ---------------------------------------------------------------------------
class ClassBAdvisories:
    def evaluate(self, doc: Dict[str, Any], bundle: Any = None) -> List[Flag]:
        doc_id = _doc_id(doc)
        bundle_idx = _bundle_index(bundle)
        flags: List[Flag] = []

        ulpin = _field(doc, 'property.ulpin')
        seller_name = _field(doc, 'seller.name')
        parcel = None if _is_blank(ulpin) else MockRegistry.get_parcel(ulpin)

        if parcel is None:
            flags.append(self._b0_registry_unavailable(doc_id, ulpin))
        else:
            flags.extend(self._b1_broken_link(
                doc_id, ulpin, seller_name, parcel, bundle_idx))
            flags.extend(self._b2_double_sale(
                doc_id, ulpin, seller_name, bundle_idx))

        flags.extend(self._b3_area_conservation(doc, doc_id, bundle_idx))
        return flags

    # ---- B0: registry cross-check could not run (coverage gap) --------------
    def _b0_registry_unavailable(self, doc_id, ulpin):
        if _is_blank(ulpin):
            reason = 'property.ulpin is missing'
        else:
            reason = "ULPIN '" + str(ulpin) + \
                "' was not found in the registry index"
        return Flag(
            severity=WARNING,
            category=CATEGORY_TITLE_ADVISORY,
            code='REGISTRY_CHECK_UNAVAILABLE',
            document_id=doc_id,
            title='Registry cross-check could not be performed',
            detail=reason + '. No ownership-link or parallel-conveyance check was run; '
            'the absence of other advisories does not indicate the ownership history is free of problems.',
            mitigation='Obtain an encumbrance certificate and the relevant revenue/mutation records for this parcel.',
            field_path='property.ulpin',
            rule_id='B0',
        )

    # ---- B1: Broken link ----------------------------------------------------
    def _b1_broken_link(self, doc_id, ulpin, seller_name, parcel, bundle_idx):
        if _is_blank(seller_name):
            return []  # A5 already reports the missing name
        owner = parcel['current_owner']
        if _names_match(seller_name, owner):
            return []
        if self._has_linking_instrument(doc_id, seller_name, owner, bundle_idx):
            logger.info(
                'B1 suppressed for %s: linking instrument found in bundle', doc_id)
            return []
        return [Flag(
            severity=WARNING,
            category=CATEGORY_TITLE_ADVISORY,
            code='BROKEN_OWNERSHIP_LINK',
            document_id=doc_id,
            title='Seller does not match the registry\'s current owner',
            detail="Seller '" + str(seller_name) +
            "' does not match the recorded current owner '"
                   + str(owner) + "' for ULPIN '" + str(ulpin) +
            "', and no linking instrument "
                   "(succession, will, gift or partition) was found in the uploaded bundle.",
            mitigation='Class B advisory (not a refusal ground). Ask for the instrument linking the seller to the '
                       'recorded owner (registered deed, succession document, decree or partition). Some '
                       'transfers legitimately happen outside registered sale deeds.',
            field_path='seller.name',
            rule_id='B1',
        )]

    def _has_linking_instrument(self, own_id, seller_name, owner_name, bundle_idx):
        """True if another bundle doc (will/gift/partition/succession) runs from
        the recorded owner to the seller."""
        for other_id, other in bundle_idx.items():
            if other_id == own_id:
                continue
            doc_type = str(other.get('doc_type') or '').strip().lower()
            if doc_type not in LINKING_DOC_TYPES:
                continue
            if (_names_match(_field(other, 'seller.name'), owner_name)
                    and _names_match(_field(other, 'buyer.name'), seller_name)):
                return True
        return False

    # ---- B2: Possible double sale ------------------------------------------
    def _b2_double_sale(self, doc_id, ulpin, seller_name, bundle_idx):
        if _is_blank(seller_name):
            return []
        bundle_doc_ids = sorted(set(bundle_idx.keys()) | {doc_id})
        hit = MockRegistry.check_for_parallel_conveyance(
            str(ulpin), str(seller_name), bundle_doc_ids)
        if hit is None:
            return []
        return [Flag(
            severity=WARNING,
            category=CATEGORY_TITLE_ADVISORY,
            code=hit['code'],
            document_id=doc_id,
            title=hit['title'],
            detail=hit['detail'],
            mitigation=hit['mitigation'],
            field_path='property.ulpin',
            rule_id='B2',
        )]

    # ---- B3: Area conservation ----------------------------------------------
    def _b3_area_conservation(self, doc, doc_id, bundle_idx):
        draft_area = _to_number(_field(doc, 'property.area_value'))
        draft_unit = _norm_unit(_field(doc, 'property.area_unit'))
        if draft_area is None or draft_unit == '':
            return []  # A2 already reports this

        parent_ref, parent_doc = _resolve_parent(doc, bundle_idx)
        if not parent_ref:
            return []
        parent_area = _to_number(_parent_attr(
            parent_ref, parent_doc, 'area_value', 'property.area_value'))
        parent_unit = _norm_unit(_parent_attr(
            parent_ref, parent_doc, 'area_unit', 'property.area_unit'))
        if parent_area is None or parent_unit == '':
            logger.info('B3 skipped for %s: parent area not available', doc_id)
            return []
        if parent_unit != draft_unit:
            logger.info('B3 skipped for %s: unit mismatch (%s vs %s)',
                        doc_id, draft_unit, parent_unit)
            return []
        if draft_area <= parent_area:
            return []
        return [Flag(
            severity=WARNING,
            category=CATEGORY_TITLE_ADVISORY,
            code='AREA_EXCEEDS_PARENT',
            document_id=doc_id,
            title='Transferred area exceeds the parent deed area',
            detail='Draft deed area ' +
                format(draft_area, 'g') + ' ' + draft_unit +
                ' is greater than the parent deed area '
                   + format(parent_area, 'g') + ' ' + parent_unit + '.',
                mitigation='Class B advisory (not a refusal ground). Reconcile against the parent deed and the survey map; '
                'request a demarcation or survey report if the parent parcel was larger than recorded.',
                field_path='property.area_value',
                rule_id='B3',
                )]


# ---------------------------------------------------------------------------
# Factories and pipeline helpers
# ---------------------------------------------------------------------------
def evaluate_class_a() -> ClassAHardStops:
    return ClassAHardStops()


def evaluate_class_b() -> ClassBAdvisories:
    return ClassBAdvisories()


def evaluate_document(doc: Dict[str, Any], bundle: Any = None,
                      as_of: Optional[date] = None) -> List[Flag]:
    """Run Class A then Class B on the draft deed.

    bundle: {doc_id: doc} or [doc, ...] of the other uploaded deeds (optional).
    as_of:  date used as the presentation date when the deed has none.
    """
    flags: List[Flag] = []
    flags.extend(ClassAHardStops().evaluate(doc, bundle=bundle, as_of=as_of))
    flags.extend(ClassBAdvisories().evaluate(doc, bundle=bundle))
    return flags


def build_checklist_state(flags: List[Flag]) -> Dict[str, Any]:
    """JSON-serialisable checklist state for audit_log.create_audit_block()."""
    return {
        'flags': [
            {
                'flag_id': f.rule_id,
                'code': f.code,
                'severity': f.severity,
                'document_id': f.document_id,
                'field_path': f.field_path,
            }
            for f in flags
        ],
        'hard_stop_count': sum(1 for f in flags if f.severity == HARD_STOP),
        'advisory_count': sum(1 for f in flags if f.severity == WARNING),
    }


# ---------------------------------------------------------------------------
# Smoke test:  python engine.py
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    demo_doc = {
        'doc_id': 'DRAFT-1',
        'doc_type': 'sale_deed',
        'execution_date': '2026-01-10',
        'presentation_date': '2026-07-01',
        'seller': {'name': 'Meera Patel'},
        'buyer': {'name': 'Anil Das'},
        'acting_through_poa': {'used': True, 'poa_reg_no': None},
        'property': {
            'ulpin': 'AS-104',
            'area_value': 1500,
            'area_unit': 'sqft',
            'boundaries': {'N': 'Road', 'E': 'Plot 12', 'S': '', 'W': 'Canal'},
        },
        'parent_ref': {'doc_ref': 'PARENT-1', 'ulpin': 'AS-104', 'area_value': 1200, 'area_unit': 'sqft'},
        'consideration': 0,
    }
    for flag in evaluate_document(demo_doc):
        print(flag.rule_id, flag.severity, flag.code, '-', flag.title)
    print(build_checklist_state(evaluate_document(demo_doc))
          ['hard_stop_count'], 'hard stops')
