"""Enforce per-file coverage floors.

This is meant to complement (not replace) the global coverage floor.

Usage:
  uv run pytest --cov=azure_opencode_setup --cov-report=json:coverage.json
  uv run python scripts/check_cov.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

_COV_JSON = Path("coverage.json")

_ERR_NOT_OBJECT = "coverage.json must be a JSON object"
_ERR_NO_FILES = "coverage.json missing 'files' map"
_ERR_UNEXPECTED_FILE = "coverage.json includes non-package file: {path}"
_ERR_MISSING_PCT = "coverage.json missing percent_covered for: {path}"
_ERR_BELOW_FLOOR = "{path}: {got}% < {floor}%"


_REQ_BASE: dict[str, float] = {
    "src/azure_opencode_setup/merge.py": 98.0,
    "src/azure_opencode_setup/io.py": 98.0,
    "src/azure_opencode_setup/types.py": 98.0,
    "src/azure_opencode_setup/errors.py": 98.0,
    "src/azure_opencode_setup/cli.py": 90.0,
}


def _requirements() -> dict[str, float]:
    req = dict(_REQ_BASE)
    if sys.platform != "win32":
        req["src/azure_opencode_setup/paths.py"] = 98.0
        req["src/azure_opencode_setup/locking.py"] = 98.0
    return req


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _load_coverage_json() -> dict[str, object]:
    data_obj: object = json.loads(_COV_JSON.read_text(encoding="utf-8"))
    if not isinstance(data_obj, dict):
        raise SystemExit(_ERR_NOT_OBJECT)
    return cast("dict[str, object]", data_obj)


def _get_files_map(data: dict[str, object]) -> dict[str, object]:
    files_obj = data.get("files")
    if not isinstance(files_obj, dict):
        raise SystemExit(_ERR_NO_FILES)
    return cast("dict[str, object]", files_obj)


def _enforce_only_package_files(files: dict[str, object]) -> None:
    for key in files:
        norm = _norm(key)
        if "azure_opencode_setup" not in norm:
            raise SystemExit(_ERR_UNEXPECTED_FILE.format(path=norm))


def _percent_covered(entry_obj: object, *, path: str) -> float:
    if not isinstance(entry_obj, dict):
        raise SystemExit(_ERR_MISSING_PCT.format(path=path))
    entry = cast("dict[str, object]", entry_obj)
    summary_obj = entry.get("summary")
    if not isinstance(summary_obj, dict):
        raise SystemExit(_ERR_MISSING_PCT.format(path=path))
    summary = cast("dict[str, object]", summary_obj)
    pct = summary.get("percent_covered")
    if not isinstance(pct, (int, float)):
        raise SystemExit(_ERR_MISSING_PCT.format(path=path))
    return float(pct)


def _suffix_from_src(path: str) -> str:
    norm = _norm(path)
    idx = norm.find("/src/")
    if idx == -1:
        return norm
    return norm[idx + 1 :]


def _index_by_suffix(files: dict[str, object]) -> dict[str, float]:
    by_suffix: dict[str, float] = {}
    for raw_path, entry_obj in files.items():
        pct = _percent_covered(entry_obj, path=raw_path)
        by_suffix[_suffix_from_src(raw_path)] = pct
    return by_suffix


def _get_pct(by_suffix: dict[str, float], req_path: str) -> float | None:
    exact = by_suffix.get(req_path)
    if exact is not None:
        return exact
    for k, v in by_suffix.items():
        if k.endswith(req_path):
            return v
    return None


def _enforce_floors(by_suffix: dict[str, float]) -> None:
    for req_path, floor in _requirements().items():
        got = _get_pct(by_suffix, req_path)
        if got is None:
            raise SystemExit(_ERR_MISSING_PCT.format(path=req_path))
        if got < floor:
            raise SystemExit(_ERR_BELOW_FLOOR.format(path=req_path, got=got, floor=floor))


def main() -> None:
    """Load coverage JSON and enforce per-file floors."""
    data = _load_coverage_json()
    files = _get_files_map(data)
    _enforce_only_package_files(files)
    by_suffix = _index_by_suffix(files)
    _enforce_floors(by_suffix)


if __name__ == "__main__":
    main()
