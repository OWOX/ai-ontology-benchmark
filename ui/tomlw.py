# Spec: docs/specs/ui.md
"""A small TOML writer for the experiment config the UI saves. Reads a config dict and
returns text; writes nothing. Handles strings, ints, floats, bools, lists, and tables.
"""


def value_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(value_text(item) for item in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{key_text(k)} = {value_text(v)}" for k, v in value.items())
        return "{ " + inner + " }" if inner else "{}"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


def key_text(key: str) -> str:
    bare = key.replace("-", "").replace("_", "")
    return key if key and bare.isascii() and bare.isalnum() else value_text(key)


def dumps_config(config: dict) -> str:
    """Scalars and lists first, then [[models]] entries, then the other tables."""
    lines = [f"{key_text(k)} = {value_text(v)}" for k, v in config.items()
             if not isinstance(v, dict) and k != "models"]
    for model in config.get("models", []):
        lines += ["", "[[models]]"] + [f"{key_text(k)} = {value_text(v)}" for k, v in model.items()]
    for key, table in config.items():
        if isinstance(table, dict):
            lines += ["", f"[{key_text(key)}]"] + [f"{key_text(k)} = {value_text(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"
