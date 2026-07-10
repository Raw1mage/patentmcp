# BR: patent_search EPO 分支不吃布林 keyword（熱補丁待固化）

- 日期：2026-07-10
- 類型：bug report（已熱補丁，待正式歸檔 + 測試）
- 元件：`search_dispatcher.py` `_run_epo` / `_keyword_to_cql`
- 提出脈絡：AIOT 非接觸異常偵測 EPO v2 建池

## 問題

`patent_search` 走 EPO 分支時，把整串 keyword（如 `"radar AND fall"`）
直接塞進 CQL 的 `txt="radar AND fall"` 當**單一片語**。EPO OPS CQL 語義下，
`txt="radar AND fall"` = 找「radar AND fall」這個**字串**（片語比對），
而非布林 `radar` AND `fall`。後果：布林檢索全掛，total 虛高（單詞 `radar`
回 3831，本該布林收斂）。

實證：修前 EPO 布林 query 拿不到收斂結果；修後 total 從單詞 3831 收斂到
布林 2285，首屏真居家案密度大升。

## 根因

`_run_epo`（原 line 490-492）未區分「keyword 內的布林運算子空格」與
「片語內的字面空格」，把 boolean 表達式整串當 phrase 傳給 CQL `txt=`。

## 已做的熱補丁（待正式化）

新增 `_keyword_to_cql()` helper（`search_dispatcher.py:484-522`）：把
keyword 布林串轉譯成 CQL——`radar AND fall` → `txt=radar and txt=fall`，
`"millimeter wave"` 引號片語保留為單一 `txt="millimeter wave"`。`_run_epo`
（line 532）已改呼叫它。已 `py_compile` + `webctl.sh restart` 驗證生效。

## 待補（本 BR 未完成部分）

1. **無單元測試**：`_keyword_to_cql()` 的布林/片語/巢狀括號 case 沒有測試覆蓋，
   換人改動易回歸。應補 test：`radar AND fall` / `"millimeter wave" OR radar`
   / `(radar OR lidar) AND fall` / `radar NOT vehicle` 各驗 CQL 輸出。
2. **括號/NOT 支援未驗證**：目前實作對巢狀括號與 NOT 的轉譯正確性未系統驗證。
3. **文件缺**：EPO 分支「吃布林 keyword」這個能力沒寫進 patentworks KB 的
   來源梯 EPO 條目，換執行者不知道可用。

## 驗收

- `_keyword_to_cql()` 有測試覆蓋布林/片語/括號/NOT 四類 case。
- KB 來源梯 EPO 條目補註「patent_search EPO 分支支援布林 keyword」。

---

## 結案記錄 2026-07-10(plan `patentmcp_bulk-entry-unification`)

- **測試覆蓋**:`tests/test_keyword_to_cql.py` 鎖定四類 case(布林/引號片語/括號/NOT)逐字斷言 + 空字串/純片語 edge;實測 `_keyword_to_cql` 現行為全數符合 spec,未需修函式。
- **KB 補註**:SKILL.md §5 EPO 條目已補「patent_search EPO 分支與 patent_bulk(source=epo) 支援布林 keyword(經 _keyword_to_cql 轉譯)」。
- 全套件 175 passed。

Status: **Resolved**
