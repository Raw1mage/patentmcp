#!/usr/bin/env python3
"""Single-ref retry pass for pool pubnos still missing family_id after batch runs.

Why: OPS batch biblio ABORTS processing the rest of a batch when it hits an
unresolvable ref (verified 2026-07-11: 40-ref batch with invalid ref at pos 11
returned exactly the first 10). So batch leaves resolvable refs unfilled.
This pass retries each remaining pubno individually with multiple candidate
epodoc formats.

Env: EPO_CONSUMER_KEY, EPO_CONSUMER_SECRET, PATENTDB_PATH, POOL_FILE (required)
"""
import json, os, re, sqlite3, sys, time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from family_backfill_batch import normalize, strip_kind, get_token, AUTH_URL

DB = os.environ.get("PATENTDB_PATH", "/home/pkcs12/projects/patentmcp/patentdb/patentdb.sqlite")
BIBLIO_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/biblio"
INTERVAL = float(os.environ.get("EPO_RETRY_INTERVAL", "0.3"))


def candidates(pubno: str) -> list[str]:
    cc, body = pubno[:2], pubno[2:]
    cands = []
    n = normalize(pubno)
    if n:
        cands.append(n)
    cands.append(pubno)                      # as-is (kind kept)
    cands.append(f"{cc}{strip_kind(body)}")  # kind stripped
    if cc == "US" and len(body) > 2 and body[:2].isalpha():
        real = body
        cands += [real, real[:2] + strip_kind(real[2:])]
    # dedupe, keep order
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def main():
    key, secret = os.environ.get("EPO_CONSUMER_KEY"), os.environ.get("EPO_CONSUMER_SECRET")
    if not key or not secret:
        sys.exit("EPO credentials required")
    pool = set()
    with open(os.environ["POOL_FILE"]) as f:
        for line in f:
            pool.add(json.loads(line)["pubno"])
    con = sqlite3.connect(DB)
    cur = con.cursor()
    missing = [r[0] for r in cur.execute(
        "SELECT pubno FROM patents WHERE family_id IS NULL ORDER BY pubno") if r[0] in pool]
    print(f"[start] retry targets={len(missing)}", flush=True)

    tok = get_token(key, secret)
    H = {"Authorization": f"Bearer {tok}", "Content-Type": "text/plain"}
    t0 = time.time()
    filled = unresolved = 0
    unresolved_list = []

    for idx, p in enumerate(missing, 1):
        fam = None
        for cand in candidates(p):
            try:
                r = requests.post(BIBLIO_URL, data=cand, headers=H, timeout=45)
            except requests.RequestException:
                time.sleep(3)
                continue
            if r.status_code == 401:
                tok = get_token(key, secret)
                H["Authorization"] = f"Bearer {tok}"
                r = requests.post(BIBLIO_URL, data=cand, headers=H, timeout=45)
            if r.status_code == 403:
                time.sleep(30)
                r = requests.post(BIBLIO_URL, data=cand, headers=H, timeout=45)
            if r.status_code == 200:
                m = re.search(r'family-id="(\d+)"', r.text)
                if m:
                    fam = m.group(1)
                    break
            time.sleep(INTERVAL)
        if fam:
            cur.execute("UPDATE patents SET family_id=? WHERE pubno=? AND family_id IS NULL",
                        (fam, p))
            con.commit()
            filled += 1
        else:
            unresolved += 1
            unresolved_list.append(p)
        if idx % 50 == 0:
            el = time.time() - t0
            print(f"[{idx}/{len(missing)}] filled={filled} unresolved={unresolved} "
                  f"elapsed={el:.0f}s", flush=True)
        time.sleep(INTERVAL)

    print(f"[done] filled={filled} unresolved={unresolved} elapsed={time.time()-t0:.0f}s",
          flush=True)
    if unresolved_list:
        print("[unresolved]", ", ".join(unresolved_list), flush=True)
    con.close()


if __name__ == "__main__":
    main()
