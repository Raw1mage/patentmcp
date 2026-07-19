"""BR_20260719 缺陷B live diagnostic: hits>0 but result-list did not render.

Reproduce the exact failing path (TW200644333 @PN → search-ready shell with
per-DB counts 本國公告=2 but no result list) and dump every intermediate HTML
so we can reverse-engineer the 'search-ready shell → result-list' navigation.

Scratch dumps go to XDG runtime dir (0700), NEVER /tmp.

Run: .venv/bin/python scripts/diag_br20260719b_render.py [NUMBER] [AXIS]
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patent_mcp_server.gpss4.session import BASE
from patent_mcp_server.gpss4.session_manager import shared_session
from patent_mcp_server.gpss4 import adv_search as A

DUMP = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", os.path.expanduser("~/.cache")),
    "br20260719b",
)
os.makedirs(DUMP, mode=0o700, exist_ok=True)


def _save(name, text):
    p = os.path.join(DUMP, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text or "")
    print(f"  dumped {name}  (len={len(text or '')})  -> {p}")


async def main():
    number = sys.argv[1] if len(sys.argv) > 1 else "200644333"
    axis = sys.argv[2] if len(sys.argv) > 2 else "pub"  # BR sample was @PN
    number = number[2:] if number.upper().startswith("TW") else number
    suffix = {"apply": "@AN", "pub": "@PN"}[axis]
    query = f"({number}){suffix}"
    print(f"[diag] query={query!r} axis={axis} dump={DUMP}")

    async with shared_session("diag_br20260719b") as s:
        await A._ensure_query_ready(s, "TW")
        # replicate _submit_query up to the shell, but capture everything
        member = s._refresh_chain[-1][1] if s._refresh_chain else ""
        adv_tab_url = getattr(s, "_adv_tab_next", None) or A._extract_adv_tab_url(member)
        print(f"[diag] adv_tab_url={adv_tab_url}")

        # adv-form GET
        form_html = ""
        for _ in range(A._ADV_FORM_RETRIES):
            resp = await s.get(adv_tab_url)
            form_html = resp.text
            if "_3_10_X" in form_html:
                break
            if A._is_transient(form_html):
                await asyncio.sleep(A._ADV_FORM_BACKOFF)
                continue
            break
        _save("01_adv_form.html", form_html)
        fm = A._ADV_FORM_ACTION_RE.search(form_html)
        im = A._INFO_RE.search(form_html)
        action = BASE + fm.group(1)
        info = im.group(1) if im else ""
        data = {
            "INFO": info, "@_3_10_X": "T_XX", "_3_10_X": query,
            "_IMG_\u6aa2\u7d22.x": "20", "_IMG_\u6aa2\u7d22.y": "10",
        }
        pr = await A._post_retry(s, action, data, str(resp.url), "INFO")
        result_html = pr.text
        result_url = str(pr.url)
        _save("02_post_resp.html", result_html)
        print(f"[diag] post_resp url={result_url}")
        print(f"[diag] result markers present? "
              f"{[k for k in A._RESULT_MARKERS if k in result_html]}")
        print(f"[diag] NeedCheck? {bool(A._NEEDCHECK_RE.search(result_html))}  "
              f"chkURL? {bool(A._CHKURL_RE.search(result_html))}  "
              f"AURL(job)? {bool(A._JOB_URL_RE.search(result_html))}  "
              f"ptmp? {bool(A._PTMP_RE.search(result_html))}")

        # if no result markers -> the search-ready shell path (the failing case)
        if not any(k in result_html for k in A._RESULT_MARKERS):
            cm = A._CHKURL_RE.search(result_html)
            pm = A._PTMP_RE.search(result_html)
            if cm and pm:
                kmtmp = pm.group(1).split("/")[0]
                watch = f"{BASE}{cm.group(1)}{kmtmp}{cm.group(2)}1:\u5168\u90e8:"
                print(f"[diag] chkURL watch = {watch}")
                counts = None
                watch_html = ""
                for i in range(40):
                    r = await s.client.get(watch, headers={"Referer": result_url})
                    watch_html = r.text
                    if "DB_OK" in watch_html:
                        counts = {
                            name.strip(): int(n.replace(",", ""))
                            for name, n in A._WATCH_COUNT_RE.findall(watch_html)
                        }
                        break
                    await asyncio.sleep(1.5)
                _save("03_watch_db_ok.html", watch_html)
                print(f"[diag] per-DB counts = {counts}")

                # KEY RECON: after DB_OK, how does the REAL UI navigate to the
                # result list? Candidates to probe:
                #   (a) re-GET the result_url (referer) — like _poll_job does
                #   (b) the shell carries a result-list anchor/form to follow
                # Probe (a):
                rr = await s.client.get(result_url, headers={"Referer": result_url})
                _save("04_reget_referer.html", rr.text)
                print(f"[diag] (a) re-GET referer markers? "
                      f"{[k for k in A._RESULT_MARKERS if k in rr.text]} "
                      f"len={len(rr.text)}")

                # Probe (b): scan the shell for any follow-up URLs / forms
                anchors = re.findall(r'(?:href|action)=["\']?(/gpss4/[^\s"\'>]+)',
                                     result_html)
                uniq = sorted(set(anchors))
                print(f"[diag] (b) shell carries {len(uniq)} gpss4 URLs:")
                for u in uniq[:40]:
                    print(f"        {u}")
                # dump JS-side clues (setTimeout/location/submit targets)
                js_hints = re.findall(
                    r'(location\.href\s*=\s*[^;]+|\.submit\(\)|setTimeout\([^)]+\)'
                    r'|AURL\s*=\s*[^;]+|chkURL\s*=\s*[^;]+|goURL\s*=\s*[^;]+'
                    r'|resURL\s*=\s*[^;]+|RURL\s*=\s*[^;]+)',
                    result_html)
                print(f"[diag] (b) {len(js_hints)} JS navigation hints:")
                for h in js_hints[:30]:
                    print(f"        {h.strip()[:120]}")
            else:
                print("[diag] shell has no chkURL/ptmp — different shape")
        else:
            print("[diag] result markers ALREADY present — no shell path hit")

    print(f"\n[diag] all dumps in {DUMP}")


if __name__ == "__main__":
    asyncio.run(main())
