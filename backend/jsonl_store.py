"""Small, strict JSON Lines storage helpers used by audit pipelines.

JSONL is the canonical format for experiment records in this repository.  A
single-record file (for example an audit manifest) is still JSONL so callers
can use the same validated reader everywhere.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


JsonObject = dict[str, Any]


class JsonlFormatError(ValueError):
    """Raised when a JSONL file contains an invalid or non-object row."""


def read_jsonl(path: Path, *, required: bool = True) -> list[JsonObject]:
    """Read a JSONL file and validate that every non-empty line is an object."""

    return list(iter_jsonl(path, required=required))


def iter_jsonl(path: Path, *, required: bool = True) -> Iterator[JsonObject]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(f"JSONL file not found: {path}")
        return

    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise JsonlFormatError(
                    f"Invalid JSON in {path} at line {line_number}: {error.msg}"
                ) from error
            if not isinstance(row, dict):
                raise JsonlFormatError(
                    f"Expected an object in {path} at line {line_number}, "
                    f"got {type(row).__name__}"
                )
            yield row


def read_one_jsonl(path: Path) -> JsonObject:
    """Read a JSONL file that must contain exactly one object."""

    rows = read_jsonl(path)
    if len(rows) != 1:
        raise JsonlFormatError(f"Expected exactly one row in {path}, got {len(rows)}")
    return rows[0]
