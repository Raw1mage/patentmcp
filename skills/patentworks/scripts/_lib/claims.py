"""Pure, stdlib-only claim/HTML text helpers.

Deterministic, zero-network. Moved verbatim from patents.py so both the
container and landing scripts can import them without pulling network clients.
"""
from __future__ import annotations


def clean_html_text(html_text: str) -> str:
    if not html_text:
        return ""
    import re
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Normalize whitespaces
    return re.sub(r'\s+', ' ', text).strip()


def extract_claim1_text(claims_text: str, full: bool = True) -> str:
    if not claims_text:
        return "Claim 1 not found."
    claims_text = claims_text.strip()
    import re

    text = None
    for pattern in [
        r'1\.\s+(.*?)(?=\s+2\.\s+|\n2\.)',
        r'1\.\s+(.*)',
        r'1[\.、](.*?)(?=\s*2[\.、]|\n2[\.、])',
        r'1[\.、](.*)'
    ]:
        m = re.search(pattern, claims_text, re.DOTALL | (re.IGNORECASE if '2' in pattern else 0))
        if m:
            text = re.sub(r'\s+', ' ', m.group(1).strip())
            break

    if text is None:
        text = claims_text.strip()

    if not full and len(text) > 1000:
        return text[:1000].strip() + "..."
    return text
