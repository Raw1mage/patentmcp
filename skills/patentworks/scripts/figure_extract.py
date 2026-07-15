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


def _poppler_available() -> bool:
    return not [b for b in _POPPLER_BINS if shutil.which(b) is None]


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


# ---------------------------------------------------------------------------
# BR_20260715 #04 (cuboai): image-projection fallback.
#
# The poppler/pdftotext locator above assumes a TEXT LAYER. Patent PDFs fetched
# via google_citation are frequently image-only scans (get_text() == "" on every
# page), so the FIG.1 text markers never match and the whole file yields
# NO_FIGURE_PAGE_BUT_IMAGES_PRESENT — zero figures. This fallback classifies a
# page as text vs figure purely from its RENDERED PIXELS (no text layer needed):
#
#   * render each page grayscale @ ~90dpi
#   * row projection: a row is "inked" if its dark-pixel fraction > 0.4%
#   * count contiguous runs of inked rows:
#       - text page  = many short runs (one per line of type)  -> nruns large
#       - figure page = few long/sparse runs (a drawing spans rows) -> nruns small
#   * page is a figure when 0.002 <= dark_ratio <= 0.11 AND nruns <= 16
#     AND short_runs <= 18
#   * pick the FIRST page of the LONGEST contiguous run of figure pages
#     (US drawings lead, CN 說明書附圖 trail — this rule fits both)
#
# Rendering uses PyMuPDF (fitz) when available (fully poppler-free — also solves
# the Windows MISSING_DEPENDENCY complaint); otherwise it degrades to
# pdftoppm + Pillow (still solves the no-text-layer failure without a new hard
# dependency, since Pillow/numpy are already present). The classifier itself is
# engine-agnostic: it consumes a grayscale numpy array.
# ---------------------------------------------------------------------------

_PROJ_DPI = 90
_DARK_THRESH = 128          # 8-bit gray < this counts as "ink"
_ROW_INK_FRAC = 0.004       # a row is "inked" if >0.4% of its pixels are ink
_FIG_DARK_LO = 0.002
_FIG_DARK_HI = 0.11
_FIG_MAX_RUNS = 16
_FIG_MAX_SHORT_RUNS = 18


def _have_fitz() -> bool:
    try:
        import fitz  # noqa: F401
        return True
    except Exception:
        return False


def _have_pillow() -> bool:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def _gray_pages_fitz(pdf_path: str, dpi: int = _PROJ_DPI):
    """Yield (page_index_1based, grayscale numpy array) via PyMuPDF."""
    import fitz
    import numpy as np
    doc = fitz.open(pdf_path)
    try:
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i in range(doc.page_count):
            pix = doc.load_page(i).get_pixmap(matrix=mat, colorspace=fitz.csGRAY,
                                              alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height,
                                                                     pix.width)
            yield i + 1, arr
    finally:
        doc.close()


def _gray_pages_poppler(pdf_path: str, pages: int, dpi: int = _PROJ_DPI):
    """Yield (page_index_1based, grayscale numpy array) via pdftoppm + Pillow."""
    import numpy as np
    from PIL import Image
    for p in range(1, pages + 1):
        with tempfile.TemporaryDirectory() as td:
            prefix = os.path.join(td, "pg")
            try:
                subprocess.run(
                    ["pdftoppm", "-gray", "-r", str(dpi), "-f", str(p), "-l",
                     str(p), "-png", pdf_path, prefix],
                    capture_output=True, text=True, timeout=120, check=True,
                )
            except Exception:
                continue
            png = next((os.path.join(td, fn) for fn in sorted(os.listdir(td))
                        if fn.endswith(".png")), None)
            if png is None:
                continue
            with Image.open(png) as im:
                arr = __import__("numpy").asarray(im.convert("L"))
            yield p, arr


def _page_metrics(arr) -> dict:
    """Row-projection metrics for one grayscale page array."""
    import numpy as np
    h, w = arr.shape[:2]
    ink = arr < _DARK_THRESH
    dark_ratio = float(ink.mean()) if h and w else 0.0
    row_ink = ink.mean(axis=1)                       # ink fraction per row
    inked = row_ink > _ROW_INK_FRAC
    # contiguous runs of inked rows
    runs = []
    run_len = 0
    for v in inked:
        if v:
            run_len += 1
        elif run_len:
            runs.append(run_len)
            run_len = 0
    if run_len:
        runs.append(run_len)
    nruns = len(runs)
    short_runs = sum(1 for r in runs if r <= max(2, int(h * 0.02)))
    return {"dark_ratio": dark_ratio, "nruns": nruns, "short_runs": short_runs}


def _is_figure(m: dict) -> bool:
    return (_FIG_DARK_LO <= m["dark_ratio"] <= _FIG_DARK_HI
            and m["nruns"] <= _FIG_MAX_RUNS
            and m["short_runs"] <= _FIG_MAX_SHORT_RUNS)


def _pick_page_by_projection(pdf_path: str, pages_hint: int = 0) -> dict:
    """Image-only figure-page locator. Returns {page, method, pages, engine} —
    page is None when no figure page is found or no render engine is usable."""
    use_fitz = _have_fitz()
    if not use_fitz and not _have_pillow():
        return {"page": None, "method": "image_projection_no_engine",
                "pages": pages_hint, "engine": "none"}
    engine = "fitz" if use_fitz else "poppler+pillow"
    if use_fitz:
        pager = _gray_pages_fitz(pdf_path)
    else:
        pgs = pages_hint or _pdf_page_count(pdf_path)
        pager = _gray_pages_poppler(pdf_path, pgs)

    fig_flags = {}   # 1-based page -> bool is_figure
    total = 0
    try:
        for pno, arr in pager:
            total = max(total, pno)
            try:
                fig_flags[pno] = _is_figure(_page_metrics(arr))
            except Exception:
                fig_flags[pno] = False
    except Exception:
        return {"page": None, "method": "image_projection_render_failed",
                "pages": pages_hint, "engine": engine}

    if not fig_flags:
        return {"page": None, "method": "image_projection_render_failed",
                "pages": pages_hint or total, "engine": engine}

    # longest contiguous run of figure pages; take its first page.
    best_start, best_len = None, 0
    cur_start, cur_len = None, 0
    for p in range(1, total + 1):
        if fig_flags.get(p):
            if cur_start is None:
                cur_start, cur_len = p, 0
            cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_start, cur_len = None, 0

    if best_start is None:
        return {"page": None, "method": "image_projection_no_figure_page",
                "pages": total, "engine": engine}
    return {"page": best_start, "method": "image_projection",
            "pages": total, "engine": engine}


def _crop_render_png(pdf_path: str, page: int, dpi: int = 200,
                     trim_header: bool = False):
    """Render a page to PNG, auto-cropping surrounding whitespace to the content
    bounding box. Prefers fitz; falls back to poppler render + Pillow crop.
    trim_header strips a top header band first (BR_20260712 軍A)."""
    # Try fitz first (poppler-free).
    if _have_fitz():
        try:
            import fitz
            import numpy as np
            from PIL import Image
            doc = fitz.open(pdf_path)
            try:
                zoom = dpi / 72.0
                pix = doc.load_page(page - 1).get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom), alpha=False)
                mode = "RGB" if pix.n >= 3 else "L"
                im = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            finally:
                doc.close()
            return _autocrop_to_png(im, trim_header=trim_header)
        except Exception:
            pass
    # Fallback: poppler render, Pillow crop.
    raw = _render_page_png(pdf_path, page, dpi=dpi)
    if raw is None:
        return None
    if not _have_pillow():
        return raw  # can't crop, but a full-page PNG is still a valid figure
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            return _autocrop_to_png(im.copy(), trim_header=trim_header)
    except Exception:
        return raw


def _trim_header_band(im):
    """BR_20260712 軍A:裁掉專利頁頂的帶狀標題文字（「说明书附图 / 图1 /
    Sheet N of M / Patent Application Publication / 公開號行」）。

    純像素列投影（免 OCR，與 dual-engine 一致）:頁頂若有一小段密集墨水列
    （帶狀文字）接著一段明顯空白間隙，就把那段帶狀裁掉。保守:只在
    帶狀位於頁面頂部 <18% 且其下有 ≥ 帶狀高度的空白間隙時才裁，避免誤削圖面。
    回傳裁切後的 im（或原 im 若未偵到帶狀）。
    """
    import numpy as np
    try:
        gray = np.asarray(im.convert("L"))
    except Exception:
        return im
    h = gray.shape[0]
    if h < 40:
        return im
    # 每列墨水比（<200 算深墨，避開淡灰圖線誤判）。
    row_ink = (gray < 200).mean(axis=1)
    ink_rows = row_ink > 0.008          # 視為「有文字/墨水」的列
    # 只看頂部 25% 區域找帶狀。
    top_zone = int(h * 0.25)
    # 頂部第一段連續墨水列 = 候選帶狀。
    r = 0
    while r < top_zone and not ink_rows[r]:
        r += 1
    if r >= top_zone:
        return im                        # 頂部全空，無帶狀
    band_start = r
    while r < h and ink_rows[r]:
        r += 1
    band_end = r                         # 帶狀下緣
    band_h = band_end - band_start
    # 帶狀必須落在頂部且不能太高（>18% 頁高就不像題帶，可能是圖）。
    if band_end > h * 0.18 or band_h < 3:
        return im
    # 帶狀下方的空白間隙:需 ≥ band_h（確保帶狀與主圖分離）。
    g = band_end
    while g < h and not ink_rows[g]:
        g += 1
    gap = g - band_end
    if gap < max(band_h, int(h * 0.01)):
        return im                        # 無明顯間隙，不確定是帶狀，不裁
    # 裁掉帶狀 + 其下間隙，保留主圖。
    return im.crop((0, g, gray.shape[1], h))


def _autocrop_to_png(im, trim_header: bool = False) -> bytes:
    """Trim whitespace to the content bbox and return PNG bytes. When
    trim_header is set, first strip a top header band (BR_20260712 軍A)."""
    import io
    import numpy as np
    from PIL import Image
    if trim_header:
        im = _trim_header_band(im)
    gray = np.asarray(im.convert("L"))
    ink = gray < 250
    if ink.any():
        rows = np.where(ink.any(axis=1))[0]
        cols = np.where(ink.any(axis=0))[0]
        pad = 8
        r0 = max(0, int(rows[0]) - pad)
        r1 = min(gray.shape[0], int(rows[-1]) + pad)
        c0 = max(0, int(cols[0]) - pad)
        c1 = min(gray.shape[1], int(cols[-1]) + pad)
        im = im.crop((c0, r0, c1, r1))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


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
    p.add_argument("--trim-header", dest="trim_header",
                   action="store_true", default=True,
                   help="strip a top header band (说明书附图 / Sheet N of M / "
                        "Patent Application Publication / 公開號行) from the "
                        "rendered figure (BR_20260712 軍A; default on).")
    p.add_argument("--no-trim-header", dest="trim_header",
                   action="store_false",
                   help="disable header-band trimming (keep the full rendered page).")
    args = p.parse_args(argv)

    # BR_20260715 #04: poppler is NO LONGER a hard gate. The text-layer locator
    # needs it, but the image-projection fallback runs on fitz (poppler-free) or
    # pdftoppm+Pillow. Only fail MISSING_DEPENDENCY when NEITHER path can work.
    have_poppler = _poppler_available()
    have_fitz = _have_fitz()
    if not have_poppler and not have_fitz:
        missing = [b for b in _POPPLER_BINS if shutil.which(b) is None]
        raise ScriptError(
            "MISSING_DEPENDENCY",
            "no usable render engine: PyMuPDF (fitz) not importable and poppler "
            f"binaries not found: {', '.join(missing)}",
            missing=missing,
            hint="pip install pymupdf  (or install poppler-utils on the host)")

    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"pdf not found: {pdf_path}")

    # Tier 1: text-layer locator (most accurate WHEN a text layer exists).
    # Requires poppler CLIs; skip cleanly when they're absent.
    loc = (_locate_figure_page(str(pdf_path)) if have_poppler
           else {"page": None, "method": "text_layer_skipped_no_poppler",
                 "pages": 0})

    # Tier 2 (BR_20260715 #04): image-projection fallback. Triggered whenever the
    # text-layer locator found nothing (no text layer / scanned PDF / no FIG.1).
    if loc["page"] is None:
        proj = _pick_page_by_projection(str(pdf_path), pages_hint=loc.get("pages", 0))
        if proj["page"] is not None:
            loc = proj

    if loc["page"] is None:
        img_count = _pdf_image_count(str(pdf_path)) if have_poppler else -1
        if img_count != 0:
            raise ScriptError(
                "NO_FIGURE_PAGE_BUT_IMAGES_PRESENT",
                "could not locate a representative figure page by text layer OR "
                "image projection",
                image_count=img_count, pages=loc["pages"], method=loc["method"],
            )
        raise ScriptError("NO_FIGURE_PAGE",
                          "could not locate a representative figure page",
                          pages=loc["pages"], method=loc["method"])

    # Render: image-projection hits get an auto-cropped render (fitz or
    # poppler+Pillow); text-layer hits keep the original full-page poppler render.
    if loc["method"] == "image_projection":
        png = _crop_render_png(str(pdf_path), loc["page"], dpi=args.dpi,
                               trim_header=args.trim_header)
    else:
        png = _render_page_png(str(pdf_path), loc["page"], dpi=args.dpi)
    if png is None:
        raise ScriptError("RENDER_FAILED", f"failed to render page {loc['page']}")

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
