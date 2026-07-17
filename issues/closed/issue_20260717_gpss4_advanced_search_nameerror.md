# BR: gpss4_advanced_search crashes with `name 'GPSS4DbScopeError' is not defined`

## Symptom
`gpss4_advanced_search(query="PN=(122316744 OR ...)", max_pages=1)` → server-side
`NameError: name 'GPSS4DbScopeError' is not defined`。
帶不帶 `databases` 參數、有無先 `gpss4_set_search_scope`（成功，persist=true）皆同樣 crash。

## Expected
應執行進階檢索或回 typed error（如 scope 未設）。NameError 代表例外類別未 import/未定義，
是 error-path 上的 latent bug：任何走到該 raise/except 的呼叫都會炸。

## Repro (2026-07-17)
1. `gpss4_set_search_scope(databases=["CNA","CNB"])` → ok
2. `gpss4_advanced_search(query="PN=(122316744 OR 122310336 OR 122313132 OR 122313384)", max_pages=1)` → NameError

## Note
同 session `gpss4_folder_search` 正常（read-only 路徑不受影響）。
另觀察：`gpss_web_search` 對單一 PN 查詢回 records=[] 且 totals 與前次不同查詢完全相同
（grand_total=948 恆定），疑似回收到 session 快取結果而非本次查詢——可一併查。

---

## Resolution（2026-07-17，fixed）

**Root cause**：`gpss4_advanced_search` 工具（`patents.py:5314`）的 function-local import
只帶 `harvest, GPSS4AdvSearchError`，**漏 import `GPSS4DbScopeError`**。當底層
`harvest()` 走到 db-scope 失敗路徑 raise `GPSS4DbScopeError`（`adv_search.py:389` 定義）時，
`patents.py:5345` 的 `except GPSS4DbScopeError` 引用了 function scope 內未 import 的名字 →
`NameError: name 'GPSS4DbScopeError' is not defined`。姊妹工具 `gpss4_set_search_scope`
（`patents.py:5419-5422`）正確 import 了三個名字，故那條路徑正常——正解釋 BR 觀察到的
「`gpss4_folder_search` 正常、只有進階檢索炸」。

**因果鏈**：BR_20260716 db-scope 新增 code 時，`gpss4_advanced_search` 的 except 子句
引用了 `GPSS4DbScopeError` 但 local import 漏補 → error-path latent regression（任何走到
該 db-scope 失敗分支的呼叫都會炸，遮蔽本應回傳的 typed `GPSS4_DBSCOPE_FAILED`）。

**契約恢復**：owning spec `specs/patentmcp_gpss-web-login-db-scope` tasks §3.1——
「庫範圍設定失敗 → typed `GPSS4_DBSCOPE_FAILED`，一律不靜默降級、不崩潰」。修復讓該
except 能正常成立、回傳 typed error 而非 NameError。

**Fix**：`patents.py:5314-5316` 把 function-local import 補成
`harvest, GPSS4AdvSearchError, GPSS4DbScopeError`。打擊半徑零（補一個名字）。

**Validation**：`python3 -c ast.parse` 通過；AST 掃描確認 `gpss4_advanced_search` 的
local import-from `patent_mcp_server.gpss4.adv_search` 已含全部三名。

**Orthogonal（不在本 BR scope）**：Note 段的 `gpss_web_search` 單 PN 回快取 totals 恆定，
屬 gpss3 totals 解析缺陷，已由 `issue_20260716_gpss_web_search_totals_missing_main_count_line`
（open）追蹤，不併入本修。
