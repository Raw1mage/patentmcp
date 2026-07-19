# Tasks: patentmcp_cross-db-pubno-converter

## 1. Converter 核心模組

- [x] 1.1 新建 `src/patent_mcp_server/pubno_convert.py`：`to_patentdb_key` / `patentdb_key_variants` / `to_gpss_rest` / `to_gpss4_web(raw,axis=None)` / `to_epo_variants`（純函式，僅 stdlib `re`，含 mapping docstring）
- [x] 1.2 `to_patentdb_key` 語義逐字等同現行 `canonical_pubno`（country + normalize_no，CN/TW 剝 kind、US 留數字 kind）
- [x] 1.3 `to_epo_variants` 收編 `epo/client.docdb_variants`（US pre-grant 10↔11 位雙變體，主形式在前）
- [x] 1.4 `to_gpss4_web` 號形→軸別推斷（`TW\d{9}` → apply/@AN；否則 pub/@PN）

## 2. 收斂散點（改呼叫 converter，刪重複邏輯）

- [x] 2.1 `epo/client.py`：`to_docdb`/`docdb_variants` 改為 converter thin re-export（保留既有 import 路徑）
- [x] 2.2 `patentdb_store.py`：`canonical_pubno` 改 `return to_patentdb_key(x)`；`normalize_pubno` 委派 converter
- [x] 2.3 `patents.py`：`_get_patent_country_and_normalized_no` 改委派 converter；TW `TW\d{9}`→@AN 推斷併入 `to_gpss4_web`
- [x] 2.4 `scripts/family_backfill_offline.py`：簡化版 `to_docdb` 改呼叫 converter（取回 US 變體能力）
- [x] 2.5 `skills/patentworks/scripts/patentdb_local.py`：vendor 同步 canonical 邏輯 + 頂部同步註記（保 R13.6 no-import）

## 3. 測試與驗證

- [x] 3.1 純函式 pytest：號形維度矩陣（CN/US/TW × pubno/appno × 帶/不帶 kind）全覆蓋，含 §2.1/§2.3 mapping 表向量
- [x] 3.2 vendor-drift guard 測試：比對 src 與 patentdb_local 的 `normalize_pubno`/`canonical_pubno` 函式體逐字相同
- [x] 3.3 回歸測試：`canonical_pubno` 對既有 patentdb 實 key 抽樣輸出逐字不變（向後相容硬閘）
- [x] 3.4 少量實查 roundtrip 抽樣（2026-07-19 全跑，三案全命中）：TW109112770→`('109112770','apply')`→GPSS4 @AN hits=2；TW113141212→`('113141212','apply')`→GPSS4 @AN hits=1；US20230053201A1→`['US.20230053201.A1','US.2023053201.A1']`→EPO OPS found=true（apply_no US202217819582A）。實查輸出與純函式逐字一致，roundtrip 坐實。TW ×2 零 API 額度，EPO ×1 消耗週額度 1 筆。

## 4. 收尾

- [x] 4.1 更新 BR_20260719 狀態（收編臨時補丁 → 標記 converter 已落地）
- [x] 4.2 event_record 收尾（Scope / Key Decisions / Validation / Remaining）
- [x] 4.3 architecture sync 檢查（號碼格式 SSOT 已入 specs/architecture.md 檢索 dispatcher 邊界後）
