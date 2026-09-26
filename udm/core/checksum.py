"""
File integrity verification using checksums (MD5, SHA-256).
"""

import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("udm.core.checksum")

BUFFER_SIZE = 65536  # 64 KB read buffer


def compute_md5(filepath: str) -> str:
    """Compute MD5 hash of a file."""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            md5.update(chunk)
    return md5.hexdigest()


def compute_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_checksum(
    filepath: str,
    expected_hash: str,
    algorithm: str = "sha256"
) -> bool:
    """
    Verify file integrity by comparing computed hash with expected.
    
    Args:
        filepath: Path to the file to verify.
        expected_hash: The expected hash value.
        algorithm: Hash algorithm ('md5' or 'sha256').
    
    Returns:
        True if hashes match, False otherwise.
    """
    if not Path(filepath).exists():
        logger.error(f"File not found: {filepath}")
        return False

    if algorithm == "md5":
        computed = compute_md5(filepath)
    elif algorithm == "sha256":
        computed = compute_sha256(filepath)
    else:
        logger.error(f"Unsupported algorithm: {algorithm}")
        return False

    match = computed.lower() == expected_hash.lower()
    if match:
        logger.info(f"Checksum verified: {filepath}")
    else:
        logger.warning(
            f"Checksum mismatch for {filepath}: "
            f"expected={expected_hash}, computed={computed}"
        )
    return match
