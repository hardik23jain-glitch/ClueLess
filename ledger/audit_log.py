# Audit Log (Backend / P2)

# Step 3: Tamper-Evident Ledger.
# Certificate Transparency-style hash chain using SQLite and hashlib.
#   * Table: idx, prev_hash, timestamp, parcel_ref, bundle_hash,
#     checklist_state, dispositions, officer_sig_ref, entry_hash
#   * create_audit_block(...)   -- SHA-256 over prev_hash + JSON payload; links to
#                                  the real previous row automatically
#   * verify_chain_integrity()  -- returns (True, None, None, None) or
#                                  (False, row_idx, expected_hash, actual_hash)
#   * dpdp_pii_redaction(text)  -- regex mask 12-digit Aadhaar numbers
#                                  (applied to every string before it is stored)
#   * get_chain_head()          -- (idx, entry_hash) of the latest block; show it on
#                                  the UI / write it down as the external witness


import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# SQLite DB path
# ---------------------------------------------------------------------------
# Absolute, so the DB is the same file no matter which folder Streamlit/tests run from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_log.db")
GENESIS_HASH = "0" * 64

_AADHAAR_PATTERN = re.compile(r"\b(\d{4}[-\s]?){2}\d{4}\b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _payload_bytes(prev_hash: str, payload: Dict[str, Any]) -> bytes:
    # Critical for tamper demo: entry_hash = SHA-256(prev_hash + payload)
    return (prev_hash + json.dumps(payload, sort_keys=True)).encode("utf-8")


def _entry_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
    return _hash(_payload_bytes(prev_hash, payload))


def dpdp_pii_redaction(text: str) -> str:
    """Mask 12-digit Aadhaar numbers before any logging occurs.

    Pattern: exactly 12 consecutive digits, optionally with spaces or
    hyphens every 4 digits. The mask replaces digits with 'X'.
    """
    return _AADHAAR_PATTERN.sub(lambda m: "X" * 12, text)


def _redact_obj(value: Any) -> Any:
    """Recursively apply dpdp_pii_redaction to every string in a JSON-like value."""
    if isinstance(value, str):
        return dpdp_pii_redaction(value)
    if isinstance(value, dict):
        return {str(k): _redact_obj(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_obj(v) for v in value]
    return value


def compute_bundle_hash(file_contents: List[bytes]) -> str:
    """SHA-256 of the sorted per-file SHA-256 hashes (order-independent)."""
    return compute_bundle_hash_from_hashes(hashlib.sha256(content).hexdigest() for content in file_contents)


def compute_bundle_hash_from_hashes(file_hashes) -> str:
    """Same bundle hash, from already-computed per-file SHA-256s (e.g. extraction provenance.file_sha256
    of the ORIGINAL uploaded files, which is what the ledger is meant to bind)."""
    return _hash("\n".join(sorted(file_hashes)).encode("utf-8"))


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    # isolation_level=None -> we control transactions explicitly
    return sqlite3.connect(DB_PATH, isolation_level=None)


def _get_connection() -> sqlite3.Connection:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            idx INTEGER PRIMARY KEY AUTOINCREMENT,
            prev_hash TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            parcel_ref TEXT NOT NULL,
            bundle_hash TEXT NOT NULL,
            checklist_state TEXT NOT NULL,
            dispositions TEXT NOT NULL,
            officer_sig_ref TEXT,
            entry_hash TEXT NOT NULL
        )
        """
    )
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def create_audit_block(
    parcel_ref: str,
    bundle_hash: str,
    checklist_state: Dict[str, Any],
    dispositions: Dict[str, Any],
    officer_sig_ref: str,
    prev_hash: Optional[str] = None,
) -> int:
    """Insert a new audit block and return the row ID.

    Leave prev_hash as None: the block is then linked to the real previous
    row's entry_hash (or the genesis hash for the first block). All free text
    is passed through dpdp_pii_redaction before hashing and storing.
    """
    parcel_ref = _redact_obj(parcel_ref)
    bundle_hash = _redact_obj(bundle_hash)
    officer_sig_ref = _redact_obj(officer_sig_ref)
    checklist_state = _redact_obj(checklist_state)
    dispositions = _redact_obj(dispositions)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    conn = _get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        if prev_hash is None:
            row = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY idx DESC LIMIT 1"
            ).fetchone()
            prev_hash = row[0] if row else GENESIS_HASH

        payload = {
            "parcel_ref": parcel_ref,
            "bundle_hash": bundle_hash,
            "checklist_state": checklist_state,
            "dispositions": dispositions,
            "officer_sig_ref": officer_sig_ref,
            "timestamp": timestamp,
        }
        entry_hash = _entry_hash(prev_hash, payload)

        cursor = conn.execute(
            """
            INSERT INTO audit_log (
                prev_hash, timestamp, parcel_ref, bundle_hash,
                checklist_state, dispositions, officer_sig_ref, entry_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prev_hash,
                timestamp,
                parcel_ref,
                bundle_hash,
                json.dumps(checklist_state, sort_keys=True),
                json.dumps(dispositions, sort_keys=True),
                officer_sig_ref,
                entry_hash,
            ),
        )
        row_id = cursor.lastrowid
        conn.execute("COMMIT")
        return row_id
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def verify_chain_integrity() -> Tuple[bool, Optional[int], Optional[str], Optional[str]]:
    """Walk the whole chain.

    Intact chain  -> (True, None, None, None)
    Broken chain  -> (False, row_idx, expected_hash, actual_hash)

    Two things are checked for every row, in order:
      1. LINK:  row.prev_hash must equal the previous row's entry_hash
                (genesis hash for the first row). A deleted or re-ordered row
                fails here: expected = what prev_hash should be, actual = what is stored.
      2. HASH:  row.entry_hash must equal SHA-256(prev_hash + payload) recomputed
                from the stored fields. An edited row fails here:
                expected = the recomputed hash, actual = the stored entry_hash.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT idx, prev_hash, timestamp, parcel_ref, bundle_hash, checklist_state, "
            "dispositions, officer_sig_ref, entry_hash FROM audit_log ORDER BY idx"
        ).fetchall()
    finally:
        conn.close()

    expected_prev = GENESIS_HASH
    for (idx, prev_hash, timestamp, parcel_ref, bundle_hash, checklist_state_json,
         dispositions_json, officer_sig_ref, entry_hash) in rows:

        if prev_hash != expected_prev:
            return False, idx, expected_prev, prev_hash

        try:
            checklist_state = json.loads(checklist_state_json)
            dispositions = json.loads(dispositions_json)
        except (TypeError, ValueError):
            return False, idx, "UNPARSEABLE_STORED_JSON", entry_hash

        payload = {
            "parcel_ref": parcel_ref,
            "bundle_hash": bundle_hash,
            "checklist_state": checklist_state,
            "dispositions": dispositions,
            "officer_sig_ref": officer_sig_ref,
            "timestamp": timestamp,
        }
        expected_hash = _entry_hash(prev_hash, payload)
        if expected_hash != entry_hash:
            return False, idx, expected_hash, entry_hash

        expected_prev = entry_hash

    return True, None, None, None


def get_chain_head() -> Optional[Tuple[int, str]]:
    """(idx, entry_hash) of the latest block, or None if the log is empty.

    Truncating the newest rows cannot be detected from inside the DB alone, so
    show this value on the UI (and note it down) as the external witness.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT idx, entry_hash FROM audit_log ORDER BY idx DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return (row[0], row[1]) if row else None


def list_blocks() -> List[Dict[str, Any]]:
    """All blocks, oldest first, with JSON fields parsed (for the UI table)."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT idx, prev_hash, timestamp, parcel_ref, bundle_hash, checklist_state, "
            "dispositions, officer_sig_ref, entry_hash FROM audit_log ORDER BY idx"
        ).fetchall()
    finally:
        conn.close()

    blocks = []
    for (idx, prev_hash, timestamp, parcel_ref, bundle_hash, checklist_state_json,
         dispositions_json, officer_sig_ref, entry_hash) in rows:
        try:
            checklist_state = json.loads(checklist_state_json)
            dispositions = json.loads(dispositions_json)
        except (TypeError, ValueError):
            checklist_state, dispositions = None, None
        blocks.append({
            "idx": idx,
            "prev_hash": prev_hash,
            "timestamp": timestamp,
            "parcel_ref": parcel_ref,
            "bundle_hash": bundle_hash,
            "checklist_state": checklist_state,
            "dispositions": dispositions,
            "officer_sig_ref": officer_sig_ref,
            "entry_hash": entry_hash,
        })
    return blocks


def reset_audit_log() -> None:
    """Clear the audit log (useful for tests and for resetting the demo)."""
    conn = _connect()
    try:
        conn.execute("DROP TABLE IF EXISTS audit_log")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tamper demo:  python audit_log.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    reset_audit_log()
    for n in range(1, 4):
        create_audit_block(
            parcel_ref="AS-10" + str(n),
            bundle_hash=compute_bundle_hash([b"deed-" + str(n).encode()]),
            checklist_state={"flags": [{"flag_id": "B2"}]},
            dispositions={"B2": {"action": "PARTIES_INFORMED",
                                 "reason": "Aadhaar 1234 5678 9012 seen"}},
            officer_sig_ref="MOCK-DSC-0001",
        )
    print("head:", get_chain_head())
    print("before tamper:", verify_chain_integrity())

    tamper = sqlite3.connect(DB_PATH)
    tamper.execute(
        "UPDATE audit_log SET dispositions = ? WHERE idx = 2",
        (json.dumps({"B2": {"action": "ACK_PROCEED",
         "reason": "edited"}}, sort_keys=True),),
    )
    tamper.commit()
    tamper.close()
    print("after tamper: ", verify_chain_integrity())
