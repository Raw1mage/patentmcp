"""
TIPO GPSS (Global Patent Search System) integration.

TIPO's GPSS REST API retrieves cross-national patent data (TW/US/CN/JP/KR/EP/WIPO
and more) filtered by a search formula. Unlike Google Patents it is an official,
ToS-clean API; unlike BigQuery it bills by quota, not bytes scanned. It supports
CPC/IPC anchoring and full-text claims search, and returns JSON.

Auth is a single `userCode` (API 驗證碼) issued by TIPO after approval — read from
the GPSS_USER_CODE environment variable.
"""

from patent_mcp_server.gpss.client import GPSSClient

__all__ = ["GPSSClient"]
