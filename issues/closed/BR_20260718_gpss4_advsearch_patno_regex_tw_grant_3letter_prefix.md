# BR_20260718 — gpss4 adv_search 專利號抽取 regex 對 TW 公告號（3 字母前綴 TWI/TWM/TWD）雙重失效

- **status**: open
- **severity**: high（污染 pool 資料、產生不存在的專利號、且靜默）
- **component**: `src/patent_mcp_server/gpss4/adv_search.py`（主兇）、`src/patent_mcp_server/gpss4/folder.py`（同構）
- **reporter**: orchestrator（異常偵測前案檢索專案 RCA）
- **date**: 2026-07-18
- **related**: BR_20260716（同一行 L87 在 b66b387 加 lookbehind 護欄，只治半個症狀）

## 1. 症狀（外顯）

TW 專利**公告號**在 GPSS 進階檢索結果頁被抽取時，開頭的國碼字母 `T` 被吃掉：

| 正確號碼 | 被抽成 | 種類 |
|---|---|---|
| `TWI930018B` | `WI930018B` | 發明公告號（TWI，I=Invention grant）|
| `TWM683169U` | `WM683169U` | 新型公告號（TWM，M=Model/新型）|

TW **公開號**（`TW201534271A` / `TW202300951A`，`TW` 後直接接數字）**不受影響**，正常。

實害：本專案 pool（`master_pool.csv`）內 **427 筆** TW 號變成 `WI…`/`WM…` 這種**任何專利庫都不存在**的殘號（WI 120 + WM 307）。後續拿殘號去 `patent_search` 補撈 → 三官方源（GPSS/EPO/PPUBS）全 miss → 下游 subagent 誤把「查不到」歸因成「TIPO 不提供舊制 TW 書目」的**假結論**，浪費配額與工時。

## 1.5 History Review（同族回顧）

- **BR_20260716**（closed，b66b387 2026-07-17）：同一行 `_PAT_NO_RE`（L87）曾因無 lookbehind 匹配 mid-token，該 commit 加了 `(?<![A-Z0-9])`。**但該修復只擋住「吃 T」，沒解決根本的「3 字母前綴無法辨識」**——修完變成對 TWI/TWM **完全漏抓**（見 §4 實測）。本 BR 是同一 regex 的**根因未除**復發，不是新缺陷。
- 復發形狀：號碼結構假設（2 字母國碼）與 TW 公告號實際結構（3 字母前綴）不符。根因在**共用的號碼結構假設**，不在任一 call site。

## 2. 重現

```python
import re
# adv_search.py 現有四條抽號 regex，全部對 TW 公告號失效：
_PAT_NO_RE = re.compile(r'(?<![A-Z0-9])([A-Z]{2}\d{6,}(?:[A-Z]\d?)?)')   # L87（護欄版）
_KINDED    = re.compile(r'^[A-Z]{2}\d{6,}[A-Z]\d?$')                      # L287
_APPLYNO   = re.compile(r'^(?:[A-Z]{2}\d{6,}(?:\.\d+)?|\d{7,}(?:\.\d+)?)$')  # L291
_TW_NO_RE  = re.compile(r'\b([A-Z]{2}\d{6,}[A-Z]?\d?)\b')                 # folder.py L48

_PAT_NO_RE.findall("TWI930018B")   # -> []          （應為 ['TWI930018B']）
_KINDED.fullmatch("TWI930018B")    # -> None         （應 match）
_TW_NO_RE.findall("TWI930018B")    # -> []          （應為 ['TWI930018B']）

# 對照——護欄加上前的舊裸版，正是吃 T 兇手：
naked = re.compile(r'([A-Z]{2}\d{6,}(?:[A-Z]\d?)?)')
naked.findall("TWI930018B")        # -> ['WI930018B']  ← 產生 427 筆壞號的兇手
```

## 3. 根因（causal chain）

**根因一句話**：所有抽號 regex 用 `[A-Z]{2}\d{6,}` 假設「2 字母國碼緊接數字」。TW 公告號是 `TW` + kind letter(`I`/`M`/`D`) + 數字，即**國碼後緊接第 3 個字母**，破壞了該假設。

- `TWI930018B`：`[A-Z]{2}` 吃掉 `TW`，接著要 `\d{6,}` 但遇到字母 `I` → 匹配失敗。
  - **無 lookbehind（舊版）**：regex 引擎回溯，從 `W` 起 `WI`+`930018`+`B` 匹配成功 → **吐出 `WI930018B`（吃掉 T）**。
  - **有 lookbehind（現版 L87）**：`(?<![A-Z0-9])` 禁止從 token 中間的 `W` 起匹配 → **完全不匹配，回 `[]`（漏抓）**。
- **兩種行為都錯**：舊版污染資料（吐不存在的號），現版靜默漏號。

**腐化傳播鏈**（本專案實據）：
```
GPSS web 結果頁抽號(舊裸版 regex, 吐 WI930018B)
  → pool_membership_tw_api.jsonl        (pubno="WI930018B" 已壞；同筆 appno="TW114141899" 正常)
  → write_meta.py                        (兩欄並存 src_pubno壞 + norm_pubno對，但選了壞的)
  → pool_membership_tw_v2.jsonl          (pubno 壞號直傳)
  → build_master.py:76-77                (原樣搬運，無辜)
  → master_pool.csv                      (427 筆壞號落地)
```
註：`build_master.py` / `mat.py` / `normalize_pubno`（patentdb_store.py:58）都**無辜**——`normalize_pubno` 對正確輸入 `TWI930018B` 會正確產出 `("TW","930018")`（`^[IMD]\d+` 分支）；問題在 regex 抽號那一刻就已吃 T，正規化拿到的已是壞號。

## 4. 打擊半徑

- **TW 專屬，且只打帶 kind letter 的 grant 公告號 TWI / TWM / TWD**。TW 公開號（`TW`+9 位數字+`A`）不受影響。
- **CN / US / EP / WO 完全不受影響**：CN 是 `CN…A`、US 是 `US…A1/B2`，kind code 在**尾端**，`[A-Z]{2}` 國碼後就是數字，不與國碼混淆。
- 影響全部四條 regex（`adv_search.py` L87/L287/L291 + `folder.py` L48）與所有經由 GPSS web 結果頁 / 資料夾頁抽 TW 公告號的路徑。

## 5. 修復建議

抽號 regex 的國碼段需容納「TW + kind letter」3 字母前綴。驗證通過的替換式：

```python
# 把 [A-Z]{2} 國碼段改為「TW[IMD] 優先，否則一般 2 字母國碼」：
r'(?<![A-Z0-9])((?:TW[IMD]|[A-Z]{2})\d{6,}(?:[A-Z]\d?)?)'
```

實測此式對 `TWI930018B`/`TWM683169U`/`TW201534271A`/`US20230081319A1`/`CN120543023A` **全部正確**。四個 call site（L87/L287/L291 fullmatch 版 + folder.py L48）需同步套用同一國碼段修法。

**迴歸測試向量**（必納入）：

| 輸入 | 期望抽出 |
|---|---|
| `TWI930018B` | `TWI930018B`（發明公告，勿吃 T、勿漏抓）|
| `TWM683169U` | `TWM683169U`（新型公告）|
| `TWD` + 數字 | `TWD…`（設計專利，若 GPSS 會回）|
| `TW201534271A` | `TW201534271A`（公開號不受影響）|
| `US20230081319A1` | `US20230081319A1`（US 尾端 kind code 不受影響）|
| `CN120543023A` | `CN120543023A`（CN 不受影響）|

## 6. 資料修復（本專案側，與工具修復解耦，零配額可行）

- 正解已在手邊：`write_meta.py` 每筆的 `norm_pubno` 欄位、`pool_membership_tw_api_enriched.jsonl` 已含正確 `TWI…/TWM…`。
- 本專案將 `master_pool.csv` 內 `WI…→TWI…`、`WM…→TWM…` 本地回填，**不必重撈 GPSS**。
- 另依專案決策：TWM（新型/機構設計）整批不進分析池、TWI（發明公告）修回保留。此為 pool 定義層決策，與本工具 BR 無關。

## 7. 建議 owner action

1. 套 §5 修法於四條 regex，加 §5 迴歸測試向量。
2. 考慮把「國碼 + 可選 kind-prefix」的號碼結構抽成單一 shared 常數，避免四處各寫一份 `[A-Z]{2}\d{6,}`（同構復發的根源）。
3. 修復後掃 patentdb 總庫是否已有經此路徑落地的 `WI…/WM…` 殘號 PK，一併正規化。
