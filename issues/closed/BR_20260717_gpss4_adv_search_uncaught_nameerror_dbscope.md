# BR: gpss4_advanced_search 未捕獲 NameError(GPSS4DbScopeError)以裸字串冒泡,非結構化錯誤

- 日期：2026-07-17
- 類型：bug report
- 元件：`gpss4_advanced_search`(`patents.py:5245` MCP tool)/ `gpss4/adv_search.py harvest`
- 提出脈絡：AIOT 非接觸異常偵測 POC 座標系失配查證(DD-76),gpss4 登入態欄碼對照

## 症狀

呼叫 `gpss4_advanced_search(query=<含 @IC 欄碼的長式>, max_pages=1, persist_scope=true)`
回：

```
Error executing tool gpss4_advanced_search: name 'GPSS4DbScopeError' is not defined
```

這是**未被工具內 try/except 捕獲的 NameError**,以裸字串冒泡到 MCP transport
(前綴 `Error executing tool`),而非工具契約承諾的結構化
`{success:false, error_code:..., error:...}`。使用者側只拿到一句 Python 例外訊息,
無 error_code、無可辨識的失敗類別。

## 復現條件(窄、額度個位數)

- 該次是本 session **第一個** gpss4 呼叫(尚未跑 `gpss4_set_search_scope`)。
- query 帶非標準分類欄碼 `@IC`(官方 REST 碼是 `IC=`,gpss4 web 慣用 `@CPC`/`@IPC`)。
- `persist_scope=true`(但注意:此參數 default 即 True——**同 default 的後續呼叫
  不帶此參數卻成功**,見下),故 `persist_scope=true` 本身不是充分觸發條件。
- **對照組(成功)**:先跑 `gpss4_set_search_scope(["CNA","CNB"], persist=true)` 建立
  scope 後,再跑 `gpss4_advanced_search(query=..., max_pages=1)`(persist_scope 用 default
  True)→ 正常回結果。故觸發與「首呼叫時 scope 尚未建立、harvest 走到需處理
  databases=None 的分支」相關,非單一參數。

## 根因(嫌疑,未逐行坐實但範圍已收斂)

`gpss4_advanced_search`(`patents.py:5245`)的 try/except(5342-5354)已 import 並捕獲
`GPSS4DbScopeError`(import 在 5314、except 在 5347)。但實測 NameError 仍以**未捕獲**
形式冒泡——代表拋出點在該 try 之外,或在 `harvest`/`set_search_databases` 某條路徑
引用了 `GPSS4DbScopeError` 而該處作用域未綁定該名字(例:巢狀函式、或首呼叫
databases=None 分支走到一段 import 尚未涵蓋的引用)。`harvest`(`gpss4/adv_search.py:770`)
在 `persist_scope=True` + `databases=None` 時於 792 呼叫 `set_search_databases`,後者於
422/429/439/447/486 拋 `GPSS4DbScopeError`——類別本身在 adv_search.py:389 有定義,故
adv_search.py 內不應 NameError。嫌疑指向 `patents.py` 某條 fallback/驗證路徑在 try 外
先引用了該名字。

## 修復方向

1. **首要**:確保 `gpss4_advanced_search` 的**所有**可拋 `GPSS4DbScopeError` 的路徑
   都在 try/except 涵蓋範圍內,或把 import 提到函式頂;任何未預期例外一律以
   `except Exception` 兜成結構化 `{success:false, error_code:"GPSS4_ADV_SEARCH_RUNTIME", ...}`
   (5352 已有此兜底,但本 NameError 冒泡代表拋出點在其保護範圍之外)。
2. **次要(可用性)**:非法/非標準分類欄碼(如 `@IC`)應在入口做欄碼驗證,回
   結構化 `{success:false, error_code:"GPSS4_BAD_FIELD_CODE", hint:"用 @CPC/@IPC"}`,
   而非讓它走到深層才以 NameError 爆掉。

## 影響

- 低頻(需首呼叫 + 特定分支),但**違反工具的 fail-fast 結構化錯誤契約**(天條 §11:
  顯式報錯、保留證據)。裸 NameError 讓呼叫方無法程式化辨識失敗類別。
- 本 POC 查證未受阻(改用 `gpss4_set_search_scope` 先建 scope 即繞過),但記錄在案
  供工具層修正。

---

## Resolution（2026-07-18，fixed — 重複件，已由 issue_20260717 修復）

**現況核對**：`src/patent_mcp_server/patents.py:5322` 的 `gpss4_advanced_search`
function-local import 現已為 `harvest, GPSS4AdvSearchError, GPSS4DbScopeError`（三名字
齊備）；`except GPSS4DbScopeError`（5354）落在該 import 作用域內，NameError 冒泡路徑已消除。

**根因與本 BR §「根因(嫌疑)」一致**：BR_20260716 db-scope 新增 code 時，
`gpss4_advanced_search` 的 except 子句引用 `GPSS4DbScopeError` 但 local import 漏補
→ error-path latent regression。**契約恢復**：owning spec
`specs/patentmcp_gpss-web-login-db-scope` tasks §3.1（庫範圍設定失敗 → typed
`GPSS4_DBSCOPE_FAILED`，不靜默降級不崩潰）。

**重複關係**：本 BR 與 `closed/issue_20260717_gpss4_advanced_search_nameerror.md`
為同一缺陷的兩份回報；後者已含完整 RCA + AST 驗證。本 BR 併入 close，不重複修。

**次要建議（§修復方向 2，非法欄碼 `@IC` 入口驗證）**：屬可用性增補、非契約破裂，
未在本次 scope；如需可另開 issue 追蹤。
