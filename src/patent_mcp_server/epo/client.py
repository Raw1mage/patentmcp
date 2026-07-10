"""Client for EPO Open Patent Services (OPS) v3.2.

OAuth2 client_credentials with auto-refresh. Endpoints used:
  - family/publication/docdb/{cc.num.kind}            INPADOC family
  - published-data/publication/docdb/{...}/biblio     bibliographic data
  - published-data/publication/docdb/{...}/abstract   abstract
  - published-data/publication/docdb/{...}/images     image availability
  - published-data/images/{...}/fullimage.pdf         image download
  - published-data/search?q={CQL}                     CQL search
"""
import asyncio
import base64
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
BASE_URL = "https://ops.epo.org/3.2/rest-services"


def to_docdb(pub: str) -> Optional[str]:
    """Normalize a publication number to OPS docdb format 'CC.NUMBER.KIND'.
    e.g. US11213256B2 / US-11213256-B2 -> US.11213256.B2; TW-I684433-B -> TW.I684433.B
    """
    p = re.sub(r"[\s\-]", "", pub).upper()
    m = re.match(r"^([A-Z]{2})([0-9A-Z]+?)([A-Z][0-9]?)$", p)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def _txt(node: Any) -> str:
    """Pull the text out of an OPS JSON value node ({'$': 'text'} or str)."""
    if isinstance(node, dict):
        return str(node.get("$", "")).strip()
    return str(node or "").strip()


def clean_badgerfish_text(node: Any) -> str:
    """Recursively extract and clean text from BadgerFish JSON structures."""
    import re
    def _raw(n: Any) -> str:
        if isinstance(n, str):
            return n
        if isinstance(n, list):
            return "".join(_raw(x) for x in n if x)
        if isinstance(n, dict):
            res = []
            if "$" in n:
                res.append(str(n["$"]))
            for k, v in n.items():
                if k != "$" and not k.startswith("@"):
                    res.append(_raw(v))
            return "".join(res)
        return str(n or "")
    
    return re.sub(r"\s+", " ", _raw(node)).strip()


class EPOClient:
    def __init__(self, key: Optional[str] = None, secret: Optional[str] = None,
                 timeout: float = 30.0, min_interval: Optional[float] = None):
        self.key = key or os.getenv("EPO_CONSUMER_KEY")
        self.secret = secret or os.getenv("EPO_CONSUMER_SECRET")
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._lock = asyncio.Lock()       # token refresh
        self._req_lock = asyncio.Lock()   # single-flight + pacing
        # OPS throttles per service (search=15/min is tightest). Space requests
        # and back off on 403/429 so we never trip "overloaded".
        self.min_interval = float(
            os.getenv("PATENTS_EPO_MIN_INTERVAL",
                      min_interval if min_interval is not None else 1.5))
        self.max_retries = int(os.getenv("PATENTS_EPO_MAX_RETRIES", "3"))
        self._last_req = 0.0
        self._cooldown_until = 0.0
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    def configured(self) -> bool:
        return bool(self.key and self.secret)

    async def _token_value(self) -> str:
        async with self._lock:
            if self._token and time.monotonic() < self._token_exp - 60:
                return self._token
            b64 = base64.b64encode(f"{self.key}:{self.secret}".encode()).decode()
            resp = await self._client.post(
                AUTH_URL,
                headers={"Authorization": f"Basic {b64}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
            )
            resp.raise_for_status()
            j = resp.json()
            self._token = j["access_token"]
            self._token_exp = time.monotonic() + int(j.get("expires_in", 1200))
            return self._token

    async def _request(self, path: str, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
        async with self._req_lock:
            for attempt in range(self.max_retries + 1):
                token = await self._token_value()
                now = time.monotonic()
                wait = max(self.min_interval - (now - self._last_req),
                           self._cooldown_until - now, 0.0)
                if wait > 0:
                    await asyncio.sleep(wait)
                
                req_headers = {"Authorization": f"Bearer {token}"}
                if headers:
                    req_headers.update(headers)
                
                try:
                    resp = await self._client.get(BASE_URL + path, headers=req_headers)
                finally:
                    self._last_req = time.monotonic()
                
                if resp.status_code == 404:
                    return resp
                
                # OPS signals throttling via 403/429 (and X-Throttling-Control).
                if resp.status_code in (403, 429):
                    backoff = min(60.0, 6.0 * (2 ** attempt))
                    self._cooldown_until = time.monotonic() + backoff
                    logger.warning("EPO %d (throttled: %s); cooldown %.0fs attempt %d/%d",
                                   resp.status_code,
                                   resp.headers.get("X-Throttling-Control", ""),
                                   backoff, attempt + 1, self.max_retries)
                    if attempt < self.max_retries:
                        continue
                
                resp.raise_for_status()
                return resp
            resp.raise_for_status()
            return resp

    async def _get(self, path: str) -> Dict[str, Any]:
        resp = await self._request(path, headers={"Accept": "application/json"})
        if resp.status_code == 404:
            return {"_status": 404}
        return resp.json()

    async def _get_binary(self, path: str, accept: str = "*/*") -> bytes:
        resp = await self._request(path, headers={"Accept": accept})
        if resp.status_code == 404:
            return b""
        return resp.content

    # ── family ──────────────────────────────────────────────────────
    async def family(self, pub: str) -> Dict[str, Any]:
        """INPADOC patent family for a publication. Returns the deduped member
        publication numbers across jurisdictions."""
        if not self.configured():
            return {"success": False, "error": "EPO_CONSUMER_KEY/SECRET not set"}
        docdb = to_docdb(pub)
        if not docdb:
            return {"success": False, "error": f"cannot parse pub number: {pub}"}
        try:
            data = await self._get(f"/family/publication/docdb/{docdb}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO family failed for {pub}: {e}")
            return {"success": False, "error": str(e)}
        if data.get("_status") == 404:
            return {"success": True, "pub": pub, "count": 0, "members": []}
        fam = (data.get("ops:world-patent-data", {})
                   .get("ops:patent-family", {}))
        members = fam.get("ops:family-member", [])
        if isinstance(members, dict):
            members = [members]
        # EPO OPS carries @family-id on the family-member node, NOT on the
        # ops:patent-family container. Read it from the first member (all
        # INPADOC members of one invention share the same family-id).
        family_id = fam.get("@family-id")
        if not family_id and members:
            family_id = members[0].get("@family-id")
        seen, out = set(), []
        for m in members:
            dids = m.get("publication-reference", {}).get("document-id", [])
            dids = dids if isinstance(dids, list) else [dids]
            for d in dids:
                if d.get("@document-id-type") == "docdb":
                    cc = _txt(d.get("country")); num = _txt(d.get("doc-number")); kind = _txt(d.get("kind"))
                    key = f"{cc}{num}"
                    if cc and num and key not in seen:
                        seen.add(key)
                        out.append(f"{cc}{num}{kind}")
        return {"success": True, "pub": pub, "family_id": family_id,
                "count": len(out), "members": out}

    # ── biblio (+ abstract) ─────────────────────────────────────────
    async def biblio(self, pub: str) -> Dict[str, Any]:
        """Official bibliographic data + abstract for a publication."""
        if not self.configured():
            return {"success": False, "error": "EPO_CONSUMER_KEY/SECRET not set"}
        docdb = to_docdb(pub)
        if not docdb:
            return {"success": False, "error": f"cannot parse pub number: {pub}"}
        try:
            data = await self._get(f"/published-data/publication/docdb/{docdb}/biblio")
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO biblio failed for {pub}: {e}")
            return {"success": False, "error": str(e)}
        if data.get("_status") == 404:
            return {"success": True, "pub": pub, "found": False}
        try:
            doc = (data["ops:world-patent-data"]["exchange-documents"]["exchange-document"])
            if isinstance(doc, list):
                doc = doc[0]
            bib = doc.get("bibliographic-data", {})
            # title (prefer en)
            titles = bib.get("invention-title", [])
            titles = titles if isinstance(titles, list) else [titles]
            title = ""
            for t in titles:
                if t.get("@lang") == "en":
                    title = _txt(t); break
            if not title and titles:
                title = _txt(titles[0])
            # abstract
            abs = doc.get("abstract", [])
            abs = abs if isinstance(abs, list) else [abs]
            abstract = ""
            for a in abs:
                p = a.get("p", [])
                p = p if isinstance(p, list) else [p]
                abstract = " ".join(_txt(x) for x in p)
                if a.get("@lang") == "en":
                    break
            # applicants
            parties = bib.get("parties", {})
            apps = parties.get("applicants", {}).get("applicant", [])
            apps = apps if isinstance(apps, list) else [apps]
            applicants = []
            for a in apps:
                nm = a.get("applicant-name", {}).get("name")
                if nm and a.get("@data-format") == "epodoc":
                    applicants.append(_txt(nm))
            # classifications
            ipc = bib.get("classifications-ipcr", {}).get("classification-ipcr", [])
            ipc = ipc if isinstance(ipc, list) else [ipc]
            ipc_codes = [_txt(c.get("text")) for c in ipc if c]
            return {"success": True, "pub": pub, "found": True, "title": title,
                    "abstract": abstract, "applicants": applicants,
                    "ipc": ipc_codes[:8]}
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO biblio parse failed for {pub}: {e}")
            return {"success": False, "error": f"parse error: {e}"}

    # ── CQL search ──────────────────────────────────────────────────
    async def search(self, cql: str, range_: str = "1-25") -> Dict[str, Any]:
        """Search published data with a CQL query (e.g. 'pa=faceheart' or
        'txt=photoplethysmography and ic=A61B5/024'). Returns matched publication
        numbers and the total count."""
        if not self.configured():
            return {"success": False, "error": "EPO_CONSUMER_KEY/SECRET not set"}
        import urllib.parse
        q = urllib.parse.quote(cql)
        try:
            data = await self._get(f"/published-data/search?q={q}&Range={range_}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO search failed: {e}")
            return {"success": False, "error": str(e)}
        try:
            sr = data["ops:world-patent-data"]["ops:biblio-search"]
            total = int(sr.get("@total-result-count", 0))
            refs = sr.get("ops:search-result", {}).get("ops:publication-reference", [])
            refs = refs if isinstance(refs, list) else [refs]
            pubs = []
            for r in refs:
                dids = r.get("document-id", [])
                dids = dids if isinstance(dids, list) else [dids]
                for d in dids:
                    if d.get("@document-id-type") == "docdb":
                        cc = _txt(d.get("country")); num = _txt(d.get("doc-number")); kind = _txt(d.get("kind"))
                        pubs.append(f"{cc}{num}{kind}")
            return {"success": True, "cql": cql, "total": total,
                    "count": len(pubs), "results": pubs}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"parse error: {e}"}

    # ── images ──────────────────────────────────────────────────────
    async def images(self, pub: str) -> Dict[str, Any]:
        """Check image availability for a publication."""
        if not self.configured():
            return {"success": False, "error": "EPO_CONSUMER_KEY/SECRET not set"}
        docdb = to_docdb(pub)
        if not docdb:
            return {"success": False, "error": f"cannot parse pub number: {pub}"}
        try:
            data = await self._get(f"/published-data/publication/docdb/{docdb}/images")
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO images failed for {pub}: {e}")
            return {"success": False, "error": str(e)}
        if data.get("_status") == 404:
            return {"success": True, "pub": pub, "count": 0, "images": []}
        return {"success": True, "pub": pub, "data": data}

    # ── claims ──────────────────────────────────────────────────────
    async def claims(self, pub: str) -> Dict[str, Any]:
        """Official claims data for a publication."""
        if not self.configured():
            return {"success": False, "error": "EPO_CONSUMER_KEY/SECRET not set"}
        docdb = to_docdb(pub)
        if not docdb:
            return {"success": False, "error": f"cannot parse pub number: {pub}"}
        try:
            data = await self._get(f"/published-data/publication/docdb/{docdb}/claims")
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO claims failed for {pub}: {e}")
            return {"success": False, "error": str(e)}
        if data.get("_status") == 404:
            return {"success": True, "pub": pub, "found": False}
        try:
            root = data.get("ops:world-patent-data", {})
            doc_container = root.get("ftxt:fulltext-documents") or root.get("exchange-documents") or {}
            doc = doc_container.get("ftxt:fulltext-document") or doc_container.get("exchange-document") or {}
            
            if isinstance(doc, list):
                doc = doc[0]
            
            claims_root = doc.get("claims", {})
            if isinstance(claims_root, list):
                claims_root = claims_root[0]
                
            claim_data = claims_root.get("claim")
            
            claim_candidates = []
            if isinstance(claim_data, list):
                for c in claim_data:
                    if isinstance(c, dict):
                        ct = c.get("claim-text")
                        txt = clean_badgerfish_text(ct)
                        if txt:
                            claim_candidates.append(txt)
            elif isinstance(claim_data, dict):
                ct = claim_data.get("claim-text")
                if isinstance(ct, list):
                    for item in ct:
                        txt = clean_badgerfish_text(item)
                        if txt:
                            claim_candidates.append(txt)
                else:
                    txt = clean_badgerfish_text(ct)
                    if txt:
                        claim_candidates.append(txt)
            
            claim1 = ""
            for candidate in claim_candidates:
                cand_lower = candidate.strip().lower().rstrip(":")
                if cand_lower not in {
                    "what is claimed is", "what we claim is", "what i claim is",
                    "we claim", "i claim", "claims", "what is claimed",
                    "what i claim", "what we claim", "claim", "the claims"
                }:
                    claim1 = candidate
                    break
            if not claim1 and claim_candidates:
                claim1 = claim_candidates[0]
            
            return {"success": True, "pub": pub, "found": bool(claim1), "claim1": claim1}
        except Exception as e:  # noqa: BLE001
            logger.error(f"EPO claims parse failed for {pub}: {e}")
            return {"success": False, "error": f"parse error: {e}"}

    async def download_image_pdf(self, pub: str, range_: str = "1") -> bytes:
        """Download a patent image PDF page range."""
        if not self.configured():
            raise ValueError("EPO_CONSUMER_KEY/SECRET not set")
        docdb = to_docdb(pub)
        if not docdb:
            raise ValueError(f"cannot parse pub number: {pub}")
        # docdb is CC.NUM.KIND
        cc, num, kind = docdb.split(".")
        path = f"/published-data/images/{cc}/{num}/{kind}/fullimage.pdf?Range={range_}"
        return await self._get_binary(path, accept="application/pdf")

    async def close(self):
        await self._client.aclose()
