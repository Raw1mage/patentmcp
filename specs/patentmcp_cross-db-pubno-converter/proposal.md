# Proposal: patentmcp_cross-db-pubno-converter

## Why

同一件專利在不同資料源需要**不同的號碼格式**（patentdb PK / GPSS REST / GPSS4 web @PN·@AN / EPO OPS docdb），
但目前沒有單一權威 converter。號碼格式邏輯**散落在至少 5 處**，各查詢點臨場處理，導致兩類系統性損害：

1. **假 miss / 假 not_found 反覆發生**：查詢用了某 DB 不接受的格式 → 回空 → 被誤判「資料真的沒有」。
   （近例：EPO US pre-grant 序號 10↔11 位單形式 404 → 誤判「EPO 對 A1 全 miss」；kind-strip key 對帳騙局
   造成 CN「4,432 pending」大半假缺口。）
2. **消費端被迫盲試格式變體燒 token**：每碰到查不到就派實驗試 3-4 種格式變體 —— 系統性浪費，
   應由 converter layer 一次把 mapping 坐實。

根本問題不是任一模組的 bug，而是**「號碼格式知識沒有 SSOT」這條架構契約從未建立**。每次散點修復
（`docdb_variants`、`normalize_pubno` US 前綴、TW @AN 軸別路由）都只補了一個症狀點，格式邏輯繼續分裂。

## Original Requirement Wording (Baseline)

- BR_20260719：「建立單一 converter layer 模組（建議 `patent_mcp_server/pubno_convert.py`）作為跨 DB
  號碼格式 SSOT，覆蓋 {CN, US, TW} × {pubno 公開/公告號, appno 申請號} × {老號, 新號, 帶/不帶 kind code}。」

## Requirement Revision History

- 2026-07-19: initial draft created via plan-init.ts
- 2026-07-19: 落點策略經使用者確認 —— 純函式模組 + 雙側共用（src 正典，patentdb_local 以 vendor 同步保留 R13.6）；
  驗證用純函式單元測試 + 少量實查 roundtrip 抽樣。

## Effective Requirement Description

1. 建立 `src/patent_mcp_server/pubno_convert.py` 作為跨 DB 號碼格式 **唯一真實來源**，
   提供 4 個 `to_<db>` 目標函式：
   - `to_patentdb_key(raw)` → patentdb PK（= 現 `canonical_pubno`，kind-strip aware）
   - `to_gpss_rest(raw)` → GPSS REST `pub_number`（完整 pubno）
   - `to_gpss4_web(raw, axis)` → GPSS4 web @PN/@AN（去國碼原始數字；axis=pub/apply，能從號形推斷）
   - `to_epo_variants(raw)` → EPO OPS docdb（= 現 `docdb_variants`，含 US 10↔11 雙變體）
2. **variants-first**：任何 DB 對某號型有多種可能接受格式時，回 variants list（主形式在前），查詢端逐個 fallback。
3. **每條 mapping 附實測依據**：模組 docstring / mapping 知識表記錄「此格式對此 DB 實測命中」的證據。
4. **收斂 5 處散點**：現有格式邏輯全部改呼叫本 layer。
5. **kind-strip 對帳一致**：CN/TW 對帳需能明確產出原始 key 與 stripped key 兩者。

## Scope

### IN
- 新建 `src/patent_mcp_server/pubno_convert.py`（純函式，僅依賴 stdlib `re`）。
- `skills/patentworks/scripts/patentdb_local.py` 以 **vendor 同步**方式複製 canonical 邏輯（保留 R13.6 no-import-from-src 契約）。
- 收斂散點（改呼叫 converter，刪除重複格式邏輯）：
  1. `src/patent_mcp_server/epo/client.py`（`to_docdb` / `docdb_variants`）
  2. `src/patent_mcp_server/patentdb_store.py`（`normalize_pubno` / `canonical_pubno`）
  3. `src/patent_mcp_server/patents.py`（`_get_patent_country_and_normalized_no`；TW @AN 軸別推斷）
  4. `scripts/family_backfill_offline.py`（簡化版 `to_docdb`，退化無 US 變體）
  5. `skills/patentworks/scripts/patentdb_local.py`（vendored `normalize_pubno` / `canonical_pubno` 副本）
- 純函式 pytest 全覆蓋（號形維度矩陣）。
- 少量實查 roundtrip 抽樣：EPO US pre-grant ×1、TW @AN 老號/新號 ×各1（用 §2.1 已坐實案例）。

### OUT
- **不**重查 TW 137 假 not_found（那是消費端前案檢索案的後續，非本 converter layer 職責；converter 落地後由該案自行重查）。
- **不**改動 GPSS4 web 抓取 / session / login 邏輯（軸別路由用既有 axis 參數，僅新增號形→軸別推斷 helper）。
- **不**改 patentdb schema / PK 語義（`canonical_pubno` 必須向後相容，既有 key 生成不變）。
- **不**新增任何 fallback mechanism（variants-first 是**顯式** fallback list，查詢端逐個試，非 silent fallback）。

## Non-Goals

- 不做號碼「驗證合法性」的校驗器（converter 是格式轉換，非 validator）。
- 不建 converter 的 MCP 工具介面（純內部 library，供 src 各查詢點 import）。

## Constraints

- **R13.6 no-import-from-src**：`patentdb_local.py` 是 host-side landing plane，刻意不 import src/。
  converter 的 canonical 真實來源在 src；host 側以 vendor 複製 + 同步註記維持，不打破該契約。
- **向後相容硬閘**：`canonical_pubno(x)` 對所有既有輸入的輸出必須逐字不變（回歸測試把關）。
- **額度**：實查 roundtrip 抽樣須挑 GPSS4 下班時段、EPO OPS 週額度內；EPO US 變體驗證只查 §2.1 已坐實的單一案例。
- **XDG scratch**：任何 roundtrip 實查的中間產物落 `$XDG_RUNTIME_DIR`，不落 /tmp、不落網路掛載工作區。

## What Changes

- 新增一個純函式 converter 模組；5 處散點的格式邏輯改為呼叫它並刪除本地重複實作。
- 號碼格式知識從「散落在各查詢點的隱性慣例」升格為「模組 docstring + mapping 知識表的顯式契約」。

## Capabilities

### New Capabilities
- `pubno_convert.to_patentdb_key / to_gpss_rest / to_gpss4_web / to_epo_variants`：跨 DB 號碼格式 SSOT。
- 號形→軸別推斷（`TW\d{9}` 民國年 = 申請號 → @AN），杜絕「申請號誤走公告號軸」。

### Modified Capabilities
- `epo.client.to_docdb / docdb_variants`：改為 converter 的 thin re-export（或直接刪除，呼叫端改 import converter）。
- `patentdb_store.canonical_pubno`：改委派 converter，行為向後相容。

## Impact

- 影響 code：epo/client.py、patentdb_store.py、patents.py、scripts/family_backfill_offline.py、
  skills/patentworks/scripts/patentdb_local.py。
- 影響 BR：BR_20260719 收編臨時補丁 `docdb_variants` → 升格 `to_epo_variants`。
- 無 API/schema break；無 operator 動作。
