# Spec: docs/specs/ui.md
"""API keys kept in <root>/secrets/<provider>.json as {"api_key": "..."}, plus "account_id" for the providers in
ACCOUNT_VARIABLES. Reads and writes only that folder (mode 0700, files 0600).
The page only ever gets the last 4 characters of a key, and only the source of an account id.
"""

import json
import os
import re
from pathlib import Path

from src.run.models import ACCOUNT_VARIABLES, KEY_VARIABLES
from ui.common import ApiError


def folder(root: Path) -> Path:
    return root / "secrets"


def file_of(root: Path, provider: object) -> Path:
    if provider not in KEY_VARIABLES:
        raise ApiError(400, f"field 'provider' must be one of {', '.join(KEY_VARIABLES)}")
    return folder(root) / f"{provider}.json"


def read_field(path: Path, name: str) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get(name)
    except (OSError, ValueError, AttributeError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def read_key(path: Path) -> str:
    return read_field(path, "api_key")


def write_private(path: Path, text: str) -> None:
    """Write atomically: a temp file in the same folder, mode 0600, then replace."""
    temp = path.with_name(path.name + ".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp, path)


def inspect(root: Path) -> dict:
    result = {}
    for provider, variable in KEY_VARIABLES.items():
        path = file_of(root, provider)
        stored = read_key(path)
        from_env = os.environ.get(variable, "").strip()
        key = from_env or stored
        source = "env" if from_env else "file" if stored else "missing"
        entry = {"variable": variable, "configured": bool(key), "tail": key[-4:], "source": source,
                 "location": f"secrets/{provider}.json" if source == "file" else
                 f"env var {variable}" if source == "env" else None}
        if provider in ACCOUNT_VARIABLES:
            account_env = os.environ.get(ACCOUNT_VARIABLES[provider], "").strip()
            account_file = read_field(path, "account_id")
            account = "env" if account_env else "file" if account_file else "missing"
            entry["account"] = {"variable": ACCOUNT_VARIABLES[provider], "source": account}
            entry["configured"] = bool(key) and account != "missing"
        result[provider] = entry
    return result


def check(name: str, value: object) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if re.search(r"\s", text):
        raise ApiError(400, f"field '{name}' must not contain whitespace")
    return text


def save(root: Path, provider: object, api_key: object, account_id: object = None) -> None:
    """Save the non-empty fields and keep the others. A provider without an account id refuses one."""
    path = file_of(root, provider)
    if account_id is not None and provider not in ACCOUNT_VARIABLES:
        raise ApiError(400, f"field 'account_id' is not used by provider '{provider}'")
    key, account = check("api_key", api_key), check("account_id", account_id)
    if not key and not account:
        raise ApiError(400, "field 'api_key' must be a non-empty string")
    fields = {name: value for name, value in (("api_key", read_key(path)), ("account_id", read_field(path, "account_id"))) if value}
    fields.update({name: value for name, value in (("api_key", key), ("account_id", account)) if value})
    folder(root).mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder(root), 0o700)
    write_private(path, json.dumps(fields) + "\n")


def clear(root: Path, provider: object) -> None:
    file_of(root, provider).unlink(missing_ok=True)


def env(root: Path) -> dict[str, str]:
    values = {}
    for provider, variable in KEY_VARIABLES.items():
        path = file_of(root, provider)
        values[variable] = read_key(path)
        if provider in ACCOUNT_VARIABLES:
            values[ACCOUNT_VARIABLES[provider]] = read_field(path, "account_id")
    return {variable: value for variable, value in values.items() if value}
