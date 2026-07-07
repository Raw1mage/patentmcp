# Spec: patentmcp_classification-bulk-export

## Purpose

提供一條與 relevance search 明確區隔的「分類軸窮盡批次匯出」保證:給定一個分類軸(IPC/CPC/USPC),系統 SHALL 透過 GPSS 原生 `expQty`/`expSkip` 能力自動分頁拉取該軸下的完整書目(強制全欄 `expFld`),官方 miss 即真 0 而不退爬蟲,並落地為完整 row 進 patentdb。

## Requirements

### Requirement: 純分類軸批次匯出

系統 SHALL 接受至少一個分類軸(`ipc`/`cpc`/`uspc`)為主查詢條件,且 SHALL NOT 把 `keyword` 作為 AND 收窄疊加在分類軸上;`num` SHALL 可指定至硬上限(如 5000),透過 `expSkip` 自動分頁累積至 `num` 或該軸窮盡。

#### Scenario: 大 num 拉整軸

- **WHEN** 呼叫 `patent_bulk_export(ipc="G16H40/67", databases=["CN"], num=2000)`
- **THEN** 系統自動分頁(expSkip 游標)累積至 2000 筆或軸窮盡,回傳 records 皆含 `expFld` 全欄(TI/PA/AB/CS/CL 非空率接近 100%)

#### Scenario: keyword 不收窄

- **WHEN** 呼叫時同時給 `ipc` 與 `keyword`
- **THEN** keyword 不被組為 AND condition 疊在 ipc 上(不因過度收窄導致官方 0 命中)

### Requirement: 官方 miss 不退爬蟲(no-fallback)

當 GPSS 對指定分類軸回 0 筆時,系統 SHALL 回結構化真 0(`records=[]` + `provenance` reason=zero_hits),且 SHALL NOT fallback 到 gpatents 爬蟲尾級或回 `SCRAPING_REQUIRED`。

#### Scenario: 分類軸真 0

- **WHEN** GPSS 回 0 筆
- **THEN** 回 `records=[]` + provenance 標 miss,不觸發 SCRAPING_REQUIRED、不呼叫 gpatents

#### Scenario: GPSS 未 configured

- **WHEN** `GPSS_USER_CODE` 未設
- **THEN** 回明確錯誤(未 configured),不 fallback 其他來源

### Requirement: 完整 row 落地 patentdb

系統 SHALL 強制 `expFld=PN,ID,TI,IN,PA,AB,CS,CL`(呼叫端不可縮欄),正規化為 records → CSV → `patentdb_import_csv`,經 `put()` COALESCE-only upsert 入庫,SHALL NOT 破壞既有非空欄位。

#### Scenario: 半殘 row 回補

- **WHEN** patentdb 既有 `title_en` 空白 row,以批次匯出重抓對應軸 import_csv
- **THEN** COALESCE 補上 title_en,既有其他非空欄位不被覆寫

## Acceptance Checks

- [ ] `patent_bulk_export(ipc=..., num=2000)` 一次回數百～數千筆含標題完整書目,title 非空率接近 100%
- [ ] GPSS 回 0 → records=[] + provenance zero_hits,不觸發 SCRAPING_REQUIRED
- [ ] 呼叫端無法縮 expFld(強制全欄)
- [ ] 分頁迴圈:多頁累積、末頁回空停止、達 num 上限停止(單元測試斷言)
- [ ] `patent_search` 內部可複用同一分頁函式(DD-1 共用)
- [ ] `GET /tools` 確認 `patent_bulk_export` 註冊 + schema 正確
