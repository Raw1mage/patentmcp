# Spec: patentmcp_gpss-web-boolean-search

## Purpose

提供一個走 GPSS 人類登入路徑 (gpss3 網頁爬蟲) 的布林檢索計數能力：接受單一欄位化括號布林檢索式，回傳各資料庫精確命中數與結果列書目，零 API 額度消耗。保證 (1) 檢索式語法在網路呼叫前驗證，(2) 大母數 (>30萬) fail-fast 而非回無意義巨量，(3) 所有請求序列化走 Cloudflare 節流政策。

## Requirements

### Requirement: 單一檢索式承載欄位/布林/日期限縮

系統 SHALL 接受一個單一字串檢索式，其中欄位限定 (`@TI`/`@AB`/`@CL`)、跨欄位布林 (`(A)@TI not (B)@AB`)、日期範圍 (`ID=YYYYMMDD:YYYYMMDD`) 全部編碼在字串內，塞入 gpss3 的 `_21_1_T` 通用文字檢索欄位；國別/資料庫經 `patDB` POST 參數獨立指定。

#### Scenario: 欄位化括號布林式檢索

- **WHEN** 呼叫 `gpss_web_search("(radar or mmwave)@TI not (vehicle)@AB")`
- **THEN** 系統走 gpss3 handshake、POST 該檢索式、回各資料庫精確命中數 + 結果列書目

#### Scenario: 日期 + 國別限縮

- **WHEN** 呼叫 `gpss_web_search("(heartbeat)@TI", date_from="20200101", date_to="20231231", databases=["TWA","CNA"])`
- **THEN** 檢索式併入 `ID=20200101:20231231`、`patDB=TWA,CNA`，只回該日期該庫的命中

### Requirement: 大母數 fail-fast 不救

系統 SHALL 在總命中觸及 GPSS 模糊上限 (>30萬) 時回結構化錯誤 `GPSS_WEB_RESULT_TOO_BROAD` + 限縮提示，不嘗試分頁窮舉、不回巨量無意義結果。

#### Scenario: 母數過大

- **WHEN** 檢索式過寬導致結果頁標示「超過30萬筆」
- **THEN** 回 `{error_code: "GPSS_WEB_RESULT_TOO_BROAD", hint: "加日期/國別/收窄布林"}`，不回 records

### Requirement: 語法驗證前置 + 零額度

系統 SHALL 在任何網路呼叫前驗證檢索式語法 (欄位代碼白名單、`@欄位`後綴、括號配對、日期語法)；非法即 `INVALID_PARAMS` 零 handshake。系統 SHALL NOT 呼叫 `gpss_api` REST 端點 (不燒 quota)。

#### Scenario: 非法欄位代碼

- **WHEN** 檢索式含未知欄位代碼 `(x)@ZZ`
- **THEN** 回 `INVALID_PARAMS` 明細，未發任何 gpss3 請求

## Acceptance Checks

- [ ] 單一欄位化括號布林式能 POST 進 gpss3 並回結果 (非語法錯)
- [ ] 日期範圍 + 國別限縮正確併入檢索
- [ ] 總命中 >30萬 回 `GPSS_WEB_RESULT_TOO_BROAD`，不回 records
- [ ] 非法語法 `INVALID_PARAMS` 零網路呼叫
- [ ] 所有請求序列化走 `_GPSS_POLICY` (不並行觸發 Cloudflare Challenge)
- [ ] 不呼叫 `gpss_api` REST (零 API 額度)
