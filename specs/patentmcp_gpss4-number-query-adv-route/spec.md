# Spec: patentmcp_gpss4-number-query-adv-route

## Purpose

GPSS4 登入模式的號碼查詢對已命中申請號抽不到公開/公告號（folder 標記清單路徑不
render 專利號）。本 spec 保證：所有登入模式 number-query 的號碼→專利號解析改走
adv_search 路徑（唯一 render 專利號的檢視），並以 per-login-session 粒度確保 DB
scope 就緒；同時以 process 內 login gate 硬化「禁並發、禁雙登入」，杜絕帳號節流鎖定。

## Requirements

### Requirement: number-query 走 adv_search 路徑解析專利號

系統 SHALL 令所有登入模式 number-query 進入點的號碼→專利號解析改走 adv_search
路徑（`_submit_query` + `_enter_dual_view` + parse），該路徑 render 專利號欄位；
folder 標記清單路徑降為 fallback 或移除。

#### Scenario: known-item 申請號解析

- **WHEN** 對 known-item `TW202223848`（@AN）走 adv 路徑查詢
- **THEN** 回傳非 None 的公開/公告號（folder 路徑此案 unmatched，adv 路徑 resolved）

### Requirement: per-login-session DB scope 前置閘

系統 SHALL 於每個 login session 首次 number-query 前，依國別/軸推導並設定 DB scope
（TW→TWA+TWB / CN→CNA+CNB / US→USA+USB），同 session 內復用不重設；設定失敗即
fail-fast raise，絕不用可能錯的現有 scope 續查。

#### Scenario: 同 session 第二次查詢復用 scope

- **WHEN** 同一 login session 已設 TWA+TWB，第二筆 TW 申請號查詢
- **THEN** 不重複呼叫 set_search_databases（per-session 復用，DD-4）

### Requirement: 登入模式互斥 gate

系統 SHALL 維護 process 內全局 login gate；任何觸發 web 登入的登入模式入口進場前
必須取得 gate，拿不到即 fail-fast raise（帶現持有者資訊），不排隊、不重試、不開第二
session。GPSS REST API 路徑不受此 gate 限制。

#### Scenario: 並發登入嘗試被擋

- **WHEN** gate 已被某登入模式 tool 持有，第二個登入模式 tool 嘗試進場
- **THEN** raise `GPSS4LoginBusyError`（帶持有者），不排隊不重試

## Acceptance Checks

- [ ] known-item `TW202223848` 走 adv 路徑抽得到公開公告號（live roundtrip）
- [ ] 同 session 多筆查詢僅設一次 scope（per-session 復用可觀測）
- [ ] gate 被持有時第二 acquire fail-fast raise，不排隊
- [ ] `gpss4_resolve_appnos` 對 pending_tw_99 resolved 率從 0 回升（live batch）
- [ ] CN/US 各一筆 number-query 驗跨國通用
