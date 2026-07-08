#!/usr/bin/env python3
"""figure_extract.py — R13 landing plane: locate + render a patent's representative figure.

Deterministic poppler-CLI pipeline over a PDF the agent already downloaded (via a
container fetch tool / WebDAV). Ports _locate_figure_page / _render_page_png /
_verify_pdf_identity / _pdf_image_count from the container.

Strategy (BR_20260628 D): skip page 1 (cover/biblio), find the first page whose
text matches a FIG.1 marker, else the page (>=2) with highest reference-numeral
density; render that page to PNG. If no figure page can be located, report
NO_FIGURE_PAGE (or NO_FIGURE_PAGE_BUT_IMAGES_PRESENT when the PDF has embedded
images but no text layer) — never guess.

DEPENDENCY: poppler CLIs (pdfinfo, pdftoppm, pdftotext, pdfimages). Missing any →
typed MISSING_DEPENDENCY, exit 2.

Usage:
  python3 figure_extract.py --pdf in.pdf --out fig1.png [--dpi 200]

All errors print a single-line typed JSON envelope + nonzero exit; no traceback
reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_POPPLER_BINS = ["pdfinfo", "pdftoppm", "pdftotext", "pdfimages"]


def _repo_root() -> Path:
    """patentmcp repo root. This script lives at
    ``<repo>/skills/patentworks/scripts/figure_extract.py`` → 3 parents up."""
    return Path(__file__).resolve().parents[3]


def src_dir(repo: "str | None" = None) -> Path:
    """Repo-local PERSISTENT intermediate-artefact directory ``<repo>/.src/``.

    Unified landing plane (plans/infra_docxmcp-stateless-container DD-6/DD-6a) —
    the same convention docxmcp uses via ``docx_utils.src_dir()``. Cross-step /
    cross-session / cross-restart artefacts (downloaded figures a later step
    inserts into a docx) land here so they survive restarts, unlike system
    ``/tmp``. Gitignored; created 0700 so private working artefacts never land
    world-readable. Root resolution order:
      1. explicit ``repo`` arg (the ``--repo`` landing-plane hook)
      2. ``$PATENTMCP_SRC_ROOT`` env (absolute)
      3. ``<repo>/.src`` (default)
    """
    if repo:
        base = Path(repo).expanduser().resolve()
    else:
        env = os.environ.get("PATENTMCP_SRC_ROOT")
        base = Path(env).expanduser().resolve() if env else _repo_root()
    d = base / ".src"
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:
        pass
    return d

_FIG1_PATTERNS = [
    re.compile(r"\bFIG\.?\s*1\b", re.IGNORECASE),
    re.compile(r"\bFIGURE\s*1\b", re.IGNORECASE),
    re.compile(r"图\s*1\b"),
    re.compile(r"圖\s*1\b"),
    re.compile(r"第\s*1\s*圖"),
    re.compile(r"第\s*1\s*图"),
]
_REFNUM_RE = re.compile(r"\b\d{1,3}[a-z]?\b")


class ScriptError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 2, **extra):
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.extra = extra
        super().__init__(message)


def _fail(code: str, message: str, exit_code: int = 2, **extra) -> None:
    env = {"success": False, "error_code": code, "message": message}
    env.update(extra)
    sys.stdout.write(json.dumps(env, ensure_ascii=False) + "\n")
    sys.exit(exit_code)


def _pdf_page_count(pdf_path: str) -> int:
    try:
        out = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, timeout=30)
        for line in out.stdout.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        return 0
    return 0


def _pdf_page_text(pdf_path: str, page: int) -> str:
    try:
        out = subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout or ""
    except Exception:
        return ""


def _pdf_image_count(pdf_path: str) -> int:
    try:
        out = subprocess.run(["pdfimages", "-list", pdf_path],
                             capture_output=True, text=True, timeout=60)
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if len(lines) <= 2:
            return 0
        count = 0
        for ln in lines[2:]:
            first = ln.split(None, 1)[0] if ln.split() else ""
            if first.isdigit():
                count += 1
        return count
    except Exception:
        return 0


def _locate_figure_page(pdf_path: str) -> dict:
    pages = _pdf_page_count(pdf_path)
    if pages <= 0:
        return {"page": None, "method": "none", "pages": pages}
    start = 2 if pages >= 2 else 1
    best_refnum_page = None
    best_refnum_count = -1
    for p in range(start, pages + 1):
        text = _pdf_page_text(pdf_path, p)
        if not text.strip():
            continue
        for pat in _FIG1_PATTERNS:
            if pat.search(text):
                return {"page": p, "method": "fig1_text", "pages": pages}
        count = len(_REFNUM_RE.findall(text))
        if count > best_refnum_count:
            best_refnum_count = count
            best_refnum_page = p
    if best_refnum_page is not None and best_refnum_count >= 5:
        return {"page": best_refnum_page, "method": "refnum_density_fallback", "pages": pages}
    return {"page": None, "method": "none", "pages": pages}


def _render_page_png(pdf_path: str, page: int, dpi: int = 200):
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "page")
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page),
                 "-png", pdf_path, prefix],
                capture_output=True, text=True, timeout=120, check=True,
            )
        except Exception:
            return None
        for fn in sorted(os.listdir(td)):
            if fn.endswith(".png"):
                with open(os.path.join(td, fn), "rb") as fh:
                    return fh.read()
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="figure_extract.py",
        description="Locate + render a patent's representative figure (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--pdf", required=True, help="input PDF path")
    p.add_argument("--out", default=None,
                   help="output PNG path. If omitted, lands in the unified "
                        ".src/ landing plane (DD-6a): <src_dir>/fig_<pdfstem>.png")
    p.add_argument("--dpi", type=int, default=200, help="render DPI (default 200)")
    p.add_argument("--repo", default=None,
                   help="repo root for the .src/ landing plane (DD-6a). When "
                        "--out is omitted, the figure lands under <repo>/.src/.")
    args = p.parse_args(argv)

    missing = [b for b in _POPPLER_BINS if shutil.which(b) is None]
    if missing:
        raise ScriptError("MISSING_DEPENDENCY",
                          f"poppler binaries not found: {', '.join(missing)}",
                          missing=missing,
                          hint="install poppler-utils on the host")

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"pdf not found: {pdf_path}")

    loc = _locate_figure_page(str(pdf_path))
    if loc["page"] is None:
        img_count = _pdf_image_count(str(pdf_path))
        if img_count > 0:
            raise ScriptError(
                "NO_FIGURE_PAGE_BUT_IMAGES_PRESENT",
                "could not locate a FIG.1 page by text, but the PDF has embedded images "
                "(scanned / no text layer)",
                image_count=img_count, pages=loc["pages"],
            )
        raise ScriptError("NO_FIGURE_PAGE",
                          "could not locate a representative figure page",
                          pages=loc["pages"])

    png = _render_page_png(str(pdf_path), loc["page"], dpi=args.dpi)
    if png is None:
        raise ScriptError("RENDER_FAILED", f"pdftoppm failed to render page {loc['page']}")

    # Landing plane (DD-6a): explicit --out wins; otherwise land in the unified
    # persistent .src/ dir (NOT system /tmp) so the figure survives restarts and
    # a later step (e.g. docx insertion) can re-read it.
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = src_dir(args.repo) / f"fig_{pdf_path.stem}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)

    sys.stdout.write(json.dumps({
        "success": True,
        "out": str(out_path),
        "page": loc["page"],
        "method": loc["method"],
        "pages": loc["pages"],
        "dpi": args.dpi,
        "bytes": len(png),
    }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScriptError as e:
        _fail(e.code, e.message, exit_code=e.exit_code, **e.extra)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        _fail("UNEXPECTED", f"{type(e).__name__}: {e}")
