#!/usr/bin/env python3
"""
Utilities to encrypt/decrypt Ansible inventory passwords.

We store ansible_password as enc$<token> where <token> is a URL-safe base64
Fernet blob. The key is derived from the INVENTORY_ENC_KEY env var, or
SECRET_KEY as a fallback. If neither is set, a weak default is used (DEV only).

Functions:
 - encrypt_password(plain: str) -> str  # returns enc$...
 - decrypt_password(token: str) -> str  # returns plaintext, passthrough if not enc$...
 - decrypt_inventory_text(text: str) -> str  # replace enc$ passwords inline
"""
from __future__ import annotations
import os
import re
import base64
import hashlib
from typing import Optional

from dotenv import load_dotenv

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore


_PW_KEY = 'ansible_password'
_ENC_PREFIX = 'enc$'


def _get_key_material() -> str:
    # Load .env from project root if present
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(base_dir, '.env'))
    return (
        os.getenv('INVENTORY_ENC_KEY')
        or os.getenv('SECRET_KEY')
        or 'dev-inventory-secret-key'
    )


def _make_fernet() -> Optional[Fernet]:  # type: ignore
    if Fernet is None:
        return None
    material = _get_key_material()
    # Derive a 32-byte key from the material via SHA-256
    key_bytes = hashlib.sha256(material.encode('utf-8')).digest()
    fkey = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fkey)


def encrypt_password(plain: str) -> str:
    if not plain:
        return plain
    if plain.startswith(_ENC_PREFIX):
        return plain
    f = _make_fernet()
    if not f:
        # cryptography not available; fallback to simple base64 with prefix (obfuscation only)
        return _ENC_PREFIX + base64.urlsafe_b64encode(plain.encode('utf-8')).decode('ascii')
    token = f.encrypt(plain.encode('utf-8')).decode('ascii')
    return _ENC_PREFIX + token


def decrypt_password(value: str) -> str:
    if not value or not isinstance(value, str):
        return value
    if not value.startswith(_ENC_PREFIX):
        return value
    token = value[len(_ENC_PREFIX) :]
    f = _make_fernet()
    if not f:
        # base64 fallback
        try:
            return base64.urlsafe_b64decode(token.encode('ascii')).decode('utf-8')
        except Exception:
            return value
    try:
        return f.decrypt(token.encode('ascii')).decode('utf-8')
    except InvalidToken:
        return value


_PW_RE = re.compile(rf"(?P<prefix>\b{_PW_KEY}\s*=\s*)(?P<val>[^\s]+)")


def decrypt_inventory_text(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        prefix = m.group('prefix')
        val = m.group('val')
        # Strip quotes around the value if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            raw = val[1:-1]
            was_quoted = True
        else:
            raw = val
            was_quoted = False
        dec = decrypt_password(raw)
        # If decrypted contains spaces or special chars, quote it
        needs_quote = any(c.isspace() for c in dec)
        if needs_quote or was_quoted:
            new_val = f'"{dec}"'
        else:
            new_val = dec
        return prefix + new_val

    return _PW_RE.sub(repl, text)


if __name__ == '__main__':  # simple CLI passthrough
    import argparse, sys
    ap = argparse.ArgumentParser(description='Encrypt/decrypt helper for inventory passwords')
    ap.add_argument('--decrypt', action='store_true', help='Read from stdin, decrypt any enc$ ansible_password values, write to stdout')
    ap.add_argument('--encrypt', metavar='PASSWORD', help='Encrypt one password and print enc$...')
    args = ap.parse_args()
    if args.encrypt:
        print(encrypt_password(args.encrypt))
        sys.exit(0)
    if args.decrypt:
        src = sys.stdin.read()
        sys.stdout.write(decrypt_inventory_text(src))
        sys.exit(0)
    ap.print_help()
