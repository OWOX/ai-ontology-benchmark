# Spec: docs/specs/ui.md
"""API keys kept in <root>/secrets/<provider>.json as {"api_key": "..."}.
Reads and writes only that folder (mode 0700, files 0600). The page only ever gets the last 4 characters.
"""

import json
import os
import re
from pathlib import Path

from src.run.models import KEY_VARIABLES
from ui.common import ApiError


def folder(root: Path) -> Path:
    return root / "secrets"


def file_of(root: Path, provider: object) -> Path:
    if provider not in KEY_VARIABLES:
        raise ApiError(400, f"field 'provider' must be one of {', '.join(KEY_VARIABLES)}")
    return folder(root) / f"{provider}.json"


def read_key(path: Path) -> str:
    try:
        key = json.loads(path.read_text(encoding="utf-8")).get("api_key")
    except (OSError, ValueError, AttributeError):
        return ""
    return key.strip() if isinstance(key, str) else ""


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
        stored = read_key(file_of(root, provider))
        from_env = os.environ.get(variable, "")
        key = from_env or stored
        source = "env" if from_env else "file" if stored else "missing"
        result[provider] = {"variable": variable, "configured": bool(key), "tail": key[-4:], "source": source,
                            "location": f"secrets/{provider}.json" if source == "file" else
                            f"env var {variable}" if source == "env" else None}
    return result


def save(root: Path, provider: object, api_key: object) -> None:
    path = file_of(root, provider)
    key = api_key.strip() if isinstance(api_key, str) else ""
    if not key:
        raise ApiError(400, "field 'api_key' must be a non-empty string")
    if re.search(r"\s", key):
        raise ApiError(400, "field 'api_key' must not contain whitespace")
    folder(root).mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder(root), 0o700)
    if path.is_file():
        write_private(path.with_name(path.name + ".bak"), path.read_text(encoding="utf-8"))
    write_private(path, json.dumps({"api_key": key}) + "\n")


def clear(root: Path, provider: object) -> None:
    file_of(root, provider).unlink(missing_ok=True)


def import_text(root: Path, text: object) -> list[str]:
    """Save each known KEY=VALUE line with a value. Skips comments, blanks, and unknown names."""
    if not isinstance(text, str):
        raise ApiError(400, "field 'text' must be a string")
    found = {}
    for line in text.splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            found[name] = value
    wanted = [(provider, found[variable]) for provider, variable in KEY_VARIABLES.items() if variable in found]
    if not wanted:
        raise ApiError(400, f"field 'text' holds none of {', '.join(KEY_VARIABLES.values())}")
    for provider, key in wanted:
        save(root, provider, key)
    return [provider for provider, _ in wanted]


def env(root: Path) -> dict[str, str]:
    values = {variable: read_key(file_of(root, provider)) for provider, variable in KEY_VARIABLES.items()}
    return {variable: key for variable, key in values.items() if key}
