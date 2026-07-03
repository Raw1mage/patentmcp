"""test_screening_build.py — golden: the landing screening_build.py produces a
byte-equal CSV to calling the pure _pure.screening functions directly (the same
logic the container used). This proves the R13 landing plane is behavior-neutral.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "patentworks" / "scripts" / "screening_build.py"

sys.path.insert(0, str(REPO / "src"))
from patent_mcp_server._pure.screening import (  # noqa: E402
    build_csv,
    dedup_by_family,
    resolve_columns,
)

_RECORDS = [
    {"pubno": "US20230081319A1", "appno": "17/123456", "title": "Escrow method",
     "abstract": "A method for escrow.", "claim1": "1. A method comprising...",
     "family_id": "F1", "cpc": "G06Q20/00", "assignee": "ACME",
     "prio_date": "2021-01-01", "app_date": "2022-01-01", "pub_date": "2023-03-01"},
    {"pubno": "US20230081320A1", "appno": "17/123457", "title": "Escrow device",
     "abstract": "A device for escrow.", "claim1": "1. A device comprising...",
     "family_id": "F1", "cpc": "G06Q20/02", "assignee": "ACME",
     "prio_date": "2021-01-02", "app_date": "2022-01-02", "pub_date": "2023-03-02"},
    {"pubno": "TWI854998B", "appno": "110123456", "title": "履約保證方法",
     "abstract": "一種履約保證方法。", "claim1": "1. 一種方法...",
     "family_id": "", "cpc": "G06Q20/08", "assignee": "宏碁",
     "prio_date": "", "app_date": "2021-05-01", "pub_date": "2024-01-01"},
]


def _golden(records, purpose="landscape", extra=None, exclude=None) -> bytes:
    deduped = dedup_by_family([dict(r) for r in records])
    cols = resolve_columns(purpose=purpose, extra=extra or [], exclude=exclude or [])
    return build_csv(deduped, cols)


def test_screening_build_byte_equal(tmp_path):
    in_path = tmp_path / "records.json"
    out_path = tmp_path / "out.csv"
    in_path.write_text(json.dumps({"records": _RECORDS}, ensure_ascii=False), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--in", str(in_path), "--out", str(out_path),
         "--purpose", "landscape"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"script failed: {proc.stdout}\n{proc.stderr}"
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["success"] is True

    produced = out_path.read_bytes()
    expected = _golden(_RECORDS, purpose="landscape")
    assert produced == expected, "screening_build CSV differs from pure golden"


def test_screening_build_bare_list(tmp_path):
    in_path = tmp_path / "records.json"
    out_path = tmp_path / "out.csv"
    in_path.write_text(json.dumps(_RECORDS, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--in", str(in_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"script failed: {proc.stdout}\n{proc.stderr}"
    assert out_path.read_bytes() == _golden(_RECORDS)


def test_screening_build_bad_input_typed_error(tmp_path):
    in_path = tmp_path / "records.json"
    out_path = tmp_path / "out.csv"
    in_path.write_text('{"no_records_key": 1}', encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--in", str(in_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0
    env = json.loads(proc.stdout.strip().splitlines()[-1])
    assert env["success"] is False
    assert env["error_code"] == "BAD_INPUT"
    # no traceback leaked to stdout
    assert "Traceback" not in proc.stdout
