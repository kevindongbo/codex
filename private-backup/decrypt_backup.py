"""Decrypt a Dongbo private backup without printing its contents."""

from __future__ import annotations

import base64
import os
import pathlib
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"DONGBO-PRIVATE-BACKUP-V1\0"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: decrypt_backup.py INPUT OUTPUT", file=sys.stderr)
        return 2

    key_text = os.environ.get("PRIVATE_BACKUP_KEY_B64", "")
    if not key_text:
        print("PRIVATE_BACKUP_KEY_B64 is required", file=sys.stderr)
        return 2

    key = base64.b64decode(key_text, validate=True)
    if len(key) != 32:
        print("PRIVATE_BACKUP_KEY_B64 must encode exactly 32 bytes", file=sys.stderr)
        return 2

    source = pathlib.Path(sys.argv[1]).read_bytes()
    if not source.startswith(MAGIC) or len(source) <= len(MAGIC) + 12:
        print("unsupported or damaged backup", file=sys.stderr)
        return 2

    nonce_start = len(MAGIC)
    nonce = source[nonce_start : nonce_start + 12]
    ciphertext = source[nonce_start + 12 :]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, MAGIC)

    destination = pathlib.Path(sys.argv[2])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(plaintext)
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
