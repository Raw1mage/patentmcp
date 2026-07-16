# Tasks: patentmcp_gpss-web-boolean-search

## 1. 探偵補完 (建工具前最後未知數)

- [x] 1.1 探明 `ttsserv_watch` AJAX 筆數輪詢真實 payload/回應格式：端點 `ttsserv_watch?<kmtmp>/km.swp:102:1:全部:`、kmtmp 源自結果頁 ptmp、回應 `transferULLI` 解析 `subdbname(rec)` 各庫命中數
- [x] 1.2 探明日期語法 `ID=YYYYMMDD:YYYYMMDD` 併入單一檢索式後 gpss3 正確限縮 (實測 query_applied `((heartbeat)@TI) and ID=20200101:20231231` gpss3 接受並執行)
- [~] 1.3 `patDB` 國別限縮：實測回應仍含全 24 庫,patDB 未真正限縮國別 (次要精度問題,不阻核心功能;記入 issue 待探網頁路徑國別選取機制)

## 2. 語法驗證 helper (A1)

- [x] 2.1 `_gpss_web_validate_expr`：欄位代碼白名單 `_GPSS_WEB_FIELD_CODES` (TI/AB/CL/AX/IV/ID/IPC/CPC…) + `@欄位`後綴 + 括號配對
- [x] 2.2 非法 → `INVALID_PARAMS` 明細,零網路呼叫 (TV-3/TV-4 單元測試通過)

## 3. 核心工具實作 (A2-A5)

- [x] 3.1 `_gpss_web_search_impl` handshake：複用 `_gpss_client` + `_GPSS_POLICY.guard` + `_gpss_extract_info` + `_gpss_extract_action` (實測 handshake ok=true)；INFO 失敗 → `GPSS_WEB_HANDSHAKE_FAILED`
- [x] 3.2 組單一檢索式 (併 `ID=`日期) 塞 `_21_1_T` + `patDB` → POST (實測 POST ok=true,gpss3 接受單一欄位化布林式)
- [x] 3.3 輪詢 `ttsserv_watch` 取各庫精確命中數 (實測 rounds=1 解析 24 庫命中數)；逾時 → `GPSS_WEB_POLL_TIMEOUT` 回部分就緒
- [x] 3.4 母數判斷 >30萬 → `GPSS_WEB_RESULT_TOO_BROAD` (防呆修正：頁面 furniture reclock/close_nodup 不誤觸,真訊號=哨兵+無 ptmp)
- [x] 3.5 ≤30萬：複用 `_gpss_iter_result_rows` 解析結果列書目,組 envelope 回傳 (實測 records 解析 pubno_core/doc_type/harder_path)

## 4. MCP 工具註冊

- [x] 4.1 註冊 `@mcp.tool() gpss_web_search`,參數契約 (expr/date_from/date_to/databases/num) 對齊 data-schema.json

## 5. 測試 + 驗證

- [x] 5.1 語法驗證單元測試 (TV-1~5 + 回歸測試全過,零網路呼叫)
- [x] 5.2 檢索流程測試 (實測單一欄位化括號布林式 POST 成功 + 回結果,非語法錯)
- [x] 5.3 限縮測試 (日期範圍正確併入 query_applied;國別 patDB 見 1.3)
- [~] 5.4 大母數 fail-fast：真訊號路徑靠純函式測試覆蓋 (TB 哨兵+無ptmp=True);真實 >30萬 未去重上限難構造,以防呆修正+單測替代
- [x] 5.5 節流：全程 `async with _GPSS_POLICY.guard()` 序列化 (含輪詢走 `_gpss_scrape_pace`,不並行)
- [x] 5.6 零 API 額度：全路徑走 `_gpss_client` 網頁 handshake,不呼叫 `gpss_client.search` REST (實測 provenance 僅 handshake/post/poll)

## 6. 收尾同步

- [x] 6.1 SKILL.md line 218 GPSS 網頁語法條目更新:已落成 `gpss_web_search` 工具 (取代「僅 KB 沉澱不改 code」),含成本定位 + patDB 已知限制
- [x] 6.2 architecture.md 補 GPSS3 網頁路徑布林檢索計數條目 (t7 AJAX/防呆修正/fail-fast 天條)
- [x] 6.3 event log 收尾記錄 (verified) + tasks.md 全勾 + issue_20260716 記 patDB 限制
