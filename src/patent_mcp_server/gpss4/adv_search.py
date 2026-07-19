"""
GPSS4 advanced-search scraper (進階檢索) — quota-free result harvesting.

Reverse-engineered & verified 2026-07-11 (design.md DD-7..DD-11). The official
GPSS API caps daily downloads; the logged-in web 進階檢索 runs on an interactive
session (no API-quota counter), so we drive IT instead to harvest large result
lists — crucially INCLUDING patent-family grouping, which the closed project-
folder export lacked.

PURE HTTPX, NO BROWSER (DD-8, superseded 2026-07-11 — de-browsered): every
GPSS4 page URL carries a SHORT-LIVED slot key (e.g. `gpsskm?.<hex>`). The old
assumption was that only a real browser could propagate it and httpx
hand-assembly always failed — TRUE for hand-assembly, but a PoC proved httpx
can EXTRACT each slot key from the current page's HTML and carry it to the next
request, exactly as the browser did. So the whole flow is a plain HTTP state
machine over GPSS4Session's httpx client; playwright + chromium are gone.

The SSO landing URL is ONE-TIME (GPSS4Session.login already consumed it) — the
進階檢索 TAB ANCHOR is read from member.html on the session's _refresh_chain
(NOT the right-side 進階檢索設定 block, which lands on the `_20_*` environment
page with no `_3_10_X`).

Flow (all httpx GET/POST on GPSS4Session.client):
  1. GPSS4Session.login()  -> authed httpx jar + member.html (_refresh_chain).
  2. Extract the 進階檢索 tab anchor `<a href=... class="link">進階檢索`.
  3. GET that tab URL -> the adv form (textarea _3_10_X + form action + INFO).
  4. POST _3_10_X=<query> + INFO + _IMG_檢索.x/.y (image submit).
  5. Response is EITHER the result list directly (<50 rows) OR a ttsserv_watch
     job shell -> poll `ttsserv_watch?<kmtmp>/km.swp:4:1:全部:` until DB_OK.
  6. VIEW SWITCH (BR_20260716 簡詳目並列, live-verified 2026-07-17): the result
     list's DEFAULT 條列式 view renders NO patent numbers at all — only seq
     checkboxes. The numbers (公開公告號/申請號/dates/title) render ONLY in the
     簡詳目並列 view: POST the result form with _IMG_簡詳目並列.x/.y + INFO +
     @_0_15_T=T_XX + @_0_48_A=A_ + JPAGE= + every @R<hex>_db_rec_n hidden rec
     input. (表格式 500s under httpx; 簡詳目並列 is the reliable one.) Then bump
     page size to 50 via the 每頁 <select> slot-option GET.
     NB the raw HTML uses UNQUOTED attributes (name=INFO value=...) and leaves
     <tr>/<td> UNCLOSED, so rows are sliced on OPEN tags, not close pairs.
  7. Family: POST BUTTON=家族收合 (plain submit, not ajax) -> collapsed list
     whose 序號 column is `N.M` (family N member M) = the per-patent family key
     (DD-10 correction: clickselect group is a selection ordinal, NOT a family
     key).
  8. Pagination: 簡詳目並列 = POST _IMG_次頁.x/.y (same form-data shape as the
     view switch, re-read from EACH page); 家族收合 legacy = JPAGE jump form
     (POST BUTTON=顯示結果 + JPAGE=<n>). Slot keys short-lived, never reused.

GPSS advanced-search query syntax (official field-code table, DD-9):
  title `(詞)@TI`, abstract `(詞)@AB`, claims `(詞)@CL`, classification
  `CS=G06F-0003/00`, date `AD=2006:2007`. NOT `TI=(詞)` (returns 0).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from patent_mcp_server.gpss4.session import GPSS4Session, BASE
from patent_mcp_server.gpss4.patno import PAT_NO_RE, KINDED_RE, APPLYNO_RE

logger = logging.getLogger(__name__)

# --- member.html: the 進階檢索 tab anchor (slot-key URL) ----------------------
# tab-list anchor form:  <a href=/gpss4/gpsskmc/gpsskm?.<hex> class="link">進階檢索
_ADV_TAB_RE = re.compile(
    r'<a\s+href=["\']?(/gpss4/gpsskmc/gpsskm\?\.[0-9A-Fa-f][^\s"\'>]+)["\']?'
    r'[^>]*class=["\']?link["\']?[^>]*>\s*進階檢索',
    re.I,
)
# --- result page: total count / current page ---------------------------------
# 共 <font/span class="numfmt">N</font> 筆，第 X/Y
_TOTAL_RE = re.compile(r'共.*?numfmt[^>]*>\s*(\d[\d,]*)\s*<.*?筆', re.S)
_PAGE_RE = re.compile(
    r'第.*?numfmt[^>]*>\s*(\d+)\s*<.*?/.*?numfmt[^>]*>\s*(\d+)\s*<', re.S
)
# 專利家族數量 <font class="numfmt">M</font>
_FAMILY_COUNT_RE = re.compile(r'專利家族數量.*?numfmt[^>]*>\s*(\d+)\s*<', re.S)
# per-row selection: clickselect(this,db,rec,group) — group is a row ordinal
_CLICKSELECT_RE = re.compile(r'clickselect\(this,\s*(\d+),\s*(\d+),\s*(\d+)\)')
# patent-number-looking token. Country segment handles TW grant 3-letter
# prefixes (TW[IMD]) as well as generic 2-letter codes — see gpss4/patno.py
# (BR_20260718: shared so the country-segment assumption lives in one place).
_PAT_NO_RE = PAT_NO_RE


class GPSS4AdvSearchError(RuntimeError):
    pass


class GPSS4AdvZeroHits(Exception):
    """BR_20260718: the engine reported the search READY with 0 hits in every
    scoped database. A zero-hit search never renders a result list at all —
    the query POST returns the search-form watcher shell (chkURL contract,
    len≈30k, 前次檢索還沒好), which the old flow mis-read as a 簡詳目並列
    view-switch failure. Carried as an exception only to unwind the harvest
    flow; harvest() converts it into a structured empty pool."""

    def __init__(self, counts: Dict[str, int], html: str = ""):
        super().__init__(f"zero hits (per-DB counts={counts})")
        self.counts = counts
        # BR_20260719 slot-expiry RCA: carry the shell HTML so a batch caller can
        # harvest the next-query slot anchor from it (a not_found item must not
        # break the anchor chain — the anchor just used is now spent).
        self.html = html


class GPSS4AdvRenderPending(GPSS4AdvSearchError):
    """BR_20260719 缺陷B: the engine reported the search READY with hits>0 in a
    scoped DB, but the response is the search-FORM watcher shell (chkURL contract,
    '前次檢索還沒好' async race) and NOT the result-page — so the result LIST never
    rendered and no patent number can be extracted yet.

    This is a RECOVERABLE condition, distinct from a hard adv error: the query DID
    match; the DOM race just left the list un-rendered on this hop. A batch caller
    (gpss4_resolve_appnos) should mark the item render_pending and CONTINUE the
    batch WITHOUT counting it toward CONSECUTIVE_ERRORS (BR §缺陷B: 把「搜到卻抽不
    到號」從 error 降為可回收，避免污染整批). Carries per-DB counts + shell HTML so
    the caller keeps the slot-anchor chain alive.

    NOTE (code-thinker honesty): the full shell→result-list re-navigation (making
    a render_pending item actually resolve its number in-batch) requires a
    reliably reproducible hits>0-no-render window, which the current data state
    does not provide. Until then this exception DOWNGRADES the failure to
    recoverable rather than silently masking it — never a fabricated number."""

    def __init__(self, counts: Dict[str, int], html: str = ""):
        total = counts.get("全部", sum(counts.values()))
        super().__init__(
            f"search matched {total} hit(s) but the result list did not render "
            f"(search-form watcher shell; engine async race; per-DB counts={counts}) "
            "— recoverable, re-queue this item"
        )
        self.counts = counts
        self.html = html


@dataclass
class AdvPatent:
    """One row in the 進階檢索 簡目 result list."""

    seq: Optional[str] = None
    apply_date: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    pat_no: Optional[str] = None
    # application number (申請號), e.g. US13938205 — a country+digits token WITHOUT
    # a kind-code suffix. Distinct from pat_no (公開/公告號) which carries a kind
    # code (B2/A1/...). Populated only when the GPSS result table is configured to
    # return the 申請號 column; None otherwise (schema-adaptive, DD-number-parser).
    apply_no: Optional[str] = None
    # DD-14: kept ONLY as a raw parse artifact for the running-seq classifier
    # below (the `N.M` family-sequence cell disambiguates seq vs date); it is
    # NEVER surfaced in to_dict() / CSV / the MCP response. NO family dedup.
    family_group: Optional[str] = None
    raw_cells: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "seq": self.seq,
            "apply_date": self.apply_date,
            "title": self.title,
            "abstract": self.abstract,
            "pat_no": self.pat_no,
            "apply_no": self.apply_no,
        }


@dataclass
class AdvResultPage:
    """Parsed 簡目 result page (one page of the paginated list)."""

    html: str
    total: int
    page: int
    total_pages: int
    family_count: Optional[int]
    patents: List[AdvPatent]
    # slot-key URLs for other pages, extracted from the 頁碼 select on THIS page
    page_urls: List[str] = field(default_factory=list)

    @classmethod
    def parse(cls, html: str) -> "AdvResultPage":
        tm = _TOTAL_RE.search(html)
        pm = _PAGE_RE.search(html)
        fm = _FAMILY_COUNT_RE.search(html)
        total = int(tm.group(1).replace(",", "")) if tm else 0
        page = int(pm.group(1)) if pm else 1
        total_pages = int(pm.group(2)) if pm else 1
        family_count = int(fm.group(1)) if fm else None
        # BR_20260716: 簡詳目並列 (dual) view pages carry labelled field rows
        # (公開公告號/申請號/…) — the ONLY view where numbers render at all.
        if _DUAL_MARKER in html:
            patents = cls._extract_dual_rows(html)
        else:
            patents = cls._extract_rows(html)
        page_urls = cls._extract_page_urls(html)
        return cls(
            html=html,
            total=total,
            page=page,
            total_pages=total_pages,
            family_count=family_count,
            patents=patents,
            page_urls=page_urls,
        )

    @staticmethod
    def _extract_dual_rows(html: str) -> List[AdvPatent]:
        """Extract rows from the 簡詳目並列 (dual) view (BR_20260716, 2026-07-17).

        Each record is a `<table class=sumtab>` block: a clickselect checkbox +
        running-seq link, then labelled field rows
        `<td class=sumth1>LABEL</td><td class=sumtdNNNN_603>VALUE`.
        Labels observed live: 公開公告號 / 公開公告日 / 申請號 / 申請日 /
        申請人 / 專利名稱 (set follows the account's 顯示欄位 config — we map
        by LABEL, never position). Raw HTML leaves <tr>/<td> unclosed, so the
        value slice ends at the next <tr / next label / </table.
        """
        chunks = re.split(r'(?=<table class="?sumtab"?)', html)
        patents: List[AdvPatent] = []
        for ch in chunks:
            if "clickselect(this" not in ch:
                continue
            p = AdvPatent()
            qm = re.search(r'class="?link602"?[^>]*>\s*(\d+)\s*<', ch)
            if qm:
                p.seq = qm.group(1)
                p.family_group = p.seq  # pubno granularity: singleton
            fields: Dict[str, str] = {}
            for fm_ in re.finditer(
                r'<td class="?sumth1"?[^>]*>\s*([^<]+?)\s*</td>\s*'
                r'<td[^>]*>(.*?)(?=<tr[\s>]|<td class="?sumth1|</table)',
                ch, re.S,
            ):
                label = fm_.group(1).strip()
                val = re.sub(r'\s+', ' ',
                             re.sub(r'<[^>]+>', ' ', fm_.group(2))).strip()
                if label and val:
                    fields[label] = val
            p.raw_cells = [f"{k}: {v}" for k, v in fields.items()]
            pub = fields.get("公開公告號", "")
            m = re.search(r'[A-Z]{2}[0-9][0-9A-Z]{5,}', pub)
            if m:
                p.pat_no = m.group(0)
            ap = fields.get("申請號", "")
            if ap:
                # BR_20260719 (live-dump RCA 2026-07-19): the 申請號 value renders as
                # "TW 109112770" — country code and digits separated by whitespace.
                # The old ap.split()[0] captured only "TW", dropping the digits
                # (broke the @AN resolve_one match). Extract the full CC+digits
                # token (tolerating the interior space / dotted CN form), then
                # normalise out spaces so downstream digit-compare works.
                am = re.search(r'[A-Z]{2}\s*[0-9][0-9A-Z.\-]*', ap)
                p.apply_no = re.sub(r'\s+', '', am.group(0)) if am else ap.split()[0]
            p.apply_date = fields.get("申請日") or None
            p.title = fields.get("專利名稱") or None
            p.abstract = fields.get("摘要") or None
            patents.append(p)
        return patents

    @staticmethod
    def _extract_rows(html: str) -> List[AdvPatent]:
        """Extract patent rows from the 簡目 / 家族收合 result table.

        Pre-collapse (簡目) columns: 序號 / 主要圖式 / 申請日 / 專利名稱 / 摘要.
        Post-collapse (家族收合) adds a family-sequence cell `N.M` (family N,
        member M) on grouped rows — THIS is the per-patent family binding key
        (DD-10 correction: NOT the clickselect group ordinal). Rows with a bare
        integer seq and no `N.M` are singleton families.

        Cleaning: some rows leak inline `<script>function instback(...)` into the
        first cell; we strip <script> blocks before cell extraction and reject
        JS-looking cell text so it never masquerades as a title/seq.
        """
        # Split on the <tr OPEN tag, not <tr>...</tr> pairs: GPSS's raw HTML
        # (as httpx sees it, un-normalised by any browser DOM) leaves <tr>/<td>
        # unclosed (35 <tr> opens vs 16 </tr> closes observed), so greedy
        # </tr> pairing swallows the whole table into one block. Slicing on the
        # open tag is robust to missing close tags.
        row_chunks = re.split(r'(?=<tr[\s>])', html)
        patents: List[AdvPatent] = []
        for tr in row_chunks:
            if "clickselect(this" not in tr:
                continue
            # a real data row carries exactly one clickselect; if this chunk has
            # more, the split under-segmented — keep only up to the next <tr.
            tr_clean = re.sub(r'<script[^>]*>.*?</script>', ' ', tr, flags=re.S)
            # <td slicing (same open-tag robustness)
            td_chunks = re.split(r'(?=<td[\s>])', tr_clean)[1:]
            cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', c)).strip()
                     for c in td_chunks]
            # reject empty + JS-leak cells (defensive: script strip may miss inline)
            cells = [c for c in cells
                     if c and not re.match(r'^\s*(function|var |window\.|if\s*\()', c)]
            p = AdvPatent(raw_cells=cells)
            # family-sequence `N.M` (family N member M) -> family_group = N
            fam = next((c for c in cells if re.fullmatch(r'\d+\.\d+', c or "")), None)
            if fam:
                p.family_group = fam.split(".")[0]
            # plain running seq: first bare-integer cell
            seqc = next((c for c in cells if re.fullmatch(r'\d+', c or "")), None)
            if seqc:
                p.seq = seqc
                # singleton family: its group id is its own running seq
                if p.family_group is None:
                    p.family_group = seqc
            dm = [c for c in cells if re.fullmatch(r'\d{4}[/-]\d{2}[/-]\d{2}', c or "")]
            if dm:
                p.apply_date = dm[0]
            # --- number classification (schema-adaptive, header-independent) ---
            # GPSS result table now carries BOTH 公開公告號 (pat_no) and 申請號
            # (apply_no) as separate columns. We classify by TOKEN SHAPE, not by
            # column position, so the parser survives any column re-ordering the
            # user configures in the GPSS result-table settings:
            #   * pat_no   (公開公告號): country + digits + KIND-CODE suffix,
            #     e.g. US09179220B2 / US20250020774A1 / CN121637048A.
            #   * apply_no (申請號): a number token that is NOT a kind-coded pat_no.
            #     - US application no: country + 8+ digits, no kind code
            #       (US18351816); often appears WITHOUT a country prefix too.
            #     - CN/TW application no: dotted form CN202411232691.8 /
            #       digits with a check-digit dot.
            # pat_no: a country-prefixed token that ENDS in a kind code
            # (letter[+optional digit]) at token end.
            _KINDED = KINDED_RE  # shared TW[IMD]-aware country segment (BR_20260718)
            # apply_no candidates: country+digits w/o kind code, OR dotted CN/TW
            # application numbers, OR a bare all-digit case number (>=7 digits).
            _APPLYNO = APPLYNO_RE
            pat_candidates = [c for c in cells if _KINDED.fullmatch(c or "")]
            if pat_candidates:
                p.pat_no = pat_candidates[0]
            else:
                nm = _PAT_NO_RE.search(tr_clean)
                if nm:
                    p.pat_no = nm.group(1)
            # apply_no: first number-shaped cell that is NOT the chosen pat_no and
            # is NOT the running seq / family-seq / date.
            for c in cells:
                if not c or c == p.pat_no or c == p.seq or c == p.apply_date:
                    continue
                if re.fullmatch(r'\d+', c) or re.fullmatch(r'\d+\.\d+', c):
                    continue  # bare running-seq / family-seq ordinals
                if _APPLYNO.fullmatch(c) and not _KINDED.fullmatch(c):
                    p.apply_no = c
                    break
            # title / abstract: natural-language text cells only — EXCLUDE any
            # number-shaped token (pat_no / apply_no / seq / date) so a patent-
            # or application-number column can never masquerade as the title.
            def _is_number_token(c: str) -> bool:
                return bool(
                    re.fullmatch(r'[\d/\-.]+', c)
                    or _KINDED.fullmatch(c)
                    or _APPLYNO.fullmatch(c)
                    or c == p.pat_no
                    or c == p.apply_no
                )
            text_cells = [c for c in cells
                          if len(c) > 4 and not _is_number_token(c)]
            if text_cells:
                p.title = text_cells[0]
            if len(text_cells) > 1:
                p.abstract = text_cells[-1]
            patents.append(p)
        return patents

    @staticmethod
    def _extract_page_urls(html: str) -> List[str]:
        """Extract per-page slot-key URLs from the 頁碼 <select> options.

        DD-11: each page is a pre-computed short-lived slot URL; they MUST be read
        from the current page's select, never pre-assembled.
        """
        urls: List[str] = []
        # page dropdown options: <option value="/gpss4/gpsskmc/gpsskm?.<hex>">
        for m in re.finditer(
            r'<option[^>]*value=["\']?(/gpss4/gpsskmc/gpsskm\?\.[0-9A-Fa-f][^"\'>\s]+)',
            html,
        ):
            urls.append(m.group(1))
        return urls


def _extract_adv_tab_url(member_html: str) -> str:
    """Find the 進階檢索 tab anchor (slot-key URL) in member.html.

    Raises if not found — do NOT fall back to the 進階檢索設定 block (lands on the
    _20_* environment page with no _3_10_X textarea).
    """
    m = _ADV_TAB_RE.search(member_html)
    if not m:
        raise GPSS4AdvSearchError(
            "進階檢索 tab anchor not found in member.html "
            "(login may have failed or member nav changed)"
        )
    href = m.group(1)
    return href if href.startswith("http") else BASE + href


# --- 進階檢索設定 (_20_* env page): per-user database-scope config -------------
# BR_20260716 task-1 live reverse-eng (2026-07-16): the search database scope is
# an ACCOUNT-LEVEL per-user server-side config, NOT a query param. The settings
# page (reached via the 喜好設定 slot-key anchor, lands on _20_*) carries 119
# checkboxes; the database-family group is `_20_1_S_<country><kind>` (value-less,
# presence = checked). Saving offers two submits: 本次套用(session) and
# 儲存個人化設定,永久有效(account-persistent). DD-7: we use the PERSISTENT save.
#
# database code -> settings-page checkbox field name. The public `databases`
# vocabulary mirrors the REST patDB codes (CNA/CNB/USA/…); map them to the web
# settings-page `_20_1_S_*` field names.
_DB_CODE_TO_FIELD = {
    "TWA": "_20_1_S_TA", "TWB": "_20_1_S_TB", "TWD": "_20_1_S_TD",
    "JPA": "_20_1_S_JA", "JPB": "_20_1_S_JB", "JPD": "_20_1_S_JD",
    "CNA": "_20_1_S_CA", "CNB": "_20_1_S_CB", "CND": "_20_1_S_CD",
    "KRA": "_20_1_S_KA", "KRB": "_20_1_S_KB", "KRD": "_20_1_S_KD",
    "USA": "_20_1_S_UA", "USB": "_20_1_S_UB", "USD": "_20_1_S_UD",
    "SEA": "_20_1_S_SA", "SEB": "_20_1_S_SB",
    "WO": "_20_1_S_WA", "WOA": "_20_1_S_WA",
    "EPA": "_20_1_S_EA", "EPB": "_20_1_S_EB", "EPD": "_20_1_S_ED",
    "OA": "_20_1_S_OA", "OB": "_20_1_S_OB",
}

# BR_20260719 §4.1B (live-dump RCA 2026-07-19): the settings page ALSO gates which
# OUTPUT COLUMNS the result view renders. The result table shows a patent number
# ONLY when the matching output-field checkbox is ticked. The page carries two
# output-field regions — 簡目 `_20_20_S_*` and 詳目 `_20_23_S_*` — and the
# 簡詳目並列 (dual) view draws from both. `set_search_databases` force-ensures the
# number / title / date columns are ticked so a fresh or reset account still
# renders 公開公告號 (the user's explicit 2026-07-19 requirement: 「輸出格式也要
# 選對」). Field-name suffixes are GPSS's own codes:
#   簡目: P1=公開公告號 AN=申請號 IDc=公開公告日 ADc=申請日 TI=專利名稱
#   詳目: PN=公開公告號 AN=申請號 TI=專利名稱
# Only fields the settings page actually offers are asserted (see the `if f in html`
# guard in set_search_databases) — so a page without a given box is never forced.
_REQUIRED_OUTPUT_FIELDS = (
    "_20_20_S_P1", "_20_20_S_AN", "_20_20_S_IDc", "_20_20_S_ADc", "_20_20_S_TI",
    "_20_23_S_PN", "_20_23_S_AN", "_20_23_S_TI",
)
# 喜好設定 / 環境設定 anchor: slot-key URL whose link text carries 設定/環境.
_SETTINGS_ANCHOR_RE = re.compile(
    r'<a\s+href=["\']?(/gpss4/gpsskmc/gpsskm\?\.[0-9A-Fa-f][^\s"\'>]+)["\']?'
    r'[^>]*>\s*(?:\u559c\u597d\u8a2d\u5b9a|\u74b0\u5883\u8a2d\u5b9a|\u6aa2\u7d22\u53ca\u986f\u793a\u8a2d\u5b9a)',
    re.I,
)
# database-family checkbox on the settings page: <input type=checkbox name=_20_1_S_XX [checked]>
_DBSCOPE_CHECKBOX_RE = re.compile(
    r'<input[^>]*type=["\']?checkbox["\']?[^>]*name=["\']?(_20_1_S_[A-Z]{2})["\']?([^>]*)>',
    re.I,
)
# settings-page form action + the persistent-save image submit.
_SETTINGS_FORM_ACTION_RE = re.compile(
    r'<form[^>]*action=["\']?(/gpss4/gpsskmc/gpsskm\?[^"\'\s>]+)', re.I)
_PERSIST_SAVE_SUBMIT = "_IMG_\u5132\u5b58\u500b\u4eba\u5316\u8a2d\u5b9a\uff0c\u6c38\u4e45\u6709\u6548"
_SESSION_SAVE_SUBMIT = "_IMG_\u672c\u6b21\u5957\u7528\uff0c\u9650\u672c\u6b21\u767b\u5165\u6709\u6548"


class GPSS4DbScopeError(RuntimeError):
    """Setting the per-user search database scope failed — DD-4 fail-fast,
    NEVER silently continue with the account's current (wrong) scope."""


def _extract_settings_url(html: str) -> Optional[str]:
    m = _SETTINGS_ANCHOR_RE.search(html)
    if not m:
        return None
    href = m.group(1)
    return href if href.startswith("http") else BASE + href


async def set_search_databases(
    s: "GPSS4Session", dbs: List[str], persist: bool = True,
    dump_dir: Optional[str] = None,
) -> Dict[str, object]:
    """Set the account's GPSS4 search database scope to exactly `dbs` (DD-3/DD-6/DD-7).

    The scope is an account-level per-user server-side config, NOT a query param
    (BR_20260716). This GETs the 進階檢索設定 (_20_*) page, rewrites the
    `_20_1_S_*` database-family checkboxes to match `dbs`, and POSTs the save.

    dbs:     REST-style db codes (CNA/CNB/USA/…); mapped to `_20_1_S_*` fields
             via _DB_CODE_TO_FIELD. Unknown codes -> GPSS4DbScopeError.
    persist: DD-7 DEFAULT True -> 儲存個人化設定,永久有效 (account-persistent,
             survives across sessions). False -> 本次套用 (session-scoped only).

    Fail-fast (DD-4): any missing page / unknown code / save-not-confirmed
    raises GPSS4DbScopeError; NEVER silently keeps the current scope.
    Runs on the ALREADY-authed session `s`; does not re-login on its own.
    """
    if not dbs:
        raise GPSS4DbScopeError("databases must be a non-empty list")
    fields = []
    unknown = []
    for code in dbs:
        f = _DB_CODE_TO_FIELD.get(code.upper())
        (fields.append(f) if f else unknown.append(code))
    if unknown:
        raise GPSS4DbScopeError(
            f"unknown database code(s): {unknown}; "
            f"valid: {sorted(_DB_CODE_TO_FIELD)}"
        )
    want = set(fields)

    # 1) find the settings page from member.html (on the authed _refresh_chain)
    member = s._refresh_chain[-1][1] if s._refresh_chain else ""
    settings_url = _extract_settings_url(member)
    if not settings_url:
        raise GPSS4DbScopeError(
            "進階檢索設定 (_20_*) anchor not found in member.html "
            "(login failed or member nav changed)"
        )
    resp = await s.get(settings_url)
    html = resp.text
    _dump(dump_dir, "dbscope_settings.html", html)
    if not _DBSCOPE_CHECKBOX_RE.search(html):
        raise GPSS4DbScopeError(
            f"settings page has no _20_1_S_* database checkboxes "
            f"(len={len(html)}); wrong page or session not authed?"
        )
    fm = _SETTINGS_FORM_ACTION_RE.search(html)
    im = _INFO_RE.search(html)
    if not fm:
        raise GPSS4DbScopeError("settings-page form action not found")
    action = BASE + fm.group(1)
    info = im.group(1) if im else ""

    # 2) build the POST body as a READ-MODIFY-WRITE of the WHOLE form (BR_20260719
    #    §4.1B, 2026-07-19 live-dump RCA). The settings page is ONE form and the
    #    persist-save button saves the ENTIRE page: any checkbox NOT echoed back is
    #    saved as UNCHECKED. The old body echoed only `_20_1_S_*` (the DB group) +
    #    hidden fields, silently dropping every OUTPUT-FIELD checkbox
    #    (`_20_23_S_*` 詳目 / `_20_20_S_*` 簡目: PN/AN/TI/日期…) and the display
    #    radios — which is exactly the 「命中卻抽不到號碼」 BR root cause (the
    #    output columns the result view renders are gated by these very boxes).
    #    So: (a) preserve EVERY hidden field, (b) preserve EVERY currently-checked
    #    checkbox and EVERY selected radio, (c) override the DB group to EXACTLY
    #    `want`, (d) force-ensure the number/title/date OUTPUT fields are checked
    #    so a fresh/resét account still renders 公開公告號 (never assume the account
    #    happens to have them on — the BR warns against exactly that assumption).
    data: Dict[str, str] = {"INFO": info}
    # (a) all hidden fields (incl. the @_20_* group markers + ID/SECU/INFO/TPHC)
    for hm in re.finditer(
        r'<input[^>]*type=["\']?hidden["\']?[^>]*name=["\']?([^"\'\s>]+)["\']?'
        r'[^>]*value=["\']?([^"\'\s>]*)', html, re.I):
        data[hm.group(1)] = hm.group(2)
    # (b) every currently-checked checkbox EXCEPT the DB group (rebuilt in (c)).
    #     value-less checkbox -> POSTs `name=on`.
    for cm in re.finditer(
        r'<input[^>]*type=["\']?checkbox["\']?[^>]*name=["\']?([^"\'\s>]+)["\']?([^>]*)>',
        html, re.I):
        name, rest = cm.group(1), cm.group(2)
        if name.startswith("_20_1_S_"):
            continue  # DB group handled in (c)
        if "checked" in (rest or "").lower():
            data[name] = "on"
    #     every selected radio (name=value) — display format / number-axis etc.
    for rm in re.finditer(
        r'<input[^>]*type=["\']?radio["\']?[^>]*name=["\']?([^"\'\s>]+)["\']?'
        r'[^>]*value=["\']?([^"\'\s>]*)["\']?([^>]*)>', html, re.I):
        name, val, rest = rm.group(1), rm.group(2), rm.group(3)
        if "checked" in (rest or "").lower():
            data[name] = val
    # (c) DB group = EXACTLY want
    for f in want:
        data[f] = "on"
    # (d) force-ensure output fields render the numbers we parse (idempotent —
    #     already-checked ones were preserved in (b); this adds any missing).
    for f in _REQUIRED_OUTPUT_FIELDS:
        if f in html:  # only assert fields this page actually offers
            data[f] = "on"
    submit = _PERSIST_SAVE_SUBMIT if persist else _SESSION_SAVE_SUBMIT
    data[f"{submit}.x"] = "10"
    data[f"{submit}.y"] = "10"

    pr = await s.client.post(action, data=data,
                             headers={"Referer": str(resp.url)})
    saved_html = pr.text
    _dump(dump_dir, "dbscope_saved.html", saved_html)

    # 3) verify the save took: re-read the settings page and assert the checked
    #    set now EQUALS `want` (fail-fast, DD-4 — no silent wrong-scope continue).
    verify = await s.get(settings_url)
    checked = {
        m.group(1) for m in _DBSCOPE_CHECKBOX_RE.finditer(verify.text)
        if "checked" in (m.group(2) or "").lower()
    }
    _dump(dump_dir, "dbscope_verify.html", verify.text)
    if checked != want:
        raise GPSS4DbScopeError(
            f"database scope save not confirmed: wanted {sorted(want)}, "
            f"settings page now shows {sorted(checked)}"
        )
    logger.info("GPSS4 search db scope set to %s (persist=%s)",
                sorted(want), persist)
    return {"ok": True, "databases": dbs, "fields": sorted(want),
            "persist": persist}


# --- result-list markers signalling the async job has rendered ---------------
_RESULT_MARKERS = ("clickselect(this", "outsum", "專利家族數量", "numfmt")


# BR_20260719 DD-4: 國別 → 該國「公開+公告」兩庫 REST db codes。number-query 要抽到
# 公開/公告號,必須把目標國別的公開庫(A)+公告庫(B)都納入 scope(TW DD-96 先例)。
# 只列已在 _DB_CODE_TO_FIELD 有對應 checkbox 的國別;未知國別 fail-fast(不猜)。
_COUNTRY_TO_DBS = {
    "TW": ["TWA", "TWB"],
    "CN": ["CNA", "CNB"],
    "US": ["USA", "USB"],
    "JP": ["JPA", "JPB"],
    "KR": ["KRA", "KRB"],
    "EP": ["EPA", "EPB"],
}


def country_to_dbs(country: str) -> List[str]:
    """國別 → 公開+公告兩庫 REST db codes(BR_20260719 DD-4)。未知國別 raise。"""
    dbs = _COUNTRY_TO_DBS.get((country or "").upper())
    if not dbs:
        raise GPSS4DbScopeError(
            f"no DB-scope mapping for country {country!r}; "
            f"known: {sorted(_COUNTRY_TO_DBS)} (BR_20260719 DD-4)"
        )
    return dbs


async def _ensure_query_ready(
    s: "GPSS4Session", country: str, dump_dir: Optional[str] = None,
) -> List[str]:
    """Per-login-session DB scope 前置閘(BR_20260719 §4 / DD-4)。

    number-query 進入點在送查詢前無條件呼叫本 routine:確保本 login session 的搜尋
    DB scope 已含目標國別的公開+公告兩庫。**per-session 粒度**——同 session 內第二次
    起若 scope 已就緒即跳過(session._scope_set 記錄),不每查重設(重設會對 batch 多發
    設定頁 POST → 升高 TIPO 節流鎖定風險;§4A login gate 已消除並發 → session 設一次
    即確定性正確,非猜 config)。

    fail-fast(DD-6):scope 設定失敗 raise GPSS4DbScopeError,絕不用可能錯的現有
    scope 續查而回假 unmatched。

    Returns: 本次生效的 DB codes(可觀測,DD-4)。
    """
    need = country_to_dbs(country)
    already = getattr(s, "_scope_set", set())
    if set(need).issubset(already):
        logger.info("GPSS4 scope reused for session (already %s)", sorted(already))
        return need
    await set_search_databases(s, need, persist=True, dump_dir=dump_dir)
    # set_search_databases verifies the save (DD-4); record on the session so the
    # rest of this batch reuses it.
    if not hasattr(s, "_scope_set") or s._scope_set is None:
        s._scope_set = set()
    s._scope_set.update(need)
    return need


async def resolve_one(
    s: "GPSS4Session", number: str, axis: str = "apply",
    country: str = "TW", dump_dir: Optional[str] = None,
) -> Optional["AdvPatent"]:
    """單一號碼 → 專利號解析,走 adv_search 路徑(BR_20260719 §4 / DD-3)。

    folder 標記清單路徑不 render 專利號(recon 坐實);adv_search 的 簡詳目並列檢視
    (_enter_dual_view)是唯一 render 公開公告號的檢視。本 helper 復用 adv primitives
    做**單號**查詢:submit → dual-view → parse 第一筆匹配 row,不做全軸分頁(harvest
    是整軸掃,resolve_one 只要第一頁 dual-view 即可)。

    呼叫前提:session 已 login、已 _ensure_query_ready(country)。本函式不自行設 scope
    (由呼叫端 per-session 統一設,避免每號重設)。

    **slot-chaining(BR_20260719 slot-expiry RCA 2026-07-19)**:進階檢索 tab anchor
    (slot-key URL)是**單次消耗**——同 session 重用同一 anchor 查第二次即回過期 stub
    (len=289)。故首查用 login-cached member anchor,之後用上一查的結果頁 re-mint 的
    新鮮 anchor(存於 s._adv_tab_next);本查結束再從結果頁 harvest 一個新鮮 anchor 存回,
    供下一筆(batch chaining)。zero-hit / 例外路徑也會盡量 capture,避免 not_found
    佔多數時 chain 斷掉。

    axis: 'apply'(@AN 申請號)/ 'pub'(@PN 公開公告號)。
    Returns: 匹配的 AdvPatent(含 pat_no/apply_no/title),或 None(not_found/unmatched)。
    """
    suffix = {"apply": "@AN", "pub": "@PN"}.get(axis)
    if not suffix:
        raise GPSS4AdvSearchError(f"unknown axis {axis!r} (use apply|pub)")
    query = f"({number}){suffix}"
    # slot-chaining: prefer the fresh anchor harvested from the previous query;
    # fall back to the login-cached member anchor for the FIRST query only.
    adv_tab_url = getattr(s, "_adv_tab_next", None)
    if not adv_tab_url:
        member = s._refresh_chain[-1][1] if s._refresh_chain else ""
        adv_tab_url = _extract_adv_tab_url(member)

    def _harvest_next_anchor(*htmls: str) -> None:
        """Re-mint the single-use anchor for the NEXT query from any page that
        carries a fresh 進階檢索 tab anchor. Consume-then-refresh: clear first so
        a page without an anchor forces the next call back to the member anchor
        (via re-login path) rather than silently reusing a spent slot."""
        s._adv_tab_next = None
        for h in htmls:
            m = _ADV_TAB_RE.search(h or "")
            if m:
                href = m.group(1)
                s._adv_tab_next = href if href.startswith("http") else BASE + href
                return

    try:
        result_html, form_action, info = await _submit_query(
            s, adv_tab_url, query, dump_dir)
    except GPSS4AdvZeroHits as z:
        # 真 zero-hit → not_found. Harvest the next-query anchor from the zero-hit
        # shell if it carries one, so the batch chain survives a not_found item.
        _harvest_next_anchor(getattr(z, "html", ""))
        return None
    # slot-chaining: harvest the next-query anchor from the RAW post-submit result
    # page — BEFORE the collapse / dual-view slot transitions. Evidence
    # (2026-07-19 diagnostic): result-page 進階檢索 anchors chain reliably ≥3 deep
    # (GET len≈30k, _3_10_X present), whereas anchors harvested from the dual view
    # (reached via collapse + view-switch + page-size slot advances) go stale by
    # the 3rd query (len=289 "view switch failed"). Harvesting the raw result-page
    # anchor here is what makes a long batch survive past 2 items.
    # 切 簡詳目並列 view(唯一 render 專利號)。**單號查詢不做家族收合也不拉
    # pagesize=50**(BR_20260719 slot-expiry mitigation):單號查詢回單筆家族/<50 筆,
    # 這兩步對 resolve_one 無用,各多一個 slot-advancing 請求。只保留 view-switch。
    dual_html, _ = await _enter_dual_view(
        s, result_html, adv_tab_url, dump_dir, bump_page_size=False)
    # slot-chaining anchor harvest — **AFTER dual-view, from the LAST response**
    # (BR_20260719 slot-expiry RCA, 2026-07-19 instrumented live trace).
    # ROOT CAUSE: the GPSS4 slot anchor is a SESSION-LEVEL "current slot"
    # pointer — every response mints a new slot and voids the previous one. The
    # old code harvested from result_html (right after submit) and THEN did the
    # dual-view POST, which minted a new slot and INVALIDATED the just-harvested
    # anchor — so query N+1 reused a spent anchor → len=289 at depth 3. The live
    # trace proved that harvesting from dual_html (the last response of THIS
    # item, after ALL its requests) chains reliably: a 3-item all-appno batch
    # resolved 3/3 (was 2/3). So harvest LAST, not early.
    _harvest_next_anchor(dual_html, result_html)
    page = AdvResultPage.parse(dual_html)
    if not page.patents:
        return None
    # 選第一筆 apply_no / pat_no 匹配的 row(去前綴數字比對,對齊 _norm 慣例)。
    def _digits(x: Optional[str]) -> str:
        return re.sub(r"\D", "", x or "").lstrip("0")
    want = _digits(number)
    for p in page.patents:
        if axis == "apply" and p.apply_no and _digits(p.apply_no) == want:
            return p
        if axis == "pub" and p.pat_no and _digits(p.pat_no) == want:
            return p
    # 無精確匹配但有結果 → 回第一筆(單號查詢通常僅一筆家族),讓呼叫端判定。
    return page.patents[0] if page.patents else None


# --- httpx handshake contract (reverse-engineered & verified 2026-07-11) ------
# The advanced-search flow is a pure HTTP state machine — NO browser needed.
# Every short-lived slot key lives in the page HTML; httpx extracts it from each
# response and carries it to the next request. (De-browsered from playwright:
# the browser's only value was auto-carrying the slot key, which httpx does by
# re-reading it from HTML — PoC-proven, so chromium is no longer a dependency.)
#
#   query POST : <form action="gpsskm?@@<n>"> with _3_10_X=<query> + INFO +
#                _IMG_檢索.x/.y (image submit). Response is EITHER the result
#                list directly (<50 rows) OR a ttsserv_watch job shell (poll).
#   job poll   : GET ttsserv_watch?<kmtmp>/km.swp:4:1:全部:  until <!--DB_OK-->
#                (kmtmp derived from ptmp="kmwork/NNNNN").
#   家族收合 : POST the result form with BUTTON=家族收合 (a plain submit,
#                NOT ajax) -> the collapsed list carrying `N.M` family seqs.
#   pagination : 簡目 = 頁碼 <select> slot URLs (GET); 家族收合 = JPAGE
#                jump form (POST BUTTON=顯示結果 + JPAGE=<n>).
_ADV_FORM_ACTION_RE = re.compile(r'<form[^>]*action="(/gpss4/gpsskmc/gpsskm\?[^"]+)"')
# KM result-page form (raw HTML often leaves attributes UNQUOTED: action=/gpss4/...)
_KM_FORM_ACTION_RE = re.compile(r'<form[^>]*action="?(/gpss4/gpsskmc/gpsskm\?@@\d+)')
# hidden per-record inputs the view-switch/pagination POST must echo back:
#   <input type=hidden value=1 name=@R<hex>_<db>_<rec>_<n>>
_HIDREC_RE = re.compile(r'<input[^>]*name="?(@R[0-9A-Fa-f]+_\d+_\d+_\d+)"?[^>]*>')
# 每頁 page-size <select>: <option value=/gpss4/gpsskmc/gpsskm?.<hex> >50</option>
_PSIZE_OPT_RE = re.compile(
    r'<option value="?(/gpss4/gpsskmc/gpsskm\?\.[0-9A-Fa-f][^\s">]*)"?\s*>\s*(\d+)\s*</option>')
_NEXTPG_RE = re.compile(r'name="?_IMG_\u6b21\u9801')
# 簡詳目並列 record field labels: <td class=sumth1 ...>公開公告號</td><td ...>VALUE
_DUAL_MARKER = '公開公告號'
# BR_20260719 slot-expiry RCA (2026-07-19 instrumented trace): after a large
# result item, the NEXT item's adv-form GET may return a ~289-byte TTS stub
# "SystemMessage:Connection refused." — a connection-layer transient (never
# reached the app tier; the anchor is NOT consumed). Retry the SAME anchor after
# a short escalating backoff before failing.
_CONN_REFUSED_MARK = 'Connection refused'
_ADV_FORM_RETRIES = 4
_ADV_FORM_BACKOFF = 1.5  # seconds; multiplied by attempt number (1.5/3.0/4.5)
_INFO_RE = re.compile(r"""name=["']?INFO["']?\s+value=["']?([0-9A-Fa-f]+)""", re.I)
_JOB_URL_RE = re.compile(r'AURL\s*=\s*"(/gpss4/gpsskmc/ttsserv_watch\?)"\s*\+\s*kmtmp')
_PTMP_RE = re.compile(r'ptmp\s*=\s*"([^"]+)"')
_NEEDCHECK_RE = re.compile(r'NeedCheck\s*=\s*1')
# BR_20260718: SEARCH-FORM watcher shell (前次檢索還沒好). Distinct from the
# RESULT-page AURL job shell (_JOB_URL_RE): the form page's JS polls
#   chkURL = "/gpss4/gpsskmc/ttsserv_watch?" + kmtmp + "/km.swp:<slot>:" +
#            curtslot(1) + ":" + encodeURIComponent("全部") + ":"
# and the DB_OK watch body carries per-DB hit counts `全部(N)` — for a
# zero-hit search this shell is the ONLY thing the server ever returns.
_CHKURL_RE = re.compile(
    r'chkURL\s*=\s*"(/gpss4/gpsskmc/ttsserv_watch\?)"\s*\+\s*kmtmp\s*\+\s*"(/km\.swp:\d+:)"')
_WATCH_COUNT_RE = re.compile(r'>([^<>()]+)\((\d[\d,]*)\)</font>')


async def _login_session() -> "GPSS4Session":
    """Login and return the authenticated (pure-httpx) GPSS4Session.

    The caller drives the whole advanced-search flow over session.client; there
    is no browser. member.html (with the 進階檢索 tab slot URL) is on the
    session's _refresh_chain.
    """
    s = GPSS4Session()
    await s.login()
    if not s._refresh_chain:
        await s.close()
        raise GPSS4AdvSearchError("login produced no member page (refresh chain empty)")
    return s


def _is_transient(html: str) -> bool:
    """BR_20260719 slot-expiry RCA (2026-07-19 instrumented trace): a ~289-byte
    TTS stub "SystemMessage:Connection refused." is a CONNECTION-LAYER transient
    — the request never reached the app tier, so NO state changed (no slot
    consumed, no query submitted). It can land on ANY hop (adv-form GET, query
    POST, 家族收合 POST, dual-view POST), typically right after a large-result
    item. Because nothing executed, replaying the SAME request is safe (never a
    double-submit). Detect by the marker OR the tell-tale tiny body.
    """
    return _CONN_REFUSED_MARK in html or len(html) < 600


async def _post_retry(s: "GPSS4Session", action: str, data: Dict[str, str],
                      referer: str, want: str) -> "httpx.Response":
    """POST with connection-layer-transient retry (see _is_transient). Retries
    the SAME POST after an escalating backoff while the response is a transient
    stub AND does not yet contain `want` (the success marker the caller needs).
    Safe because a Connection-refused response means the POST never executed.
    """
    pr = None
    for _attempt in range(_ADV_FORM_RETRIES):
        pr = await s.client.post(action, data=data, headers={"Referer": referer})
        if want in pr.text or not _is_transient(pr.text):
            return pr
        logger.info("POST transient (len=%d, attempt %d/%d); backoff+retry",
                    len(pr.text), _attempt + 1, _ADV_FORM_RETRIES)
        await asyncio.sleep(_ADV_FORM_BACKOFF * (_attempt + 1))
    return pr


def _dump(dump_dir: Optional[str], name: str, html: str) -> None:
    if not dump_dir:
        return
    try:
        os.makedirs(dump_dir, mode=0o700, exist_ok=True)
        with open(os.path.join(dump_dir, name), "w") as fh:
            fh.write(html)
    except OSError:
        pass


async def _submit_query(s: "GPSS4Session", adv_tab_url: str, query: str,
                        dump_dir: Optional[str]) -> tuple:
    """GET the 進階檢索 tab, POST the query. Return (result_html, form_action, info).

    form_action / info are needed later for the 家族收合 + JPAGE POSTs.
    """
    # adv-form GET with transient-retry (BR_20260719 slot-expiry RCA, 2026-07-19
    # instrumented trace): after a large-result item the server occasionally
    # returns a 289-byte TTS stub "SystemMessage:Connection refused." for the
    # NEXT item's adv-form GET — a CONNECTION-LAYER transient (the request never
    # reached the app tier), NOT a quota/limit and NOT a spent anchor. Since the
    # anchor was never consumed, re-GETting the SAME anchor after a short backoff
    # recovers. Retry a few times before failing; only a persistent miss raises.
    form_html = ""
    for _attempt in range(_ADV_FORM_RETRIES):
        resp = await s.get(adv_tab_url)
        form_html = resp.text
        if "_3_10_X" in form_html:
            break
        if _is_transient(form_html):
            logger.info(
                "adv-form GET transient (len=%d, attempt %d/%d); backoff+retry",
                len(form_html), _attempt + 1, _ADV_FORM_RETRIES)
            await asyncio.sleep(_ADV_FORM_BACKOFF * (_attempt + 1))
            continue
        break  # a substantive page without the form marker -> real failure
    _dump(dump_dir, "adv_form.html", form_html)
    if "_3_10_X" not in form_html:
        raise GPSS4AdvSearchError(
            f"adv form not reachable (no _3_10_X; len={len(form_html)}); "
            "wrong tab URL or session not authed?"
        )
    fm = _ADV_FORM_ACTION_RE.search(form_html)
    im = _INFO_RE.search(form_html)
    if not fm:
        raise GPSS4AdvSearchError("adv form action not found")
    action = BASE + fm.group(1)
    info = im.group(1) if im else ""
    data = {
        "INFO": info,
        "@_3_10_X": "T_XX",
        "_3_10_X": query,
        "_IMG_\u6aa2\u7d22.x": "20", "_IMG_\u6aa2\u7d22.y": "10",
    }
    # query POST with connection-layer-transient retry (any success marker or a
    # non-transient body ends the retry; INFO is the minimal result-form marker).
    pr = await _post_retry(s, action, data, str(resp.url), "INFO")
    result_html = pr.text
    # async job? poll ttsserv_watch until the result list renders.
    if _NEEDCHECK_RE.search(result_html) and not any(
        k in result_html for k in _RESULT_MARKERS
    ):
        result_html = await _poll_job(s, result_html, str(pr.url))
    # BR_20260718: still no result markers -> this may be the SEARCH-FORM
    # watcher shell (chkURL contract), which a zero-hit search never leaves.
    # Poll the watch: DB_OK + 全部(0) = genuine empty result (raise the
    # zero-hit unwinder); DB_OK + hits>0 with no list = typed fail-loud.
    if not any(k in result_html for k in _RESULT_MARKERS):
        counts = await _search_ready_watch(s, result_html, str(pr.url))
        if counts is not None:
            total_all = counts.get("全部", sum(counts.values()))
            if total_all == 0:
                raise GPSS4AdvZeroHits(counts, result_html)
            # BR_20260719 缺陷B: hits>0 但 result-list 未 render = 引擎 async race
            # (search-form watcher shell, NOT result-page)。降級為 recoverable
            # render-pending (carry counts + shell HTML 供 batch caller 保 anchor
            # 鏈 + 標 render_pending 不中斷整批)，不再用誤導的 "retry the query"
            # 文字直接當硬 error 累計 CONSECUTIVE_ERRORS。
            raise GPSS4AdvRenderPending(counts, result_html)
    _dump(dump_dir, "post_resp.html", result_html)
    # the result form's own action/INFO (for 家族收合 / JPAGE POSTs)
    rfm = _ADV_FORM_ACTION_RE.search(result_html)
    rim = _INFO_RE.search(result_html)
    return (result_html,
            BASE + rfm.group(1) if rfm else action,
            rim.group(1) if rim else info)


async def _search_ready_watch(s: "GPSS4Session", shell_html: str, referer: str,
                              max_polls: int = 40) -> Optional[Dict[str, int]]:
    """BR_20260718: poll the SEARCH-FORM shell's chkURL watch until DB_OK and
    return the per-DB hit counts {name: N}. Returns None when the shell does
    not carry the chkURL contract (different failure shape — let the caller's
    existing fail-fast paths handle it). Fails fast if the watch never
    completes."""
    cm = _CHKURL_RE.search(shell_html)
    pm = _PTMP_RE.search(shell_html)
    if not cm or not pm:
        return None
    kmtmp = pm.group(1).split("/")[0]
    watch = f"{BASE}{cm.group(1)}{kmtmp}{cm.group(2)}1:\u5168\u90e8:"
    for _ in range(max_polls):
        r = await s.client.get(watch, headers={"Referer": referer})
        if "DB_OK" in r.text:
            return {
                name.strip(): int(n.replace(",", ""))
                for name, n in _WATCH_COUNT_RE.findall(r.text)
            }
        await asyncio.sleep(1.5)
    raise GPSS4AdvSearchError(
        f"search-ready watch never reached DB_OK after {max_polls} polls")


async def _poll_job(s: "GPSS4Session", shell_html: str, referer: str,
                    max_polls: int = 40) -> str:
    """Poll ttsserv_watch until the job renders the result list (<!--DB_OK-->).

    Derives the watch URL from the job shell: AURL + kmtmp (from ptmp=kmwork/N).
    Returns the final result HTML. Fails fast if the job never completes.
    """
    import asyncio as _aio

    jm = _JOB_URL_RE.search(shell_html)
    pm = _PTMP_RE.search(shell_html)
    if not jm or not pm:
        # no parseable job contract; assume the shell IS the result
        return shell_html
    ptmp = pm.group(1)
    kmtmp = ptmp.split("/")[0]
    watch = f"{BASE}/gpss4/gpsskmc/ttsserv_watch?{kmtmp}/km.swp:4:1:\u5168\u90e8:"
    for _ in range(max_polls):
        r = await s.client.get(watch, headers={"Referer": referer})
        if "DB_OK" in r.text or any(k in r.text for k in _RESULT_MARKERS):
            # job done: re-fetch the result page (referer) to get the full list
            rr = await s.client.get(referer, headers={"Referer": referer})
            if any(k in rr.text for k in _RESULT_MARKERS):
                return rr.text
            return r.text
        await _aio.sleep(1.5)
    raise GPSS4AdvSearchError(f"job did not complete after {max_polls} polls")


async def _collapse_family(s: "GPSS4Session", form_action: str, info: str,
                          referer: str, dump_dir: Optional[str]) -> str:
    """POST BUTTON=家族收合 to get the collapsed list (with `N.M` family seqs)."""
    pr = await _post_retry(
        s, form_action, {"INFO": info, "BUTTON": "\u5bb6\u65cf\u6536\u5408"},
        referer, "INFO")
    _dump(dump_dir, "famcollapse.html", pr.text)
    return pr.text


def _view_form_data(html: str, img_name: str) -> tuple:
    """Build the (action, data) for a result-page image-submit POST
    (簡詳目並列 view switch / 次頁 pagination) — BR_20260716, playwright-
    captured contract 2026-07-17: INFO + @_0_15_T=T_XX + @_0_48_A=A_ +
    GPSSTECH + JPAGE + _IMG_<name>.x/.y + EVERY @R<hex>_db_rec_n hidden
    per-record input echoed back. Raw HTML attrs may be unquoted.
    """
    im = _INFO_RE.search(html)
    fm = _KM_FORM_ACTION_RE.search(html)
    if not im or not fm:
        raise GPSS4AdvSearchError(
            f"result-page form contract missing (INFO={bool(im)}, "
            f"action={bool(fm)}, len={len(html)}) — cannot {img_name}")
    data: Dict[str, str] = {
        "INFO": im.group(1),
        "@_0_15_T": "T_XX", "_0_15_T": "",
        "GPSSTECH": "",
        "@_0_48_A": "A_", "_0_48_A": "0",
        "JPAGE": "",
        f"_IMG_{img_name}.x": "16", f"_IMG_{img_name}.y": "15",
    }
    for hm in _HIDREC_RE.finditer(html):
        data[hm.group(1)] = "1"
    return BASE + fm.group(1), data


async def _enter_dual_view(s: "GPSS4Session", result_html: str, referer: str,
                           dump_dir: Optional[str],
                           bump_page_size: bool = True) -> tuple:
    """Switch the result list into 簡詳目並列 view (the ONLY view rendering
    patent numbers — BR_20260716) and (when bump_page_size) bump page size to 50
    via the 每頁 <select> slot-option GET. Returns (dual_html, new_referer).

    bump_page_size=False (BR_20260719 slot-expiry mitigation): a single-number
    query returns 1 family / <50 rows, so the 50/page GET is pointless — skipping
    it removes one slot-advancing request between anchor-harvest and next use
    (the surviving hypothesis for the batch depth-3 anchor staleness). harvest()
    keeps the default True (it paginates large pools).

    Fail-fast: if the switch does not render 公開公告號 rows, raise — never
    silently harvest the number-less 條列式 view.
    """
    action, data = _view_form_data(result_html, "簡詳目並列")
    # dual-view POST with connection-layer-transient retry (_DUAL_MARKER is the
    # success marker — the 公開公告號 rows we need).
    pr = await _post_retry(s, action, data, referer, _DUAL_MARKER)
    dual = pr.text
    _dump(dump_dir, "dualview_p1.html", dual)
    if _DUAL_MARKER not in dual:
        raise GPSS4AdvSearchError(
            f"簡詳目並列 view switch failed (len={len(dual)}, "
            "no 公開公告號 rows) — numbers unavailable")
    referer = str(pr.url)
    if not bump_page_size:
        return dual, referer
    # page size 50 (server maximum): the 每頁 <select> options are short-lived
    # slot URLs; GET the one labelled 50. Re-rendering resets to page 1.
    opts = _PSIZE_OPT_RE.findall(dual)
    u50 = next((u for u, n in opts if n == "50"), None)
    if u50:
        r = await s.client.get(BASE + u50, headers={"Referer": referer})
        if _DUAL_MARKER in r.text:
            dual, referer = r.text, str(r.url)
            _dump(dump_dir, "dualview_p1_50.html", dual)
        else:
            logger.warning("每頁=50 slot GET did not re-render dual view; "
                           "continuing at default page size")
    return dual, referer


async def _harvest_pages(s: "GPSS4Session", first_html: str, form_action: str,
                        info: str, referer: str, max_pages: int,
                        dump_dir: Optional[str]) -> List[AdvResultPage]:
    """Parse first_html, then paginate (頁碼 slot-URL or JPAGE POST) up to max_pages.

    Two mechanisms (DD-11): 簡目 = 頁碼 <select> slot URLs (GET); 家族收合 =
    JPAGE jump form (POST BUTTON=顯示結果 + JPAGE=<n>). Slot URLs are short-lived,
    re-read from each page.
    """
    out: List[AdvResultPage] = []
    html = first_html
    cur_ref = referer
    truncated = False
    seen_pages: set = set()   # guard against re-fetching the same page (a JPAGE
                              # POST that fails to advance returns the same page).
    for i in range(max_pages):
        rp = AdvResultPage.parse(html)
        # DEFENSIVE: if we landed on a page already parsed, pagination did not
        # advance — stop rather than loop forever re-collecting the same rows.
        if rp.page in seen_pages:
            break
        seen_pages.add(rp.page)
        out.append(rp)
        _dump(dump_dir, f"page_{i+1}.html", html)
        if rp.page >= rp.total_pages:
            break
        # would advance, but this iteration is the last allowed -> truncated:
        # there ARE more pages the server would serve, we just stopped early.
        if i == max_pages - 1:
            truncated = True
            break
        # PAGINATION — 簡詳目並列 view (BR_20260716): POST _IMG_次頁 with the
        # form contract re-read from THIS page (slot keys are single-use).
        if _DUAL_MARKER in html:
            if not _NEXTPG_RE.search(html):
                break
            n_action, n_data = _view_form_data(html, "\u6b21\u9801")
            pr = await s.client.post(n_action, data=n_data,
                                     headers={"Referer": cur_ref})
            if _DUAL_MARKER not in pr.text:
                break
            html, cur_ref = pr.text, n_action
            continue
        # PAGINATION legacy (簡目/家族收合, DD 2026-07-14): the GPSS4 進階檢索 result
        # list paginates ONLY via the 跳至第<N>頁 + 顯示結果 jump form — a POST of
        # {INFO, BUTTON=顯示結果, JPAGE=<next page>} to the KM form action. There
        # is NO per-page slot-URL <select>: the only <select> on the page whose
        # options carry gpsskm slot URLs is the 每頁[10/20/30/40/50]筆 PAGE-SIZE
        # picker (verified from real page HTML 2026-07-14). Following one of those
        # options just re-renders page 1 at a different page size — which is
        # exactly why the old "mechanism 1" (page_urls[rp.page]) silently capped
        # the harvest at the first 50 rows (page never advanced -> seen_pages
        # break). page_urls is therefore IGNORED for pagination.
        pr = await s.client.post(
            form_action,
            data={"INFO": info, "BUTTON": "\u986f\u793a\u7d50\u679c",
                  "JPAGE": str(rp.page + 1)},
            headers={"Referer": cur_ref},
        )
        if not any(k in pr.text for k in _RESULT_MARKERS):
            break
        html, cur_ref = pr.text, form_action
    return out, truncated


async def harvest(query: str, max_pages: int = 200, expand_family: bool = True,
                  dump_dir: Optional[str] = None,
                  databases: Optional[List[str]] = None,
                  persist_scope: bool = True) -> Dict[str, object]:
    """Full advanced-search harvest: login -> query -> collapse -> paginate -> parse.

    Pure httpx state machine (NO browser): the short-lived slot keys are
    extracted from each page's HTML and carried forward. Walks EVERY result
    page the server serves (50 rows/page — the 進階檢索 max, no 100/page option)
    and assembles ONE complete pool, exactly like paging through the web UI by
    hand. max_pages is a high SAFETY cap (200 pages = 10k rows), not a batch
    size; if a result set genuinely exceeds it the walk stops and the return
    carries truncated=true so the caller KNOWS the pool is partial (never a
    silent cut). Returns {total, family_count, patents[], complete, truncated, ...}.
    """
    s = await _login_session()
    try:
        member = s._refresh_chain[-1][1]
        # BR_20260716 DD-3/DD-6: database scope is an account-level per-user
        # server-side config, not a query param. When the caller pins
        # `databases`, set the scope FIRST (fail-fast on failure, DD-4) so the
        # subsequent query harvests a single-source pool. databases=None keeps
        # the account's current scope (back-compat).
        if databases:
            await set_search_databases(
                s, databases, persist=persist_scope, dump_dir=dump_dir)
        adv_tab_url = _extract_adv_tab_url(member)
        try:
            result_html, form_action, info = await _submit_query(
                s, adv_tab_url, query, dump_dir)
        except GPSS4AdvZeroHits as z:
            # BR_20260718: genuine zero-hit search (watch DB_OK, 全部(0)).
            # The server never renders a result list for these, so there is
            # nothing to view-switch or paginate — return a structured empty
            # pool instead of the old misleading "view switch failed" error.
            logger.info("GPSS4 adv search zero hits: %s", z.counts)
            return {
                "query": query,
                "total": 0,
                "hit_count": 0,
                "pages_fetched": 0,
                "total_pages": 0,
                "complete": True,
                "truncated": False,
                "zero_hits": True,
                "db_counts": z.counts,
                "patents": [],
            }
        referer = adv_tab_url
        if expand_family and "\u5bb6\u65cf\u6536\u5408" in result_html:
            collapsed = await _collapse_family(
                s, form_action, info, referer, dump_dir)
            if any(k in collapsed for k in _RESULT_MARKERS):
                result_html, referer = collapsed, form_action
        # BR_20260716: switch to 簡詳目並列 — the ONLY view that renders patent
        # numbers (default 條列式 shows seq checkboxes only) — and bump to 50/page.
        result_html, referer = await _enter_dual_view(
            s, result_html, referer, dump_dir)
        pages, truncated = await _harvest_pages(
            s, result_html, form_action, info, referer, max_pages, dump_dir)
    finally:
        await s.close()
    if not pages:
        raise GPSS4AdvSearchError("harvest produced no result pages")
    all_patents: List[AdvPatent] = []
    for rp in pages:
        all_patents.extend(rp.patents)
    first = pages[0]
    # DD-14: pubno-granularity ONLY. NO family grouping / representative marking.
    # The離線 family-dedup近似法 was廢棄 (recall=0實測失效) and the網站 family
    # collapse is不透明; every parsed row is kept as its own pubno record, nothing
    # is collapsed or tagged. hit_count = the actual number of rows harvested.
    return {
        "query": query,
        "total": first.total,
        "hit_count": len(all_patents),
        "pages_fetched": len(pages),
        "total_pages": first.total_pages,
        # complete = every page the server serves was walked into this ONE pool;
        # truncated = max_pages cap hit before the last page (pool is PARTIAL,
        # raise max_pages to get the rest). Never a silent cut.
        "complete": not truncated,
        "truncated": truncated,
        "patents": [p.to_dict() for p in all_patents],
    }


def write_csv(result: Dict[str, object], path: str) -> str:
    """Write harvested patents to a CSV file. Returns the path."""
    import csv

    patents = result.get("patents", [])  # type: ignore[assignment]
    fields = ["seq", "pat_no", "apply_no", "apply_date", "title", "abstract"]
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in patents:  # type: ignore[union-attr]
            w.writerow(p)
    return path


# --- CLI entry: `python -m patent_mcp_server.gpss4.adv_search "<query>" ...` ---
def _amain(argv: Optional[List[str]] = None) -> int:
    """CLI: harvest the GPSS4 advanced search into a family-tagged pool CSV.

    Pure httpx (no browser). Credentials from GPSS4_USERNAME / GPSS4_PASSWORD
    (env or .env). Prints a one-line summary + writes CSV when --csv is given.
    """
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="gpss4-adv-search",
        description="Harvest TIPO GPSS4 進階檢索 (advanced search) into a "
                    "family-tagged pool CSV. Bypasses the API daily-download quota.",
    )
    ap.add_argument("query",
                    help="GPSS syntax, e.g. '(video)@TI AND CS=H04N-0021/00'. "
                         "Use @-prefix for '-' at start (a leading @file reads "
                         "the query from that file).")
    ap.add_argument("--csv", default="",
                    help="output CSV path (UTF-8-BOM). If omitted, prints JSON.")
    ap.add_argument("--max-pages", type=int, default=20,
                    help="safety cap on pages to paginate (default 20).")
    ap.add_argument("--expand-family", action="store_true",
                    help="(DD-14 discouraged) click 家族收合 on the網站 before "
                         "harvesting. Default OFF: pubno-granularity, no網站 "
                         "family collapse (the collapse is不透明).")
    ap.add_argument("--dump-dir", default=None,
                    help="optional dir to dump each page's HTML (debug).")
    args = ap.parse_args(argv)

    query = args.query
    if query.startswith("@") and os.path.isfile(query[1:]):
        query = open(query[1:], encoding="utf-8").read().strip()

    try:
        res = asyncio.run(harvest(
            query, max_pages=args.max_pages,
            expand_family=args.expand_family, dump_dir=args.dump_dir))
    except GPSS4AdvSearchError as e:
        print(f"ERROR: {e}", file=__import__("sys").stderr)
        return 2

    if args.csv:
        write_csv(res, args.csv)
        print(f"total={res['total']} hits={res['hit_count']} "
              f"pages={res['pages_fetched']}/{res['total_pages']} "
              f"rows={len(res['patents'])}")
        print(f"CSV: {args.csv}")
    else:
        print(_json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    # load .env so credentials resolve when run standalone.
    # adv_search.py is at src/patent_mcp_server/gpss4/ -> repo root is 3 up.
    _envp = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))
    if os.path.isfile(_envp):
        for _line in open(_envp):
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k, _v)
    sys.exit(_amain())
