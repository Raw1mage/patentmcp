"""
TIPO GPSS (Global Patent Search System) integration.

TIPO's GPSS REST API retrieves cross-national patent data (TW/US/CN/JP/KR/EP/WIPO
and more) filtered by a search formula. Unlike Google Patents it is an official,
ToS-clean API; unlike BigQuery it bills by quota, not bytes scanned. It supports
CPC/IPC anchoring and full-text claims search, and returns JSON.

Auth is a `userCode` (API 驗證碼) issued by TIPO after approval. The client holds
an ORDERED POOL of userCodes (GPSS_USER_CODES, comma-separated) and rotates to
the next account when one's time-window quota is exhausted; when all are spent it
fails fast with GPSS_ALL_ACCOUNTS_EXHAUSTED. The legacy single GPSS_USER_CODE is
still honoured when GPSS_USER_CODES is unset.
"""

from patent_mcp_server.gpss.client import GPSSClient

__all__ = ["GPSSClient"]
