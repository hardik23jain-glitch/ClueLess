"""
Ed25519 signatures + privacy commitments for the decision log (P1 added; completes P2's hash chain).

audit_log.py gives a tamper-EVIDENT chain (hashes). The concept doc also promises a SIGNED log:
each entry is signed over its entry_hash, so a party who can rewrite the whole database
still cannot forge entries without the private key. Signatures live in a side table
(`audit_signatures`) so the existing audit_log schema and database stay untouched.

Also here: salted HMAC commitments for party names, so no personal data sits in the
immutable log, only a value that proves "this log entry is about that name" to someone who
already knows the name and the salt.

Keys are generated on first use and stored beside this file (git-ignored). The key stands in
for the department-held officer signature; officer_sig_ref still records the (mock) DSC serial.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ledger import audit_log as al

_HERE = Path(__file__).resolve().parent
KEY_PATH = _HERE / "signing_key.pem"
SALT_PATH = _HERE / "commit_salt.bin"


def _load_key(path: Optional[Path] = None) -> Ed25519PrivateKey:
    path = Path(path or KEY_PATH)
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return key


def public_key_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(al.DB_PATH, isolation_level=None)
    c.execute("CREATE TABLE IF NOT EXISTS audit_signatures ("
              "idx INTEGER PRIMARY KEY, entry_hash TEXT NOT NULL, signature TEXT NOT NULL, public_key TEXT NOT NULL)")
    return c


def sign_block(idx: int, entry_hash: str, key_path: Optional[Path] = None) -> dict:
    """Sign a block's entry_hash and store the signature. Returns {signature, public_key}."""
    key = _load_key(key_path)
    sig = key.sign(entry_hash.encode("utf-8")).hex()
    pub = public_key_hex(key)
    c = _conn()
    try:
        c.execute("INSERT OR REPLACE INTO audit_signatures VALUES (?,?,?,?)", (idx, entry_hash, sig, pub))
    finally:
        c.close()
    return {"signature": sig, "public_key": pub}


def verify_signatures() -> Tuple[bool, Optional[int], str]:
    """
    Check every block: the chain must be intact AND each entry_hash must carry a valid signature
    from the stored public key. Returns (ok, first_bad_idx, reason).
    """
    ok, bad_idx, _, _ = al.verify_chain_integrity()
    if not ok:
        return False, bad_idx, "hash chain broken"
    c = _conn()
    try:
        sigs = {r[0]: r[1:] for r in c.execute("SELECT idx, entry_hash, signature, public_key FROM audit_signatures")}
    finally:
        c.close()
    for block in al.list_blocks():
        rec = sigs.get(block["idx"])
        if rec is None:
            return False, block["idx"], "block is not signed"
        entry_hash, signature, pub = rec
        if entry_hash != block["entry_hash"]:
            return False, block["idx"], "signature was made over a different entry hash"
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(bytes.fromhex(signature),
                                                                         entry_hash.encode("utf-8"))
        except Exception:
            return False, block["idx"], "signature invalid"
    return True, None, "ok"


def _salt() -> bytes:
    env = os.getenv("LANDGUARD_COMMIT_SALT")
    if env:
        return env.encode("utf-8")
    if SALT_PATH.exists():
        return SALT_PATH.read_bytes()
    salt = os.urandom(32)
    SALT_PATH.write_bytes(salt)
    return salt


def party_commitment(name: Optional[str]) -> Optional[str]:
    """Salted HMAC-SHA256 of the normalised name: no personal data in the immutable log."""
    if not name or not str(name).strip():
        return None
    norm = " ".join(str(name).lower().split())
    return hmac.new(_salt(), norm.encode("utf-8"), hashlib.sha256).hexdigest()
