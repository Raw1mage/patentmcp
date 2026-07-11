#!/usr/bin/env python3
"""Batch INPADOC family_id backfill via EPO OPS published-data batch biblio.

Replaces family_backfill_offline.py (per-pub, ~13/min, ~31h) with batch POST
(100 refs/call, ~2s/call) -> full pool backfill in minutes.

Contract (verified 2026-07-11 by live probes):
  POST https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/biblio
  body: comma-separated epodoc refs
  resp: XML, each <exchange-document family-id=".." country=".." doc-number="..">

epodoc ref normalization rules (probed per class, 2026-07-11):
  CN utility (body 2xxxxxxxx, 9 digits) -> append 'U'        CN204087418  -> CN204087418U
  US grant w/ leading zeros            -> strip zeros+kind   US09005141B1 -> US9005141
  US app 13-digit (year+7serial)       -> year+6serial       US20150077282A1 -> US2015077282
  US app 12-digit                      -> strip kind         US2015141794A1  -> US2015141794
  USxx misattached prefix (USAU.., USDE..) -> strip 'US'+kind  USAU2020278020A1 -> AU2020278020
  TW grant TWInnnnnn                   -> append 'B'         TWI470582 -> TWI470582B
  WO/EP/JP apps                        -> strip kind
  known-unresolvable: KR grants, JP grants (kind-stripped 404), TW 2026 apps (EPO lag)

Idempotent: only rows with family_id IS NULL are targeted; re-run resumes.
Env: EPO_CONSUMER_KEY, EPO_CONSUMER_SECRET, PATENTDB_PATH (default host path)
     POOL_FILE (optional): pool_membership.jsonl path — restrict targets to
     pool pubnos only (project scope), instead of the whole cross-project DB.
"""
import os, re, sqlite3, sys, time
import requests

DB = os.environ.get("PATENTDB_PATH", "/home/pkcs12/projects/patentmcp/patentdb/patentdb.sqlite")
BATCH = int(os.environ.get("EPO_BATCH_SIZE", "100"))
INTERVAL = float(os.environ.get("EPO_BATCH_INTERVAL", "1.0"))
AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
BIBLIO_URL = "https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/biblio"

KIND_RE = re.compile(r"^(.*?)([A-CUY]\d?)$")  # trailing kind code


def strip_kind(body: str) -> str:
    m = KIND_RE.match(body)
    return m.group(1) if m and m.group(1) and m.group(1)[-1].isdigit() else body


def normalize(pubno: str) -> str | None:
    """pubno (DB form) -> epodoc ref candidate. None = known-unresolvable, skip."""
    if not re.fullmatch(r"[A-Z]{2,5}\w{4,}", pubno):
        return None
    cc, body = pubno[:2], pubno[2:]

    # misattached US prefix: USAU2020278020A1 / USDE... -> strip US
    if cc == "US" and len(body) > 2 and body[:2].isalpha():
        real = body  # e.g. AU2020278020A1
        return real[:2] + strip_kind(real[2:])

    if cc == "CN":
        digits = strip_kind(body)
        if len(digits) == 9 and digits.startswith("2") and digits.isdigit():
            return f"CN{digits}U"  # utility model
        return f"CN{digits}"

    if cc == "US":
        digits = strip_kind(body)
        if not digits.isdigit():
            return pubno
        if len(digits) == 11:  # 13-digit app form year(4)+serial(7) -> year+serial[1:]
            return f"US{digits[:4]}{digits[5:]}"
        if len(digits) == 10 and digits[:2] == "20":  # already epodoc app form
            return f"US{digits}"
        return f"US{int(digits)}"  # grant: strip leading zeros

    if cc == "TW":
        if body.startswith("I") and body[1:].isdigit():
            return f"TWI{body[1:]}B"  # invention grant
        if body.startswith("M") and body[1:].isdigit():
            return f"TWM{body[1:]}U"  # utility model grant
        return f"TW{strip_kind(body)}"

    # WO / EP / JP / KR / others: strip kind
    return f"{cc}{strip_kind(body)}"


def get_token(key, secret):
    r = requests.post(AUTH_URL, data={"grant_type": "client_credentials"},
                      auth=(key, secret), timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def parse_blocks(xml: str) -> dict[str, str]:
    """Return {id_string: family_id} for every exchange-document block.

    id_strings include header CC+docnum and every document-id doc-number text
    (epodoc form embeds country), so candidates match regardless of format.
    """
    out = {}
    for block in re.split(r"<exchange-document\s", xml)[1:]:
        head = block[:400]
        fam = re.search(r'family-id="(\d+)"', head)
        if not fam:
            continue
        fam = fam.group(1)
        cc = re.search(r'country="(\w+)"', head)
        dn = re.search(r'doc-number="(\w+)"', head)
        if cc and dn:
            out[f"{cc.group(1)}{dn.group(1)}"] = fam
        for m in re.finditer(r"<doc-number>(\w+)</doc-number>", block[:3000]):
            out[m.group(1)] = fam
    return out


def main():
    key = os.environ.get("EPO_CONSUMER_KEY")
    secret = os.environ.get("EPO_CONSUMER_SECRET")
    if not key or not secret:
        sys.exit("EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET required in env")

    con = sqlite3.connect(DB)
    cur = con.cursor()
    targets = [r[0] for r in cur.execute(
        "SELECT pubno FROM patents WHERE family_id IS NULL ORDER BY pubno")]
    pool_file = os.environ.get("POOL_FILE")
    if pool_file:
        import json
        pool = set()
        with open(pool_file) as f:
            for line in f:
                pool.add(json.loads(line)["pubno"])
        targets = [p for p in targets if p in pool]
        print(f"[scope] pool_file={pool_file} pool_uniq={len(pool)}", flush=True)

    cand_map = {}   # candidate ref -> orig pubno
    skipped = 0
    for p in targets:
        c = normalize(p)
        if c:
            cand_map.setdefault(c, p)
        else:
            skipped += 1
    cands = list(cand_map)
    total = len(cands)
    print(f"[start] targets={len(targets)} candidates={total} "
          f"skipped_unresolvable={skipped} batch={BATCH}", flush=True)
    if not total:
        print("[done] nothing to fill", flush=True)
        return

    tok = get_token(key, secret)
    t0 = time.time()
    filled = failed_batches = no_match = 0

    for i in range(0, total, BATCH):
        chunk = cands[i:i + BATCH]
        body = ", ".join(chunk)
        r = None
        for attempt in (1, 2, 3):
            try:
                r = requests.post(BIBLIO_URL, data=body,
                                  headers={"Authorization": f"Bearer {tok}",
                                           "Content-Type": "text/plain"}, timeout=90)
                if r.status_code == 401 or (r.status_code == 400 and "access_token" in r.text.lower()):
                    tok = get_token(key, secret)
                    continue
                if r.status_code == 403:
                    time.sleep(30 * attempt)
                    continue
                break
            except requests.RequestException as e:
                print(f"[warn] batch@{i} attempt{attempt}: {e}", flush=True)
                time.sleep(5 * attempt)
        if r is None or r.status_code != 200:
            failed_batches += 1
            code = r.status_code if r is not None else "n/a"
            print(f"[warn] batch@{i} HTTP {code}", flush=True)
            time.sleep(INTERVAL)
            continue

        ids = parse_blocks(r.text)
        n = 0
        for cand in chunk:
            fam = ids.get(cand)
            if fam:
                cur.execute("UPDATE patents SET family_id=? WHERE pubno=? AND family_id IS NULL",
                            (fam, cand_map[cand]))
                n += cur.rowcount
        con.commit()
        filled += n
        no_match += len(chunk) - n
        el = time.time() - t0
        print(f"[{min(i+BATCH,total)}/{total}] filled={filled} no_match={no_match} "
              f"failed_batches={failed_batches} {((i+BATCH)/el*60):.0f}/min elapsed={el:.0f}s",
              flush=True)
        time.sleep(INTERVAL)

    print(f"[done] filled={filled} no_match={no_match} failed_batches={failed_batches} "
          f"skipped_unresolvable={skipped} elapsed={time.time()-t0:.0f}s", flush=True)
    con.close()


if __name__ == "__main__":
    main()
