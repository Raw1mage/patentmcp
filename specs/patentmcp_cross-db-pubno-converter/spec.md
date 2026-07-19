# Spec: patentmcp_cross-db-pubno-converter

## Purpose

提供跨資料源專利號碼格式轉換的唯一真實來源（SSOT）。給定任意來源格式的 pubno/appno 字串，
本模組保證產出目標 DB（patentdb PK / GPSS REST / GPSS4 web / EPO OPS docdb）所接受的號碼形式；
歧義時回顯式 variants 陣列（主形式在前）供呼叫端逐個 fallback，杜絕「單形式查空 → 誤判 miss」。

## Requirements

### Requirement: 跨 DB 格式投影 SSOT

系統 SHALL 提供 `to_patentdb_key` / `to_gpss_rest` / `to_gpss4_web` / `to_epo_variants` 四個純函式，
覆蓋 {CN, US, TW} × {pubno, appno} × {帶/不帶 kind}，且為所有查詢點唯一的格式轉換入口。

#### Scenario: US pre-grant 位數變體

- **WHEN** 呼叫 `to_epo_variants("US20230053201A1")`
- **THEN** 回傳 `["US.20230053201.A1", "US.2023053201.A1"]`（10↔11 位雙變體，主形式在前）

#### Scenario: TW 申請號號形推斷軸別

- **WHEN** 呼叫 `to_gpss4_web("TW109112770", axis=None)`
- **THEN** 回傳 `("109112770", "apply")`（`TW\d{9}` 民國年號形 → @AN 軸，杜絕誤走 @PN）

### Requirement: canonical_pubno 向後相容

系統 SHALL 保證 `to_patentdb_key` 對所有既有輸入的輸出，與收斂前的 `canonical_pubno` 逐字相同。

#### Scenario: 外國碼不誤掛 US 前綴

- **WHEN** 呼叫 `to_patentdb_key("KR20260067039A")`
- **THEN** 回傳 `KR20260067039`（不產生 `USKR...` 雙前綴；DD-31 回歸）

### Requirement: variants-first 顯式 fallback（無 silent fallback）

系統 SHALL 在號形無法明確解析時回空 list 或 raise，呼叫端 fail fast；SHALL NOT silent fallback 到猜測號。

#### Scenario: 無法解析時 fail fast

- **WHEN** converter 收到無法對映任何國碼/號形的字串
- **THEN** 回空 list（variants 函式）或 raise，呼叫端可見此失敗，絕不回傳猜測號

## Acceptance Checks

- [ ] `pubno_convert.py` 四函式覆蓋 CN/US/TW × pubno/appno，純函式僅依賴 stdlib `re`
- [ ] mapping 知識表每條附實測依據（docstring 或 design.md）
- [ ] EPO US pre-grant、TW @AN 老號/新號至少各一 roundtrip 實查命中
- [ ] 5 處散點改走本 layer，無重複格式邏輯
- [ ] `canonical_pubno` 對既有 patentdb key 抽樣輸出逐字不變
- [ ] vendor-drift guard：src 與 patentdb_local 的 canonical 函式體逐字相同
