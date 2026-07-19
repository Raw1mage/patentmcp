"""pubno_convert.py — 跨 DB 專利號碼格式轉換 SSOT (single source of truth).

BR_20260719: 同一件專利在不同資料源需要不同號碼格式，格式邏輯過去散落 ≥5 處
(epo/client.to_docdb、patentdb_store.canonical_pubno、patents._get_patent_country_
and_normalized_no、family_backfill_offline.to_docdb、patentdb_local vendored copy)。
本模組收斂為單一純函式 layer；各查詢點一律改呼叫本層，不再各自臨場處理格式。

設計約束（見 plans/patentmcp_cross-db-pubno-converter/design.md）:
- **純函式，僅依賴 stdlib `re`**（DD-1）：確保可被 src 內模組與 host-side landing
  plane（skills/patentworks/scripts/patentdb_local.py，R13.6 no-import-from-src）以
  vendor 複製方式共用。若本檔的 normalize_pubno/canonical_pubno 函式體改動，
  patentdb_local.py 的 vendored 副本必須同步（pytest vendor-drift guard 把關）。
- **variants-first，非 silent fallback**（DD-2）：歧義號型回 list（主形式在前），
  呼叫端逐個顯式 fallback；無法解析回空 list / None，**絕不猜測號**。
- **canonical_pubno 向後相容**（DD-3）：to_patentdb_key 對所有既有輸入逐字等同
  收斂前的 canonical_pubno。

═══════════════════════════════════════════════════════════════════════════════
Mapping 知識表（每條附實測依據；BR §2.1/§2.3 已坐實）
═══════════════════════════════════════════════════════════════════════════════
| 維度                        | 函式                    | 輸出                         | 實測依據
|-----------------------------|-------------------------|------------------------------|------------------------
| CN pubno CN119230141A       | to_patentdb_key         | CN119230141 (剝 kind)        | patentdb key 慣例;§2.4 騙局1
| CN 對帳                     | patentdb_key_variants   | [CN119230141, CN119230141A]  | §2.4 騙局1: CN 4432 假缺口
| US grant US11213256B2       | to_patentdb_key         | US11213256B2 (留數字 kind)   | normalize_pubno 現行
| US pre-grant US20230053201A1| to_epo_variants         | [US.20230053201.A1,          | §2.3+騙局3;EPO 序號 10↔11 位
|                             |                         |  US.2023053201.A1]           |  event_20260719_epo-docdb-format-bug
| TW appno TW109112770        | to_gpss4_web(raw, None) | ("109112770", "apply")       | §2.1 實測 hits=2 → TW202138759A
| TW appno TW113141212        | to_gpss4_web(raw, None) | ("113141212", "apply")       | §2.1 實測 hits=1 → TW202619683A
| TW appno TW112107009        | to_gpss4_web(raw, None) | ("112107009", "apply")       | §2.1 實測 hits=2 → TW202435176A
| TW pubno 公告 TW578729U     | to_patentdb_key         | TW578729 (剝 kind);TWM/TWI/  | §2.5;gpss4 patno.py TW[IMD]
|                             |                         | TWD 憑證段保留               |
| 任意 → GPSS REST            | to_gpss_rest            | 完整 pubno (含 kind)         | GPSS REST pub_number 接受完整
═══════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ISO-3166 alpha-2 country codes appearing as publication-number prefixes in this
# project's multi-jurisdiction pool. A pubno ALWAYS starts with its own 2-letter
# country code; a prior parser recognised only TW/US/EP/WO/CN and silently
# defaulted everything else to "US", then prefixed "US" onto an already-complete
# foreign pubno (KR20260067039A -> USKR20260067039A), minting double-prefix
# numbers existing in no patent office (RCA DD-31, 2026-07-14).
_KNOWN_CC = (
    "TW", "US", "EP", "WO", "CN", "KR", "JP", "CA", "AU", "DE", "GB",
    "FR", "ES", "FI", "PL", "MX", "IT", "NL", "SE", "CH", "AT", "BE",
    "DK", "NO", "RU", "IN", "BR", "SG", "IL", "HK", "MO", "CZ", "GR", "TR",
)


# ─────────────────────────────────────────────────────────────────────────────
# A1: 正規化解析 (raw → country, normalized_no)  —— canonical, 向後相容硬閘
# ─────────────────────────────────────────────────────────────────────────────

def normalize_pubno(publication_number: str) -> Tuple[str, str]:
    """Split a raw pubno into (country, normalized_no).

    country = 2-letter ISO code stripped from the prefix (full _KNOWN_CC set);
    normalized_no = number body with separators, country code, and trailing kind
    code removed. CN/TW/other trailing kind is stripped; a US numeric-style kind
    (B2/A1) survives because the trailing-letter strip only removes ONE optional
    letter suffix, not the digit-letter grant kind — see canonical_pubno note.

    向後相容硬閘（DD-3）：對所有既有輸入的輸出必須逐字等同收斂前的
    patentdb_store.normalize_pubno。
    """
    pat = re.sub(r"[\s/\-,\.]+", "", publication_number or "").upper()
    country = "US"
    matched_cc = False
    for cc in _KNOWN_CC:
        if pat.startswith(cc):
            country, pat, matched_cc = cc, pat[len(cc):], True
            break
    if not matched_cc and re.match(r"^[IMD]\d+", pat):
        country = "TW"
    elif not matched_cc and re.match(r"^\d{9}$", pat):
        country = "TW"
    m_cert = re.match(r"^([IMD]\d+)[A-Za-z]*$", pat)
    if m_cert:
        pat = m_cert.group(1)
    else:
        m_app = re.match(r"^(\d+)[A-Za-z]*$", pat)
        if m_app:
            pat = m_app.group(1)
    return country, pat


# ─────────────────────────────────────────────────────────────────────────────
# A2: 號碼形態判別 (TW appno vs 已公開識別號) —— resolve_appnos 入口分流
# ─────────────────────────────────────────────────────────────────────────────

def tw_number_kind(raw: str) -> str:
    """判別 TW 號碼形態,供 resolve_appnos 入口 fail-fast 分流 (BR_20260719 缺陷A)。

    回傳:
    - 'apply'      : 民國年申請號 (TW + 3位民國年 + 6位流水,如 TW109112770)。
                     民國年 3 位數落 1xx/09x/0xx (民 100+/9x/早期),即百位 < 西元千位。
    - 'identifier' : 已是對外公開/公告號 (識別號最終形態),不應投入 appno→pubno 解析:
                       * 西元年公開號 TW20xx/TW19xx (9位,前綴 19|20,如 TW200644333)
                       * 憑證號 TWI/TWM/TWD + 數字 (如 TWI684433 / TWM578729)
                       * 帶 kind 尾碼的公告號 (如 TW578729U/TWI684433B)
    - 'unknown'    : 無法判別號形 (非 TW、位數不符),交呼叫端既有路徑處理,不猜。

    設計約束沿用本模組 DD-1 (純函式 re-only) / DD-2 (不猜號,無法判別回 unknown)。
    判別依 SSOT: 西元年公開號 TW\\d{9} 且前綴 19|20 = 已公開識別號 (BR §缺陷A 坐實
    TW200644333/TW201021598/… 8 件全 TW20xx 被誤入 apply 軸拖垮整批)。
    """
    up = re.sub(r"[\s/\-,\.]+", "", raw or "").upper()
    if not up.startswith("TW"):
        return "unknown"
    body = up[2:]
    # 憑證號: TW[IMD] + 數字 (± kind 尾碼) = 已核准公告識別號
    if re.match(r"^[IMD]\d+[A-Z]*$", body):
        return "identifier"
    # 純 9 位數字: 西元年 (19|20 前綴) = 公開號; 否則民國年申請號
    if re.match(r"^\d{9}$", body):
        return "identifier" if body[:2] in ("19", "20") else "apply"
    # 帶 kind 尾碼的數字號 (如 578729U) = 已公告識別號
    if re.match(r"^\d+[A-Z]+$", body):
        return "identifier"
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# to_<db> 目標函式
# ─────────────────────────────────────────────────────────────────────────────

def to_patentdb_key(raw: str) -> str:
    """patentdb PK: country + normalized_no (= 現 canonical_pubno).

    CN/TW 剝尾端 kind、US 保留數字型 kind (B2/A1)。向後相容硬閘（DD-3）。
    """
    country, norm = normalize_pubno(raw)
    return f"{country}{norm}"


def patentdb_key_variants(raw: str) -> List[str]:
    """對帳雙 key: [stripped_key, original_with_kind]（stripped 在前）。

    §2.4 騙局1：patentdb canonical key 剝 CN/TW 尾端 kind（庫 key=CN119230141
    非 CN119230141A）。對帳若只用原始帶 kind pubno 查庫 → 查不到 → 誤判假缺口
    （CN 4432 pending 大半假缺口的根因）。呼叫端同時查兩 key 即可杜絕。

    stripped == original 時（US 保留 kind、無 kind 號）回單元素 list，不製造重複。
    """
    stripped = to_patentdb_key(raw)
    original = re.sub(r"[\s/\-,\.]+", "", raw or "").upper()
    if original == stripped:
        return [stripped]
    return [stripped, original]


def to_gpss_rest(raw: str) -> str:
    """GPSS REST `pub_number`: 完整 pubno（含 kind，去分隔符大寫化）。

    GPSS REST 接受完整 pubno（§2.3）；不剝 kind、不拆軸別。
    """
    return re.sub(r"[\s/\-,\.]+", "", raw or "").upper()


def to_gpss4_web(raw: str, axis: Optional[str] = None) -> Tuple[str, str]:
    """GPSS4 web 號碼搜尋: (number_str, axis)。

    number = 去國碼原始數字（TW 去 'TW' 前綴）；axis ∈ {'pub' (@PN), 'apply' (@AN)}。

    軸別（DD-4，§2.4 TW 軸別錯位）:
    - 顯式 axis in {'pub','apply'} → 直接用。
    - axis=None → 從號形推斷: `TW\\d{9}`（民國年 3+6，如 TW109112770）= 申請號
      → 'apply'(@AN)；否則預設 'pub'(@PN)。杜絕「TW 申請號誤走 @PN 公告號軸 →
      假 miss → 掉爬蟲」(event_20260718_ppubs_tw_quota_bugfixes Bug 2)。

    number 去前綴後 lstrip('0') 對齊 gpss4_resolve_appnos 的 _norm/GPSS4Folder
    既有慣例（§2.1 實測三變體皆命中，raw 9 位可直接查）。
    """
    if axis is not None and axis not in ("pub", "apply"):
        raise ValueError(f"axis must be 'pub'|'apply'|None, got {axis!r}")
    up = re.sub(r"[\s/\-,\.]+", "", raw or "").upper()
    inferred_axis = axis
    if inferred_axis is None:
        inferred_axis = "apply" if re.match(r"^TW\d{9}$", up) else "pub"
    # strip country code (only the 2-letter CC prefix; keep TW cert letters I/M/D
    # off the number-search string — GPSS4 number field takes the raw digits).
    number = up
    for cc in _KNOWN_CC:
        if number.startswith(cc):
            number = number[len(cc):]
            break
    # for @PN pub numbers, drop trailing kind letters; keep digit body
    m = re.match(r"^([IMD]?\d+)", number)
    if m:
        number = m.group(1)
    return number, inferred_axis


def to_docdb(raw: str) -> Optional[str]:
    """EPO OPS docdb primary form 'CC.NUMBER[.KIND]'.

    kind code is OPTIONAL: many pool pubnos (CN121811579, TW202238300, EP42)
    carry no kind suffix. OPS accepts docdb 'CC.NUMBER' without a kind for family
    lookup, so a missing kind must NOT fail the parse (else CN+TW — ~83% of the
    backfill target set — silently drops out).

    e.g. US11213256B2 / US-11213256-B2 -> US.11213256.B2; TW-I684433-B -> TW.I684433.B
    """
    p = re.sub(r"[\s\-]", "", raw or "").upper()
    m = re.match(r"^([A-Z]{2})([0-9A-Z]+?)([A-Z][0-9]?)?$", p)
    if not m:
        return None
    cc, num, kind = m.group(1), m.group(2), m.group(3)
    return f"{cc}.{num}.{kind}" if kind else f"{cc}.{num}"


def to_epo_variants(raw: str) -> List[str]:
    """All plausible EPO docdb forms, primary first (BR §6 docdb_variants 升格).

    US publication numbers carry TWO independent serial-format ambiguities at the
    EPO docdb boundary; a single-form lookup yields false misses (~format bug, not
    true EPO gaps), so query every plausible form:

    1. **pre-grant** (USYYYYNNNNNNNkind): EPO stores the serial sometimes
       zero-stripped to 6 digits (US.2023053201.A1) and sometimes kept at 7 digits
       (US.20230053201.A1) — varies by year/batch. §2.3 + 騙局3 +
       event_20260719_epo-docdb-format-bug.
    2. **grant / old-A** (US09997041B2 / US06150941A): the plain serial itself can
       carry LEADING ZERO(s); EPO stores the un-padded serial. A leading-zero form
       404s, the stripped form hits (前導零是唯一變因,命中/miss 完全對翻). §2.4-晚
       實測坐實: US09997041B2→404 / US9997041B2→found; US06150941A→404 /
       US6150941A→found. Same-family漏網 as the pre-grant 10↔11 fix (A1 修了、
       grant/old-A 當時漏掉,BR_20260719 reopened 補上)。

    # UNVERIFIED — needs roundtrip: 其他國別的 docdb 序號位數變體（若有）未實測，
    # 不憑推測擴充；目前僅對 US pre-grant 10↔11 位 + US grant/old-A 前導零有坐實依據。
    """
    primary = to_docdb(raw)
    if not primary:
        return []
    out = [primary]
    parts = primary.split(".")
    cc, num = parts[0], parts[1]
    kind = parts[2] if len(parts) > 2 else None
    if cc == "US" and num.isdigit():
        alts: List[str] = []
        if len(num) == 11 and num[4] == "0":
            # pre-grant: 4-digit year + 7-digit serial with leading zero -> 6-digit
            alts.append(num[:4] + num[5:])
        elif len(num) == 10:
            # pre-grant: 4-digit year + 6-digit serial -> pad serial back to 7
            alts.append(num[:4] + "0" + num[4:])
        elif num[0] == "0":
            # grant/old-A: plain serial with leading zero(s). Pre-grant years never
            # start with 0, so num[0]=='0' uniquely marks this case. EPO stores the
            # un-padded serial -> add the leading-zero-stripped variant (§2.4-晚).
            stripped = num.lstrip("0")
            if stripped and stripped != num:
                alts.append(stripped)
        for alt in alts:
            out.append(f"{cc}.{alt}.{kind}" if kind else f"{cc}.{alt}")
    return out
