"""
TIPO GPSS4 web-app MEMBER integration (專案資料夾 / project folders).

Distinct from `patent_mcp_server.gpss` (the REST search API, single userCode):
this module drives the GPSS4 *web app* logged-in member area — session-based
(custom TTS* cookies), 5-GIF CAPTCHA login, token-URL page navigation.

First version is read-only: list project folders, list patents in a folder,
export folder contents.

Credentials come from GPSS4_USERNAME / GPSS4_PASSWORD (env / .env).
"""

from patent_mcp_server.gpss4.session import GPSS4Session

__all__ = ["GPSS4Session"]
