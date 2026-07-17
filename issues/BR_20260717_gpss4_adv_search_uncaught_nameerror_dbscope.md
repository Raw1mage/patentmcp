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
