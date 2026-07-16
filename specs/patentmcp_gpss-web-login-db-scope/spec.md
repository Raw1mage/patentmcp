# Spec: patentmcp_gpss-web-login-db-scope

## Purpose

保證 gpss 零 API 額度的 web 檢索路徑（`gpss_web_search` / `gpss4_advanced_search`）對大陸公開/公告（CNA/CNB）取得與 REST 端 `databases=["CNA","CNB"]` 一致的命中覆蓋——透過走登入 session + 檢索前設定 session 庫範圍 state 納入 CN，取代無效的 `patDB` POST 欄位假設（supersede DD-2）。

## Requirements

### Requirement: web 路徑 CN 庫覆蓋

系統 SHALL 使 web 檢索路徑的庫範圍涵蓋 `databases` 參數指定的所有庫（含 CNA/CNB），並在未指定時預設含 CN（`DB_DEFAULT`=US+CN）。庫範圍 SHALL 透過登入 session 的檢索庫範圍 state 設定，而非 `patDB` POST 欄位（該欄位在網頁表單不存在、被伺服器忽略）。

#### Scenario: 同軸 CN 檢索式回非零大陸命中

- **WHEN** 呼叫 `gpss_web_search` 送出一個在 REST 端 `databases=["CNA","CNB"]` 撈到 N（>0）筆的同軸檢索式
- **THEN** 回傳的 `totals` 大陸公開/公告命中數為非零，量級與 REST 對齊（非 0/空 records）

### Requirement: fail-fast 無 fallback

系統 SHALL 在登入失敗回 `GPSS_WEB_LOGIN_FAILED`、庫範圍設定失敗回 `GPSS_WEB_DBSCOPE_FAILED`，且 SHALL NOT 靜默降級到匿名 session 或 REST 路徑（使用者天條）。

#### Scenario: 登入失敗不靜默降級

- **WHEN** GPSS4 member 登入失敗
- **THEN** 回 `GPSS_WEB_LOGIN_FAILED` 顯式錯誤，不回匿名 session 的（不含 CN）結果

## Acceptance Checks

- [ ] `gpss_web_search` 同軸 CN 式子回非零大陸命中（對齊 REST 量級）
- [ ] 登入/設庫失敗回對應 typed error，無 silent fallback
- [ ] 非 CN 軸（TW/US）檢索行為不退化；`databases` 限縮正確
