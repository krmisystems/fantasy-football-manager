"""Test session import with fictional, temporary cookie databases."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from fantasy_football_manager import espn_http_auth as auth


COOKIES = {"SWID": "fictional-member", "espn_s2": "fictional-session-canary"}


def credential_file(tmp_path, value=None):
    path = tmp_path / "session.json"
    path.write_text(json.dumps(COOKIES if value is None else value), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_only_the_two_expected_cookie_names_are_loaded(tmp_path):
    assert auth.read_credentials(credential_file(tmp_path)) == COOKIES


@pytest.mark.parametrize("value", [{}, {"SWID": "one"}, {**COOKIES, "other": "unrelated"},
                                   {**COOKIES, "espn_s2": ""}, {**COOKIES, "espn_s2": 3},
                                   {**COOKIES, "espn_s2": "fictional-session-canary\r\n"},
                                   {**COOKIES, "espn_s2": "fictional-session-canary;other=value"},
                                   {**COOKIES, "espn_s2": "fictional-session-canary\x00"},
                                   {**COOKIES, "espn_s2": "x" * 12001}, []])
def test_bad_credentials_are_rejected_without_values_in_errors(tmp_path, value):
    with pytest.raises(ValueError) as error:
        auth.read_credentials(credential_file(tmp_path, value))
    assert "fictional-session-canary" not in str(error.value)


def test_malformed_oversized_and_missing_files_are_rejected(tmp_path):
    path = credential_file(tmp_path)
    for body in ("fictional-session-canary", "x" * 16385):
        path.write_text(body, encoding="utf-8")
        with pytest.raises(ValueError):
            auth.read_credentials(path)
    with pytest.raises(ValueError):
        auth.read_credentials(tmp_path / "missing.json")


@pytest.mark.parametrize("mode,owner", [(0o644, 42), (0o600, 99), (0o660, 42)])
def test_linux_permissions_and_ownership_are_required(monkeypatch, tmp_path, mode, owner):
    path = credential_file(tmp_path)
    info = path.stat()

    class ObservedPath:
        def expanduser(self):
            return self

        def is_symlink(self):
            return False

        def is_file(self):
            return True

        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=owner, st_size=info.st_size)

    monkeypatch.setattr(auth, "os", SimpleNamespace(name="posix", geteuid=lambda: 42))
    monkeypatch.setattr(auth, "Path", lambda _: ObservedPath())
    with pytest.raises(ValueError, match="0600"):
        auth.read_credentials(path)


def encrypted_cookie(value, *, version=24, host=".espn.com"):
    ciphers = pytest.importorskip("cryptography.hazmat.primitives.ciphers")
    padding = pytest.importorskip("cryptography.hazmat.primitives.padding")
    clear = value.encode()
    if version >= 24:
        clear = hashlib.sha256(host.encode()).digest() + clear
    pad = padding.PKCS7(128).padder()
    padded = pad.update(clear) + pad.finalize()
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
    encrypt = ciphers.Cipher(ciphers.algorithms.AES(key), ciphers.modes.CBC(b" " * 16)).encryptor()
    return b"v10" + encrypt.update(padded) + encrypt.finalize()


def cookie_database(tmp_path, *, version=24, change=None):
    path = tmp_path / "Cookies"
    rows = [[".espn.com", name, "", encrypted_cookie(value, version=version), 0, 0]
            for name, value in COOKIES.items()]
    rows.append([".unrelated.invalid", "unrelated", "unrelated-private-value", b"", 0, 0])
    if change:
        change(rows)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        db.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
        db.execute("CREATE TABLE cookies (host_key TEXT,name TEXT,value TEXT,encrypted_value BLOB,expires_utc INTEGER,has_expires INTEGER)")
        db.executemany("INSERT INTO cookies VALUES (?,?,?,?,?,?)", rows)
    return path


@pytest.fixture
def linux_import(monkeypatch):
    """Simulate only Linux OS calls on Windows; SQLite and cryptography stay real."""
    requested_modes = []
    original_read = auth.read_credentials

    def fchmod(fd, mode):
        requested_modes.append(mode)
        if os.name == "posix":
            os.fchmod(fd, mode)

    proxy = SimpleNamespace(name="posix", geteuid=getattr(os, "geteuid", lambda: 0), fchmod=fchmod,
                            fdopen=os.fdopen, fsync=os.fsync, replace=os.replace, path=os.path, unlink=os.unlink)
    monkeypatch.setattr(auth, "os", proxy)

    def verify(path):
        # Native permissions have separate tests. Windows cannot apply a POSIX mode.
        with monkeypatch.context() as context:
            context.setattr(auth, "os", os)
            return original_read(path)

    monkeypatch.setattr(auth, "read_credentials", verify)
    return requested_modes


@pytest.mark.parametrize("version", [23, 24])
def test_v10_import_is_scoped_read_only_and_returns_no_cookie_values(tmp_path, linux_import, version):
    database = cookie_database(tmp_path, version=version)
    before = database.read_bytes()
    destination = tmp_path / "private" / "session.json"
    result = auth.import_linux_session(database, destination)
    assert json.loads(destination.read_text()) == COOKIES
    assert database.read_bytes() == before
    assert result == {"status": "imported", "credential_names": ["SWID", "espn_s2"], "browser_started": False}
    assert "fictional-session-canary" not in json.dumps(result)
    assert linux_import == [0o600]
    assert not list(destination.parent.glob(".espn-session-*"))


@pytest.mark.parametrize("problem", ["missing", "duplicate", "expired", "encryption", "digest", "padding", "unsafe_value"])
def test_invalid_saved_sessions_do_not_replace_existing_credentials(tmp_path, linux_import, problem):
    def change(rows):
        if problem == "missing":
            rows.pop(0)
        elif problem == "duplicate":
            rows.append(list(rows[0]))
        elif problem == "expired":
            rows[0][4:] = [1, 1]
        elif problem == "encryption":
            rows[0][3] = b"v11" + rows[0][3][3:]
        elif problem == "digest":
            rows[0][3] = encrypted_cookie("fictional-session-canary", host=".other.invalid")
        elif problem == "padding":
            rows[0][3] = b"v10" + b"broken"
        else:
            rows[0][3] = encrypted_cookie("fictional-session-canary;other=value")
    database = cookie_database(tmp_path, change=change)
    destination = tmp_path / "session.json"
    destination.write_text("existing-credential-marker")
    with pytest.raises(ValueError) as error:
        auth.import_linux_session(database, destination)
    assert "fictional-session-canary" not in str(error.value)
    assert destination.read_text() == "existing-credential-marker"
    assert not list(tmp_path.glob(".espn-session-*"))


def test_import_does_not_run_on_other_operating_systems(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "os", SimpleNamespace(name="nt"))
    with pytest.raises(ValueError, match="Linux"):
        auth.import_linux_session(tmp_path / "missing", tmp_path / "session.json")
