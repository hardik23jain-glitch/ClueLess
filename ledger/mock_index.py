# Registry State Simulator (Backend / P2)

# Step 2: State Registry Simulator.

# A lightweight stub that simulates the government Sub-Registrar registry.
# Since we do not have access to the real registry, this module:
#   * Contains 4 fake parcels in an in-memory dictionary (MockRegistry)
#   * One parcel (AS-104) has a HIDDEN parallel conveyance (a 2015 sale to a
#     third party that the user did NOT upload in their bundle)
#   * Provides check_for_parallel_conveyance() for Class B advisory B2
#   * Provides get_current_owner() / get_parcel() for Class B advisory B1
#   * Provides normalize_name(), the single name-matching rule shared with
#     engine.py so the registry and the rules engine can never disagree.

# Everything is deterministic and in-memory (no I/O, no time, no DB).


from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Name normalisation (MVP: no fuzzy matching, no extra dependencies)
# ---------------------------------------------------------------------------
def normalize_name(name: Optional[str]) -> str:
    """Lower-case, trim and collapse inner whitespace. None -> ''."""
    if name is None:
        return ""
    return " ".join(str(name).lower().split())


# ---------------------------------------------------------------------------
# ULPIN normalisation. A real ULPIN (Bhu-Aadhaar) is 14 alphanumeric characters, so the
# registry now keys on that format. Short demo codes such as "AS-104" still resolve
# through an alias table, so older fixtures keep working.
# ---------------------------------------------------------------------------
def normalize_ulpin(ulpin: Optional[str]) -> str:
    """Upper-case and drop spaces/hyphens: "as-104" -> "AS104"."""
    return "".join(ch for ch in str(ulpin or "") if ch.isalnum()).upper()


# ---------------------------------------------------------------------------
# MockRegistry -- the state registry simulator
# ---------------------------------------------------------------------------
class MockRegistry:
    """Simulates the Sub-Registrar registry index.

    In a production system this would be a government API / SQL database.
    Here it is an in-memory dict to make the hackathon deterministic and
    fast to run.

    Data rule (checked at import time by _validate_parcels): current_owner
    is always the LAST BUYER in the recorded chain.
    """

    #: Fake parcel ULPINs in the registry index.
    #: Each parcel stores:
    #:   * current_owner: the latest recorded owner (last buyer in chain)
    #:   * chain: list of (seller, buyer, year) tuples representing the
    #:     recorded chain of title
    #:   * double_sold: optional dict indicating a hidden parallel conveyance
    #:     by an earlier owner (not part of the user's uploaded bundle)
    PARCELS: Dict[str, Dict[str, Any]] = {
        "AS000000000104": {
            "current_owner": "Meera Patel",
            "chain": [
                ("Rajesh Kumar", "Ravi Sharma", 2010),
                ("Ravi Sharma", "Meera Patel", 2015),
            ],
            # Ravi Sharma ALSO conveyed this parcel to a third party in 2015.
            # That deed is only visible in the registry index.
            "double_sold": {
                "third_party": "Vikram Singh",
                "year": 2015,
                "conveyance_doc": "DL-2015-0099",
            },
        },
        "AS000000000105": {
            "current_owner": "Sneha Reddy",
            "chain": [
                ("Chennai Corp", "Sneha Reddy", 2012),
            ],
            "double_sold": None,
        },
        "AS000000000106": {
            "current_owner": "Arjun Deshpande",
            "chain": [
                ("Laxman Rao", "Arjun Deshpande", 2008),
            ],
            "double_sold": None,
            "encumbrances": [
                {"type": "mortgage", "holder": "State Bank of India",
                 "registered_year": 2010, "amount_inr": 1500000,
                 "status": "active"},
            ],
        },
        "AS000000000107": {
            "current_owner": "Priya Nair",
            "chain": [
                ("K. Rajan", "Priya Nair", 2018),
            ],
            "double_sold": None,
        },
        "AS000000000101": {
            "current_owner": "Anil Sharma",
            "chain": [
                ("Bimal Das", "Anil Sharma", 2016),
            ],
            "double_sold": None,
        },
        "AS000000000102": {
            "current_owner": "Sunil Verma",
            "chain": [
                ("Dinesh Nath", "Sunil Verma", 2012),
            ],
            "double_sold": None,
        },
        "AS000000000103": {
            "current_owner": "Pradeep Das",
            "chain": [
                ("Gautam Bora", "Pradeep Das", 2014),
            ],
            "double_sold": None,
        },
        "AS000000000108": {
            "current_owner": "Late Harish Chandra",
            "chain": [
                ("Kamal Nath", "Late Harish Chandra", 2005),
            ],
            "double_sold": None,
        },
        "AS000000000109": {
            "current_owner": "सुरेश वर्मा",
            "chain": [
                ("दिनेश कुमार", "सुरेश वर्मा", 2015),
            ],
            "double_sold": None,
        },
    }

    @classmethod
    def get_parcel(cls, ulpin: Optional[str]) -> Optional[Dict[str, Any]]:
        if ulpin is None:
            return None
        key = normalize_ulpin(ulpin)
        return cls.PARCELS.get(cls._ALIASES.get(key, key))

    @classmethod
    def get_current_owner(cls, ulpin: Optional[str]) -> Optional[str]:
        parcel = cls.get_parcel(ulpin)
        if parcel is None:
            return None
        return parcel["current_owner"]

    @classmethod
    def get_encumbrances(cls, ulpin: Optional[str]) -> List[Dict[str, Any]]:
        """Return recorded encumbrances for a parcel (empty list if none or parcel unknown)."""
        parcel = cls.get_parcel(ulpin)
        if parcel is None:
            return []
        return parcel.get("encumbrances", [])

    @classmethod
    def check_for_parallel_conveyance(
        cls, ulpin: str, seller_name: str, bundle_doc_ids: List[str]
    ) -> Optional[Dict[str, Any]]:
        """Class B advisory B2: a conveyance the user's bundle does not show.

        Only fires when the seller matches the registry's current owner, so
        B1 (broken link) and B2 (parallel conveyance) are never reported
        for the same seller at the same time.
        """
        parcel = cls.get_parcel(ulpin)
        if parcel is None:
            return None

        double_sold = parcel.get("double_sold")
        if double_sold is None:
            return None

        if normalize_name(seller_name) != normalize_name(parcel["current_owner"]):
            return None

        return {
            "code": "PARALLEL_CONVEYANCE",
            "title": "Possible parallel conveyance in registry index",
            "detail": (
                "Registry index shows ULPIN '" +
                    str(ulpin) + "' was also conveyed to '"
                + double_sold["third_party"] +
                    "' in " + str(double_sold["year"])
                + " (registry ref " + double_sold["conveyance_doc"] + "). "
                + "This may indicate a double sale and is not visible in the uploaded bundle. "
                + "Bundle doc IDs: " + ", ".join(bundle_doc_ids)
            ),
            "mitigation": (
                "Class B advisory (not a refusal ground). Obtain the parallel "
                "conveyance record and the registration certificate of the earlier sale, "
                "inform the parties, and record a disposition (e.g. refer to the "
                "competent revenue or legal authority)."
            ),
        }


# ---------------------------------------------------------------------------
# Convenience function (backwards-compatible with Step 1's flag pipeline)
# ---------------------------------------------------------------------------
def check_for_parallel_conveyance(
    ulpin: str, seller_name: str, bundle_doc_ids: List[str]
) -> Optional[Dict[str, Any]]:
    return MockRegistry.check_for_parallel_conveyance(ulpin, seller_name, bundle_doc_ids)


# ---------------------------------------------------------------------------
# Import-time data sanity check (fails loudly if someone edits PARCELS wrongly)
# ---------------------------------------------------------------------------
def _validate_parcels() -> None:
    for ulpin, parcel in MockRegistry.PARCELS.items():
        chain = parcel["chain"]
        if not chain:
            raise ValueError("MockRegistry parcel " +
                             ulpin + " has an empty chain")
        last_buyer = chain[-1][1]
        if normalize_name(parcel["current_owner"]) != normalize_name(last_buyer):
            raise ValueError(
                "MockRegistry parcel " + ulpin + ": current_owner '"
                + parcel["current_owner"] +
                "' must equal last buyer '" + last_buyer + "'"
            )


# Short-code aliases: "AS104" -> "AS000000000104"
MockRegistry._ALIASES = {"AS" + k[2:].lstrip("0"): k for k in MockRegistry.PARCELS}

_validate_parcels()

