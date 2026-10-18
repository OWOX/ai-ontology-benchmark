# Spec: docs/specs/run.md
"""Reads one raw file of one AI model. Reads the file at `path` and writes nothing. Both the
run script (to resume) and the evaluate script (to score) use it, so they agree on what a
torn line is.
"""

import json
from pathlib import Path


def read_raw(path: Path) -> tuple[list[dict], int]:
    """Return (records, skipped line count) for one raw file.

    A line that does not parse as a JSON object is skipped and counted. A stopped write
    leaves such a line, and a later run ends it with a newline, so it can sit anywhere in
    the file. A missing file gives no records.
    """
    path = Path(path)
    if not path.is_file():
        return [], 0
    records: list[dict] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            skipped += 1
    return records, skipped
