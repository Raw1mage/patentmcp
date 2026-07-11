#!/usr/bin/env python3
"""B 層核心精析集選案 pipeline (家族去重 + 選最完整代表案).

依賴 patentdb.sqlite 的 INPADOC family_id 回填 (DD-26/27 離線腳本).
邏輯:
  1. membership 池 pubno -> join patents 取 family_id
  2. 有 family_id: 按 family 分組; 每組選「最完整代表案」
  3. 無 family_id (尚未回填 or 單體案): 各自成組 (代表案=自己)
  4. 輸出: 家族層去重後的代表案清單 + 去重統計

代表案評分 (DD-31, 依實資料驗出; title_en 全空故不計):
  - 內容完整度: len(claim1)*2 + len(abstract) + len(cpc_codes) + len(ipc_codes)
  - 書目完整度: has(publication_date)+has(priority_date) 各 +500 bonus
  - tiebreak: publication_date 最早 -> pubno 字典序

冪等/可重跑: 純讀 DB + membership, 不改 DB. 回填進度變 -> 重跑得新結果.
"""
from __future__ import annotations
import json, os, sqlite3, sys
from collections import defaultdict

DB = os.environ.get("PATENTDB_PATH",
    "/home/pkcs12/projects/patentmcp/patentdb/patentdb.sqlite")
POOL = os.environ.get("POOL_MEMBERSHIP", sys.argv[1] if len(sys.argv) > 1 else "")
OUT = os.environ.get("B_LAYER_OUT", sys.argv[2] if len(sys.argv) > 2 else "")


def score(r: sqlite3.Row) -> tuple:
    """代表案評分. 回傳 sort key (越大越優先當代表案)."""
    content = (len(r["claim1"] or "") * 2 + len(r["abstract"] or "")
               + len(r["cpc_codes"] or "") + len(r["ipc_codes"] or ""))
    biblio = (500 if r["publication_date"] else 0) + (500 if r["priority_date"] else 0)
    # tiebreak: pub_date 最早優先 -> 用負字串反向 (空日期排最後)
    pd = r["publication_date"] or "99999999"
    return (content + biblio, )  # 主分; tiebreak 在排序時另處理


def main() -> None:
    if not POOL or not OUT:
        sys.exit("usage: b_layer_select.py <pool_membership.jsonl> <out.json>")
    pool = [json.loads(l) for l in open(POOL)]
    pool_pubs = list(dict.fromkeys(m["pubno"] for m in pool))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TEMP TABLE poolpub(pubno TEXT PRIMARY KEY)")
    con.executemany("INSERT OR IGNORE INTO poolpub VALUES(?)", [(p,) for p in pool_pubs])

    rows = con.execute("""
      SELECT p.pubno, p.country, p.kind, p.family_id,
             p.title_orig, p.abstract, p.claim1, p.cpc_codes, p.ipc_codes,
             p.publication_date, p.priority_date, p.application_date
      FROM poolpub pp JOIN patents p ON pp.pubno=p.pubno
    """).fetchall()

    hit = len(rows)
    miss_db = len(pool_pubs) - hit

    # 分組: 有 family_id 按 family; 無則 pubno 自成組 (key=SINGLE:<pubno>)
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        fid = r["family_id"]
        key = f"FAM:{fid}" if fid else f"SINGLE:{r['pubno']}"
        groups[key].append(r)

    # 每組選代表案
    reps = []
    multi_member_fams = 0
    for key, members in groups.items():
        # 排序: 主分降序 -> pub_date 升序 (最早) -> pubno 字典序
        members_sorted = sorted(members, key=lambda r: (
            -score(r)[0],
            r["publication_date"] or "99999999",
            r["pubno"],
        ))
        rep = members_sorted[0]
        is_fam = key.startswith("FAM:")
        if is_fam and len(members) > 1:
            multi_member_fams += 1
        reps.append({
            "rep_pubno": rep["pubno"],
            "family_id": rep["family_id"] or None,
            "group_key": key,
            "group_size": len(members),
            "country": rep["country"],
            "rep_score": score(rep)[0],
            "member_pubnos": [m["pubno"] for m in members_sorted],
            "collapsed": len(members) - 1,  # 被此代表案吸收的同族數
        })

    reps.sort(key=lambda x: (-x["group_size"], x["group_key"]))
    collapsed_total = sum(r["collapsed"] for r in reps)

    summary = {
        "pool_uniq_pubno": len(pool_pubs),
        "hit_db": hit,
        "miss_db": miss_db,
        "total_groups": len(groups),
        "family_groups": sum(1 for k in groups if k.startswith("FAM:")),
        "single_groups": sum(1 for k in groups if k.startswith("SINGLE:")),
        "multi_member_family_groups": multi_member_fams,
        "collapsed_by_family_dedup": collapsed_total,
        "b_layer_representatives": len(reps),
    }
    out = {"summary": summary, "representatives": reps}
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n輸出 -> {OUT}")


if __name__ == "__main__":
    main()
