"""
GPSS4 member-area 標記清單 (mark list) operations.

Reverse-engineered & verified 2026-07-11 (design.md DD-5). All operations ride
ONE authenticated GPSS4Session (URL-slot session key). The "mark list" (標記清單)
is GPSS4's project-folder equivalent: patents the member has bookmarked.

Marking a patent is a THREE-step server-side session sequence:

  1. number search  — POST the KM form with `_21_1_T=(<no>)@PN` (image submit).
                       Response (~25KB) lists hits, each row carrying a checkbox
                       `onclick="clickselect(this,<db>,<rec>,<curt>)"`.
  2. clickselect    — GET gpssbkm?<TOK>^S^<db>_<rec>_<curt>_1^  (AJAX). This
                       writes the SELECTION into the server-side session; a plain
                       POSTed checkbox is rejected with alert('請勾選資料').
                       (_1^ = select, _0^ = deselect.)
  3. add to marks   — POST the result form with `BUTTON=加入標記清單` + INFO.
                       The RESPONSE PAGE IS the mark list itself (a synchronous
                       HTML table of marked patents — NOT an AJAX shell).

Critical trap (DD-5): do NOT re-fetch the mark list via the home page's
`gpssbkm?.<hex-token>` link — that token is bound to an EXPIRED slot and returns
an empty shell page (fixed "無標記資料" placeholder), which looks like an empty
list. The real list is the add-to-marks response, or a same-slot fetch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from patent_mcp_server.gpss4.session import GPSS4Session, BASE

# --- login-home / result-page parsing regexes --------------------------------
_KM_ACTION_RE = re.compile(
    r'<form[^>]*action="(/gpss4/gpsskmc/gpssbkm\?@@\d+)"[^>]*name=KM', re.I
)
_INFO_RE = re.compile(r'name=["\']?INFO["\']?\s+value=["\']?([0-9A-Fa-f]+)', re.I)
# result-row checkbox: name=R<token>_<db>_<rec>_<curt> onclick=clickselect(this,db,rec,curt)
_CHECKBOX_RE = re.compile(
    r'clickselect\(this,\s*(\d+),\s*(\d+),\s*(\d+)\)', re.I
)
# clickselect ajax url token: gpssbkm?<HEXTOK>^S^
_SELECT_TOK_RE = re.compile(r'gpssbkm\?([0-9A-Fa-f]+)\^S\^', re.I)
_COUNT_RE = re.compile(r'檢索結果[：:]\s*共\s*(\d+)\s*筆')
# mark-list table rows: patent-number tokens
_TW_NO_RE = re.compile(r'\b([A-Z]{2}\d{6,}[A-Z]?\d?)\b')


class GPSS4FolderError(RuntimeError):
    pass


@dataclass
class MarkedPatent:
    """One row in the mark list."""

    seq: Optional[str] = None
    apply_date: Optional[str] = None
    pub_date: Optional[str] = None
    apply_no: Optional[str] = None
    pub_no: Optional[str] = None
    title: Optional[str] = None
    applicant: Optional[str] = None
    raw_cells: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "seq": self.seq,
            "apply_date": self.apply_date,
            "pub_date": self.pub_date,
            "apply_no": self.apply_no,
            "pub_no": self.pub_no,
            "title": self.title,
            "applicant": self.applicant,
        }


class GPSS4Folder:
    """Read/write the GPSS4 member 標記清單 over one authenticated session."""

    # search-field suffix -> GPSS4 tudor query axis
    AXIS = {"pub": "@PN", "apply": "@AN"}

    def __init__(self, session: Optional[GPSS4Session] = None):
        self._s = session or GPSS4Session()

    async def _authed_home(self) -> str:
        """Fetch a fresh authed home page and return its HTML (for KM action/INFO)."""
        import random

        await self._s.ensure_logged_in()
        r = await self._s.get(
            f"{BASE}/gpss4/gpsskmc/gpssbkm?@@{random.randint(1, 9_999_999)}"
        )
        return r.text

    # ---- step 1: number search ------------------------------------------

    async def search_number(self, number: str, axis: str = "pub") -> "SearchResult":
        """POST a number search. axis='pub' (@PN) or 'apply' (@AN).

        Returns a SearchResult carrying the result HTML + parsed hit selectors.
        """
        home = await self._authed_home()
        am = _KM_ACTION_RE.search(home)
        im = _INFO_RE.search(home)
        if not am or not im:
            raise GPSS4FolderError(
                f"KM form action/INFO not found on home (action={bool(am)}, "
                f"info={bool(im)})"
            )
        action, info = am.group(1), im.group(1)
        suffix = self.AXIS.get(axis)
        if not suffix:
            raise GPSS4FolderError(f"unknown search axis {axis!r} (use pub|apply)")
        data = {
            "INFO": info,
            "@_21_1_T": "T_XX",
            "_21_1_T": f"({number}){suffix}",
            "@_0_9_T": "T_XX",
            "_0_9_T": "",
            "_IMG_檢索.x": "20",
            "_IMG_檢索.y": "10",
        }
        resp = await self._s.client.post(
            f"{BASE}{action}", data=data, headers={"Referer": f"{BASE}{action}"}
        )
        return SearchResult.parse(resp.text, resp)

    # ---- step 2: clickselect --------------------------------------------

    async def select_hit(self, result: "SearchResult", index: int = 0,
                         select: bool = True) -> None:
        """Select (or deselect) the Nth hit via the clickselect AJAX GET.

        Writes the selection into the server-side session so the subsequent
        add-to-marks POST sees it.
        """
        if index >= len(result.hits):
            raise GPSS4FolderError(
                f"hit index {index} out of range ({len(result.hits)} hits)"
            )
        if not result.select_token:
            raise GPSS4FolderError("clickselect token not found on result page")
        db, rec, curt = result.hits[index]
        flag = "1" if select else "0"
        url = (
            f"{BASE}/gpss4/gpsskmc/gpssbkm?"
            f"{result.select_token}^S^{db}_{rec}_{curt}_{flag}^"
        )
        await self._s.client.get(url, headers={"Referer": str(result.response.url)})

    # ---- step 3: add to marks -------------------------------------------

    async def add_marks(self, result: "SearchResult") -> "MarkList":
        """POST BUTTON=加入標記清單. The response page IS the mark list."""
        resp = await self._s.client.post(
            f"{BASE}{result.action}",
            data={"INFO": result.info, "BUTTON": "加入標記清單"},
            headers={"Referer": str(result.response.url)},
        )
        return MarkList.parse(resp.text)

    # ---- high-level: mark a patent by number ----------------------------

    async def mark_patent(self, number: str, axis: str = "pub") -> "MarkList":
        """Full 3-step sequence: search -> select first hit -> add to marks."""
        result = await self.search_number(number, axis=axis)
        if not result.hits:
            raise GPSS4FolderError(f"no hits for {number!r} ({axis})")
        await self.select_hit(result, 0, select=True)
        return await self.add_marks(result)

    async def current_marks(self) -> "MarkList":
        """Read the current 標記清單 via the member-area mark-list link.

        DD-5 trap: the home page's `gpssbkm?.<hex-token>` mark-list link is bound
        to whichever slot minted it. Fetching it on the SAME authed session (not
        an expired slot) surfaces the real list; an expired-slot fetch returns the
        empty-shell placeholder, which MarkList.parse detects (is_empty=True).
        """
        home = await self._authed_home()
        m = re.search(r'href=(/gpss4/gpsskmc/gpssbkm\?\.[0-9A-Fa-f]+)\s*>\s*標記清單', home)
        if not m:
            m = re.search(r'href=["\']?(/gpss4/gpsskmc/gpssbkm\?\.[0-9A-Fa-f]+)["\']?[^>]*>\s*標記清單', home)
        if not m:
            raise GPSS4FolderError("標記清單 link not found on member home")
        resp = await self._s.client.get(
            f"{BASE}{m.group(1)}", headers={"Referer": f"{BASE}/gpss4/gpsskmc/gpssbkm"}
        )
        return MarkList.parse(resp.text)

    async def close(self) -> None:
        await self._s.close()


@dataclass
class SearchResult:
    """Parsed number-search result page."""

    html: str
    response: object
    action: str
    info: str
    select_token: Optional[str]
    count: int
    hits: List[tuple]  # list of (db, rec, curt)

    @classmethod
    def parse(cls, html: str, response) -> "SearchResult":
        am = _KM_ACTION_RE.search(html)
        im = _INFO_RE.search(html)
        tok = _SELECT_TOK_RE.search(html)
        cm = _COUNT_RE.search(html)
        hits = [(m.group(1), m.group(2), m.group(3))
                for m in _CHECKBOX_RE.finditer(html)]
        return cls(
            html=html,
            response=response,
            action=am.group(1) if am else "",
            info=im.group(1) if im else "",
            select_token=tok.group(1) if tok else None,
            count=int(cm.group(1)) if cm else len(hits),
            hits=hits,
        )


@dataclass
class MarkList:
    """Parsed 標記清單 (the add-to-marks response page)."""

    count: int
    patents: List[MarkedPatent]
    is_empty: bool

    @classmethod
    def parse(cls, html: str) -> "MarkList":
        # empty-shell guard: the expired-slot link returns this placeholder
        if "無標記資料" in html and "檢索結果" not in html:
            return cls(count=0, patents=[], is_empty=True)
        cm = _COUNT_RE.search(html)
        count = int(cm.group(1)) if cm else 0
        patents = cls._extract_rows(html)
        return cls(count=count or len(patents), patents=patents,
                   is_empty=(count == 0 and not patents))

    @staticmethod
    def _extract_rows(html: str) -> List[MarkedPatent]:
        """Extract patent rows from the mark-list HTML table.

        The table has columns: 序號 主要圖式 申請日 公開公告日 申請號 公開公告號
        專利名稱 申請人. We parse <tr> blocks that carry a patent number cell.
        """
        patents: List[MarkedPatent] = []
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
            cells = [re.sub(r'<[^>]+>', '', c).strip()
                     for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            # a data row has a patent-number-looking cell
            nums = [c for c in cells if _TW_NO_RE.fullmatch(c or "")]
            if not nums:
                continue
            p = MarkedPatent(raw_cells=cells)
            # heuristic column mapping (may vary; raw_cells always preserved)
            date_cells = [c for c in cells if re.fullmatch(r'\d{4}/\d{2}/\d{2}', c or "")]
            no_cells = [c for c in cells if _TW_NO_RE.fullmatch(c or "")]
            if cells and re.fullmatch(r'\d+', cells[0] or ""):
                p.seq = cells[0]
            if len(date_cells) >= 1:
                p.apply_date = date_cells[0]
            if len(date_cells) >= 2:
                p.pub_date = date_cells[1]
            if len(no_cells) >= 1:
                p.apply_no = no_cells[0]
            if len(no_cells) >= 2:
                p.pub_no = no_cells[1]
            patents.append(p)
        return patents

    def to_dict(self) -> Dict[str, object]:
        return {
            "count": self.count,
            "is_empty": self.is_empty,
            "patents": [p.to_dict() for p in self.patents],
        }
