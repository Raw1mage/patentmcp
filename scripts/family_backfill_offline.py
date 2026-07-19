#!/usr/bin/env python3
"""Host-local, MCP-free full INPADOC family_id backfill for patentdb.

Why this exists: the MCP tool patent_family_backfill runs INSIDE the MCP
request/response model, which has a hard client-transport timeout (~60-120s).
No amount of internal looping escapes that ceiling — a full 30k-row sweep
cannot complete in one MCP request. This script talks straight to
patentdb.sqlite + EPO OPS with `requests`, so it runs to completion in ONE
shell invocation with zero MCP round-trips.

Ported, verified logic (identical semantics to the MCP tool):
  - to_docdb: kind code OPTIONAL (CN/TW numbers carry no kind -> 'CC.NUMBER')
  - _fam_key: kind-stripped country+number key for family-coverage matching
  - family coverage: one EPO call stamps EVERY in-pool member of that family

Idempotent: only rows still missing family_id are targeted; re-running resumes.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

import requests

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
BASE_URL = "https://ops.epo.org/3.2/rest-services"

DB_PATH = os.environ.get(
    "PATENTDB_PATH",
    "/home/pkcs12/projects/patentmcp/patentdb/patentdb.sqlite",
)
MIN_INTERVAL = float(os.environ.get("EPO_MIN_INTERVAL", "4.2"))  # 15/min safe
MAX_RETRIES = 3


# ── pubno helpers — number-format logic owned by the converter SSOT ───────
# (pubno_convert.py, BR_20260719). This host-local script runs outside the MCP
# process, so inject src/ onto sys.path and import the canonical to_docdb rather
# than re-porting a simplified copy (the old inline version had NO US pre-grant
# 10↔11 variant support — a scatter regression this convergence removes).
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
from patent_mcp_server.pubno_convert import to_docdb  # noqa: E402  (SSOT re-use)


def fam_key(pn: str) -> str:
    s = re.sub(r"[\s/\-,\.]+", "", (pn or "")).upper()
    m = re.match(r"^([A-Z]{2})?(.+?)([A-Z]\d*)?$", s)
    if not m:
        return s
    return f"{m.group(1) or ''}{m.group(2) or ''}"


def _txt(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("$", "")).strip()
    return str(node or "").strip()


# ── EPO OPS client (minimal, requests-based) ─────────────────────────────
class EPO:
    def __init__(self) -> None:
        self.key = os.environ["EPO_CONSUMER_KEY"]
        self.secret = os.environ["EPO_CONSUMER_SECRET"]
        self._token: Optional[str] = None
        self._exp = 0.0
        self._last = 0.0
        self._cooldown = 0.0
        self.s = requests.Session()

    def _token_value(self) -> str:
        if self._token and time.monotonic() < self._exp - 60:
            return self._token
        b64 = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
        r = self.s.post(
            AUTH_URL,
            headers={"Authorization": f"Basic {b64}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"}, timeout=30,
        )
        r.raise_for_status()
        j = r.json()
        self._token = j["access_token"]
        self._exp = time.monotonic() + int(j.get("expires_in", 1200))
        return self._token

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._cooldown:
            time.sleep(self._cooldown - now)
        gap = time.monotonic() - self._last
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

    def family(self, pub: str) -> Dict[str, Any]:
        docdb = to_docdb(pub)
        if not docdb:
            return {"success": False, "error": f"cannot parse pub number: {pub}"}
        path = f"/family/publication/docdb/{docdb}"
        for attempt in range(MAX_RETRIES):
            self._pace()
            try:
                tok = self._token_value()
                r = self.s.get(BASE_URL + path,
                               headers={"Authorization": f"Bearer {tok}",
                                        "Accept": "application/json"},
                               timeout=30)
                self._last = time.monotonic()
            except Exception as e:  # noqa: BLE001
                if attempt == MAX_RETRIES - 1:
                    return {"success": False, "error": f"request: {e}"}
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 404:
                return {"success": True, "pub": pub, "family_id": None,
                        "count": 0, "members": []}
            if r.status_code in (403, 429) or r.status_code >= 500:
                # throttled / overloaded -> back off and retry
                self._cooldown = time.monotonic() + 20
                if attempt == MAX_RETRIES - 1:
                    return {"success": False,
                            "error": f"http {r.status_code}"}
                continue
            if r.status_code == 401:  # token stale
                self._token = None
                continue
            try:
                data = r.json()
            except Exception as e:  # noqa: BLE001
                return {"success": False, "error": f"json: {e}"}
            return self._parse_family(pub, data)
        return {"success": False, "error": "max_retries"}

    @staticmethod
    def _parse_family(pub: str, data: Dict[str, Any]) -> Dict[str, Any]:
        fam = (data.get("ops:world-patent-data", {})
                   .get("ops:patent-family", {}))
        members = fam.get("ops:family-member", [])
        if isinstance(members, dict):
            members = [members]
        family_id = fam.get("@family-id")
        if not family_id and members:
            family_id = members[0].get("@family-id")
        seen, out = set(), []
        for m in members:
            dids = m.get("publication-reference", {}).get("document-id", [])
            dids = dids if isinstance(dids, list) else [dids]
            for d in dids:
                if d.get("@document-id-type") == "docdb":
                    cc = _txt(d.get("country"))
                    num = _txt(d.get("doc-number"))
                    kind = _txt(d.get("kind"))
                    key = f"{cc}{num}"
                    if cc and num and key not in seen:
                        seen.add(key)
                        out.append(f"{cc}{num}{kind}")
        return {"success": True, "pub": pub, "family_id": family_id,
                "count": len(out), "members": out}


# ── main sweep ───────────────────────────────────────────────────────────
def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0 = all
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT pubno FROM patents "
        "WHERE family_id IS NULL OR TRIM(family_id)='' ORDER BY pubno"
    ).fetchall()
    targets = [r["pubno"] for r in rows]
    if limit:
        targets = targets[:limit]
    total = len(targets)
    target_keys = {fam_key(p): p for p in targets}

    epo = EPO()
    covered: Dict[str, str] = {}
    filled = family_covered = failed = calls = 0
    errors: List[Dict[str, str]] = []
    t0 = time.monotonic()

    def _flush_stamp(write_pub: str, fid: str) -> None:
        conn.execute(
            "UPDATE patents SET family_id=?, updated_at=? "
            "WHERE pubno=? AND (family_id IS NULL OR TRIM(family_id)='')",
            (fid, str(int(time.time())), write_pub),
        )

    print(f"[start] targets={total} db={DB_PATH}", file=sys.stderr, flush=True)

    for idx, pub in enumerate(targets):
        pk = fam_key(pub)
        if pk in covered:
            family_covered += 1
            continue
        res = epo.family(pub)
        calls += 1
        fid = res.get("family_id")
        if res.get("success") and fid:
            fid_s = str(fid)
            members = res.get("members") or [pub]
            stamped = 0
            for m in members:
                mk = fam_key(m)
                if mk in covered:
                    continue
                orig = target_keys.get(mk)
                if orig is None and mk != pk:
                    continue
                write_pub = orig if orig is not None else m
                _flush_stamp(write_pub, fid_s)
                covered[mk] = fid_s
                stamped += 1
            filled += 1
            if stamped > 1:
                family_covered += stamped - 1
        else:
            failed += 1
            if len(errors) < 100:
                errors.append({"pubno": pub,
                               "error": res.get("error") or "no_family_id"})

        # commit + progress every 25 real calls
        if calls % 25 == 0:
            conn.commit()
            el = time.monotonic() - t0
            done = filled + family_covered + failed
            rate = calls / el * 60 if el > 0 else 0
            print(f"[{done}/{total}] calls={calls} filled={filled} "
                  f"covered={family_covered} failed={failed} "
                  f"{rate:.0f}call/min elapsed={el:.0f}s",
                  file=sys.stderr, flush=True)

    conn.commit()
    still_missing = conn.execute(
        "SELECT COUNT(*) FROM patents "
        "WHERE family_id IS NULL OR TRIM(family_id)=''"
    ).fetchone()[0]
    conn.close()

    summary = {
        "success": True, "total_targets": total, "filled": filled,
        "family_covered": family_covered, "failed": failed,
        "calls_made": calls, "still_missing_after": still_missing,
        "elapsed_sec": round(time.monotonic() - t0, 1),
        "errors_sample": errors[:20],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
