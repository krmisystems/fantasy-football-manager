"""Read a restricted ESPN session without starting a browser."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from datetime import datetime, timezone


COOKIE_NAMES = frozenset({"SWID", "espn_s2"})


def read_credentials(path):
    """Load only the two ESPN credentials. Never include values in errors."""
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("An ESPN credential file is required.")
    info = path.stat()
    if os.name == "posix" and (stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.geteuid()):
        raise ValueError("The ESPN credential file must belong to this account and use mode 0600.")
    try:
        if info.st_size > 16384:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != COOKIE_NAMES:
            raise ValueError()
        if any(not isinstance(item, str) or not item or len(item) > 12000
               or any(c in item for c in "\r\n;\x00") for item in value.values()):
            raise ValueError()
    except (ValueError, UnicodeError, OSError):
        raise ValueError("The ESPN credential file is invalid.") from None
    return value


def import_linux_session(cookie_database, destination):
    """Import two ESPN cookies from a Linux Chromium v10 database.

    This function opens SQLite read-only. It does not start or control Chromium.
    Unsupported encryption and expired sessions require separate authentication.
    Chromium's v10 algorithm is documented in its os_crypt_linux.cc source.
    """
    if os.name != "posix":
        raise ValueError("This session import supports Linux Chromium v10 only.")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7
    except ImportError:
        raise ValueError("Install the session-import extra before importing a Linux session.") from None
    source = Path(cookie_database).expanduser().resolve(strict=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        version = int(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        rows = db.execute("""SELECT host_key,name,value,encrypted_value,expires_utc,has_expires
            FROM cookies WHERE host_key='.espn.com' AND name IN ('SWID','espn_s2')""").fetchall()
    if len(rows) != 2 or {row[1] for row in rows} != COOKIE_NAMES:
        raise ValueError("The profile must contain one current value for each ESPN session cookie.")
    result = {}
    chromium_now = (datetime.now(timezone.utc).timestamp() + 11644473600) * 1000000
    for host, name, plain, encrypted, expiry, has_expiry in rows:
        if has_expiry and expiry <= chromium_now:
            raise ValueError("The saved ESPN session has expired.")
        if not plain:
            if encrypted[:3] != b"v10":
                raise ValueError("The saved session uses unsupported cookie encryption.")
            key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
            try:
                decrypt = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
                padded = decrypt.update(encrypted[3:]) + decrypt.finalize()
                unpad = PKCS7(128).unpadder()
                decoded = unpad.update(padded) + unpad.finalize()
                if version >= 24:
                    if decoded[:32] != hashlib.sha256(host.encode()).digest():
                        raise ValueError()
                    decoded = decoded[32:]
                plain = decoded.decode("utf-8")
            except (ValueError, UnicodeError):
                raise ValueError("The ESPN session could not be decrypted and verified.") from None
        result[name] = plain
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.is_symlink():
        raise ValueError("The credential destination must not be a symbolic link.")
    fd, temporary = tempfile.mkstemp(prefix=".espn-session-", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        read_credentials(temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"status": "imported", "credential_names": sorted(COOKIE_NAMES), "browser_started": False}
