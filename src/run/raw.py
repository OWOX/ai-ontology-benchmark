# Spec: docs/specs/run.md
"""Reads one raw file of one AI model. Reads the file at `path` and writes nothing. Both the
run script (to resume) and the evaluate script (to score) use it, so they agree on what a
torn line is.
"""

import json
from pathlib import Path


def is_decision_record(record: dict, decision_models) -> bool:
    """Whether a raw record is scored as a decision-model record. Its `decision` field decides.
    A record written before that field existed falls back to the config rule: its AI model is in
    `decision_models`, the names of the models whose provider is a decision provider."""
    flag = record.get("decision")
    return flag if isinstance(flag, bool) else record["model"] in decision_models


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
