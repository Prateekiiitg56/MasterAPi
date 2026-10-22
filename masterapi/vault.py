"""Encrypted on-disk store for named API key sets and client access tokens.

The vault is a Fernet-encrypted JSON file. Its encryption key lives in the OS
keyring (Windows Credential Manager, macOS Keychain, Secret Service) or, for
headless machines, in the MASTERAPI_KEY environment variable.
"""

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .providers import OPERATIONS, OVERRIDABLE, provider_for

KEYRING_SERVICE = "masterapi"
KEYRING_USER = "vault-key"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class VaultError(Exception):
    pass


class UnknownAlias(VaultError):
    pass


def home() -> Path:
    return Path(os.environ.get("MASTERAPI_HOME") or Path.home() / ".masterapi")


def _encryption_key(create: bool) -> bytes:
    env = os.environ.get("MASTERAPI_KEY")
    if env:
        return env.encode()

    import keyring
    from keyring.errors import KeyringError

    try:
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if key is None:
            if not create:
                # A vault exists but its key is gone: making a new key would
                # make the old vault unreadable and the next save would wipe it.
                raise VaultError(
                    "vault exists but its encryption key is missing from the OS keyring; "
                    "set MASTERAPI_KEY to the original key"
                )
            key = Fernet.generate_key().decode()
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    except KeyringError as e:
        raise VaultError(f"no usable OS keyring ({e}); set MASTERAPI_KEY (see `masterapi keygen`)") from e
    return key.encode()


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise VaultError(f"invalid name '{name}': 1-64 letters, digits, '.', '_' or '-'")


def _dedupe(keys: list[str]) -> list[str]:
    return list(dict.fromkeys(k.strip() for k in keys if k and k.strip()))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _migrate(data: dict) -> dict:
    """Upgrade v0.1 vaults: single plaintext token, single `model` field."""
    data.setdefault("aliases", {})
    tokens = data.setdefault("tokens", {})
    if old := data.pop("token", None):
        tokens.setdefault("default", {"hash": _hash(old), "aliases": None, "admin": False, "created": _now()})
    for alias in data["aliases"].values():
        if "model" in alias:
            model = alias.pop("model")
            alias["models"] = {"chat": model} if model else {}
    return data


def _validate(name: str, alias: dict) -> None:
    try:
        provider = provider_for(alias)
    except ValueError as e:
        raise VaultError(f"alias '{name}': {e}") from None
    if provider.needs_key and not alias["keys"]:
        raise VaultError("at least one API key is required")
    unknown = set(alias["models"]) - set(OPERATIONS)
    if unknown:
        raise VaultError(f"unknown model operation {sorted(unknown)}")


class Vault:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else home() / "vault.enc"
        self._fernet: Fernet | None = None
        self._data: dict | None = None
        self._mtime: int | None = None
        self._lock = threading.Lock()

    def _cipher(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(_encryption_key(create=not self.path.exists()))
        return self._fernet

    def _load(self) -> dict:
        """Return vault data, re-reading the file when it changed on disk."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return {"aliases": {}, "tokens": {}}
        if mtime != self._mtime:
            try:
                raw = self._cipher().decrypt(self.path.read_bytes())
            except InvalidToken as e:
                raise VaultError("cannot decrypt vault: wrong MASTERAPI_KEY or keyring entry") from e
            self._data, self._mtime = _migrate(json.loads(raw)), mtime
        return self._data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._cipher().encrypt(json.dumps(data).encode()))
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        self._data, self._mtime = data, self.path.stat().st_mtime_ns

    @contextmanager
    def _edit(self):
        """Mutate a copy and save it; nothing changes if the body raises."""
        with self._lock:
            data = copy.deepcopy(self._load())
            yield data
            self._save(data)

    @staticmethod
    def _alias(data: dict, name: str) -> dict:
        try:
            return data["aliases"][name]
        except KeyError:
            raise UnknownAlias(f"no alias named '{name}'") from None

    # Aliases

    def aliases(self) -> dict[str, dict]:
        return copy.deepcopy(self._load()["aliases"])

    def get(self, name: str) -> dict:
        return copy.deepcopy(self._alias(self._load(), name))

    def add(self, name: str, provider: str, keys: list[str], *, models: dict | None = None,
            force: bool = False, **overrides) -> None:
        """Create an alias. `overrides` may set base_url, adapter, auth, capabilities, headers."""
        _check_name(name)
        if bad := set(overrides) - set(OVERRIDABLE):
            raise VaultError(f"unknown alias field {sorted(bad)}")
        alias = {"provider": provider, "keys": _dedupe(keys),
                 "models": {k: v for k, v in (models or {}).items() if v},
                 **{k: v for k, v in overrides.items() if v not in (None, "")}}
        _validate(name, alias)
        with self._edit() as data:
            if name in data["aliases"] and not force:
                raise VaultError(f"alias '{name}' already exists (use --force to replace it)")
            data["aliases"][name] = alias

    def update(self, name: str, *, models: dict | None = None, **overrides) -> None:
        """None leaves a field unchanged; "" clears it."""
        if bad := set(overrides) - set(OVERRIDABLE):
            raise VaultError(f"unknown alias field {sorted(bad)}")
        with self._edit() as data:
            alias = self._alias(data, name)
            for op, model in (models or {}).items():
                if model == "":
                    alias["models"].pop(op, None)
                elif model is not None:
                    alias["models"][op] = model
            for k, v in overrides.items():
                if v == "":
                    alias.pop(k, None)
                elif v is not None:
                    alias[k] = v
            _validate(name, alias)

    def remove(self, name: str) -> None:
        with self._edit() as data:
            self._alias(data, name)
            del data["aliases"][name]

    def add_keys(self, name: str, keys: list[str]) -> int:
        with self._edit() as data:
            alias = self._alias(data, name)
            before = len(alias["keys"])
            alias["keys"] = _dedupe(alias["keys"] + keys)
            return len(alias["keys"]) - before

    def remove_key(self, name: str, *, ending: str | None = None, fingerprint: str | None = None) -> int:
        """Remove keys of alias `name` matching their last characters or their fingerprint."""
        from .keypool import fingerprint as fp

        if fingerprint:
            def match(k): return fp(k) == fingerprint
        elif ending and len(ending) >= 4:
            def match(k): return k.endswith(ending)
        else:
            raise VaultError("give at least the last 4 characters of the key")
        with self._edit() as data:
            alias = self._alias(data, name)
            kept = [k for k in alias["keys"] if not match(k)]
            if len(kept) == len(alias["keys"]):
                raise VaultError(f"no matching key in '{name}'")
            if not kept and provider_for(alias).needs_key:
                raise VaultError("refusing to remove the last key; remove the alias instead")
            removed = len(alias["keys"]) - len(kept)
            alias["keys"] = kept
            return removed

    # Client access tokens (stored as SHA-256 hashes; plaintext shown once)

    def create_token(self, name: str, aliases: list[str] | None = None, admin: bool = False) -> str:
        _check_name(name)
        token = "mapi-" + secrets.token_urlsafe(32)
        with self._edit() as data:
            if name in data["tokens"]:
                raise VaultError(f"token '{name}' already exists; revoke it first")
            data["tokens"][name] = {"hash": _hash(token), "aliases": aliases or None,
                                    "admin": admin, "created": _now()}
        return token

    def list_tokens(self) -> list[dict]:
        return [{"name": n, **{k: v for k, v in t.items() if k != "hash"}}
                for n, t in sorted(self._load()["tokens"].items())]

    def revoke_token(self, name: str) -> None:
        with self._edit() as data:
            if data["tokens"].pop(name, None) is None:
                raise VaultError(f"no token named '{name}'")

    def verify_token(self, token: str) -> dict | None:
        """Return the token's record (name, aliases, admin) or None."""
        if not token:
            return None
        digest = _hash(token)
        for name, t in self._load()["tokens"].items():
            if hmac.compare_digest(digest, t["hash"]):
                return {"name": name, "aliases": t["aliases"], "admin": t["admin"]}
        return None
