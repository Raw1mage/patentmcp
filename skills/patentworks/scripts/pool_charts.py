#!/usr/bin/env python3
"""pool_charts.py — R13 landing plane: render the 6 pool-analysis charts locally.

Deterministic given a records JSON (already fetched by the container's
patentmcp_analyze_pool metadata half → pool_fetch). Ports the matplotlib
chart-rendering half of patentmcp_analyze_pool: country pie, years trend, top-10
CPC, top-10 assignees, CPC-group categories, and a pure-matplotlib word cloud.

DEPENDENCY: matplotlib (+ pandas). Missing → typed MISSING_DEPENDENCY, exit 2.

Input records JSON: {"records": [...]} or a bare list. Each record may carry:
  pub, country, year, assignee, cpc (list), cpc_group, title, abstract, claim1.

Usage:
  python3 pool_charts.py --in records.json --out-dir charts/

All errors print a single-line typed JSON envelope + nonzero exit; no traceback
reaches stdout (R13.6).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


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


def _load_records(in_path: Path) -> list:
    if not in_path.is_file():
        raise ScriptError("INPUT_NOT_FOUND", f"input file not found: {in_path}")
    try:
        raw = json.loads(in_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScriptError("BAD_JSON", f"could not parse --in as JSON: {e}")
    if isinstance(raw, dict):
        recs = raw.get("records")
        if recs is None:
            raise ScriptError("BAD_INPUT", "records JSON object has no 'records' key")
        return list(recs)
    if isinstance(raw, list):
        return list(raw)
    raise ScriptError("BAD_INPUT", f"expected object or list, got {type(raw).__name__}")


def _render(records: list, out_dir: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    # normalize records to the shape the chart code expects
    norm = []
    for r in records:
        cpc = r.get("cpc", [])
        if isinstance(cpc, str):
            cpc = [c.strip() for c in re.split(r"[;,]", cpc) if c.strip()]
        norm.append({
            "pub": r.get("pub") or r.get("pubno") or "",
            "country": r.get("country") or "Unknown",
            "year": str(r.get("year") or "Unknown"),
            "assignee": r.get("assignee") or "Unknown",
            "cpc": cpc if isinstance(cpc, list) else [],
            "cpc_group": r.get("cpc_group") or (cpc[0][:4] if cpc else "Unknown"),
            "title": r.get("title") or "",
            "abstract": r.get("abstract") or "",
            "claim1": r.get("claim1") or "",
        })
    df = pd.DataFrame(norm)
    out_dir.mkdir(parents=True, exist_ok=True)

    colors = ["#004b87", "#0072ce", "#4192d9", "#7dbdf6", "#bce2f8", "#d9f0fc"]
    plt.rcParams.update({
        'figure.facecolor': 'white', 'axes.facecolor': 'white',
        'text.color': '#333333', 'axes.labelcolor': '#333333',
        'xtick.color': '#333333', 'ytick.color': '#333333', 'font.size': 10,
    })
    charts = {}

    def save_chart(fig, filename):
        path = out_dir / filename
        fig.savefig(str(path), format="png", bbox_inches="tight", dpi=150)
        plt.close(fig)
        charts[filename.replace(".png", "")] = str(path)

    # Chart 1: Country
    fig, ax = plt.subplots(figsize=(6, 5))
    cc = df["country"].value_counts()
    ax.pie(cc, labels=cc.index, autopct='%1.1f%%', colors=colors[:len(cc)])
    ax.set_title("Patent Distribution by Country/Jurisdiction")
    save_chart(fig, "country_distribution.png")

    # Chart 2: Years trend
    fig, ax = plt.subplots(figsize=(7, 4.5))
    year_df = df[df["year"] != "Unknown"]
    if not year_df.empty:
        yc = year_df["year"].value_counts().sort_index()
        ax.plot(yc.index, yc.values, marker='o', color="#0072ce", linewidth=2.5)
        ax.fill_between(yc.index, yc.values, color="#bce2f8", alpha=0.4)
        ax.set_title("Patent Filing/Publication Trend Over Years")
        ax.set_xlabel("Year"); ax.set_ylabel("Patent Count")
        import matplotlib.pyplot as _plt2
        _plt2.xticks(rotation=45)
    else:
        ax.text(0.5, 0.5, "No Year Data Available", ha='center', va='center')
    save_chart(fig, "years_trend.png")

    # Chart 3: Top 10 CPC
    fig, ax = plt.subplots(figsize=(7, 5))
    all_cpcs = [c for lst in df["cpc"] for c in lst]
    if all_cpcs:
        pd.Series(all_cpcs).value_counts().head(10).plot(kind="barh", ax=ax, color="#4192d9").invert_yaxis()
        ax.set_title("Top 10 CPC Technical Classifications"); ax.set_xlabel("Frequency")
    else:
        ax.text(0.5, 0.5, "No CPC Data Available", ha='center', va='center')
    save_chart(fig, "cpc_distribution.png")

    # Chart 4: Top 10 Assignees
    fig, ax = plt.subplots(figsize=(7, 5))
    acnt = df[df["assignee"] != "Unknown"]["assignee"].value_counts().head(10)
    if not acnt.empty:
        acnt.plot(kind="barh", ax=ax, color="#0072ce").invert_yaxis()
        ax.set_title("Top 10 Patent Assignees / Owners"); ax.set_xlabel("Patent Count")
    else:
        ax.text(0.5, 0.5, "No Assignee Data Available", ha='center', va='center')
    save_chart(fig, "assignee_distribution.png")

    # Chart 5: CPC group categories
    fig, ax = plt.subplots(figsize=(6, 5))
    cat = df[df["cpc_group"] != "Unknown"]["cpc_group"].value_counts()
    if not cat.empty:
        ax.pie(cat, labels=cat.index, autopct='%1.1f%%', colors=colors[:len(cat)])
        ax.set_title("Technical Categories Distribution (CPC Group)")
    else:
        ax.text(0.5, 0.5, "No Category Data Available", ha='center', va='center')
    save_chart(fig, "category_distribution.png")

    # Chart 6: word cloud (pure matplotlib spiral placement)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.axis("off")
    stopwords = {"system", "device", "method", "apparatus", "plurality", "comprising",
                 "comprises", "associated", "herein", "having", "first", "second", "one",
                 "invention", "patents", "patent", "disclosed", "discloses", "disclosure",
                 "data", "information", "user", "plural", "methods", "devices", "systems",
                 "一種", "方法", "裝置", "系統", "複數", "包含", "設有", "包括", "提供", "根據",
                 "本發明", "申請", "實施", "公開", "技術", "主要", "特徵", "進行", "其係", "該當",
                 "以及", "藉由", "本實施例", "具有", "第一", "第二", "步驟", "單元", "訊號", "模組",
                 "控制", "處理", "接收", "發送"}
    text_pool = ""
    for _, row in df.iterrows():
        text_pool += f" {row['title']} {row['abstract']} {row['claim1']}"
    words = []
    words.extend([w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', text_pool)
                  if w.lower() not in stopwords])
    words.extend([w for w in re.findall(r'[\u4e00-\u9fa5]{2,4}', text_pool) if w not in stopwords])
    word_counts = Counter(words).most_common(50)
    if word_counts:
        max_freq = word_counts[0][1]
        boxes = []
        hsl_colors = ["#004b87", "#0072ce", "#4192d9", "#2a7ebb", "#58a4d8", "#005a9c"]
        for idx, (word, freq) in enumerate(word_counts):
            fontsize = int(12 + 28 * (math.log(freq) / math.log(max_freq) if max_freq > 1 else 1))
            theta = 0.0; a = 0.005; placed = False
            is_zh = any('\u4e00' <= ch <= '\u9fa5' for ch in word)
            width = len(word) * fontsize * (0.0055 if is_zh else 0.0032)
            height = fontsize * 0.014
            for _ in range(800):
                r = a * theta
                x = 0.5 + r * math.cos(theta); y = 0.5 + r * math.sin(theta)
                box = (x - width/2, y - height/2, x + width/2, y + height/2)
                if box[0] < 0.05 or box[2] > 0.95 or box[1] < 0.05 or box[3] > 0.95:
                    theta += 0.05; continue
                overlap = any(not (box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3]) for b in boxes)
                if not overlap:
                    ax.text(x, y, word, fontsize=fontsize, color=hsl_colors[idx % len(hsl_colors)],
                            ha='center', va='center', weight='bold')
                    boxes.append(box); placed = True; break
                theta += 0.08
            if not placed:
                ax.text(0.1 + (idx * 0.05) % 0.8, 0.05 + (idx * 0.07) % 0.9, word,
                        fontsize=fontsize//2, color="#7dbdf6", ha='center', va='center')
        ax.set_title("Patent Pool Key Technical Features Word Cloud", fontsize=12, pad=20)
    else:
        ax.text(0.5, 0.5, "No Text Data Available for Word Cloud", ha='center', va='center')
    save_chart(fig, "wordcloud.png")

    return charts


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="pool_charts.py",
        description="Render the 6 pool-analysis charts locally (R13 landing plane).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--in", dest="in_path", required=True, help="input records JSON")
    p.add_argument("--out-dir", dest="out_dir", required=True, help="output directory for PNGs")
    p.add_argument("--repo", default=None, help="repo root (unused; landing-plane convention)")
    args = p.parse_args(argv)

    try:
        import matplotlib  # noqa: F401
        import pandas  # noqa: F401
    except ImportError as e:
        raise ScriptError("MISSING_DEPENDENCY",
                          f"chart rendering needs matplotlib + pandas: {e}",
                          hint="pip install matplotlib pandas")

    records = _load_records(Path(args.in_path))
    charts = _render(records, Path(args.out_dir))
    sys.stdout.write(json.dumps({"success": True, "charts": charts, "rows": len(records)},
                                ensure_ascii=False) + "\n")
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
