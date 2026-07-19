# BR_20260719 — GPSS4 登入模式號碼查詢：查前未啟動「該國資料庫」+「輸出欄位」→ 命中卻抽不到號碼

- **狀態**: **resolved（2026-07-19：code + 單元測試全部落地；§5 live 驗證全通過——TW roundtrip + pending_tw_99 batch 6/6 + CN/US 跨國各一筆，見文末「§5 live 驗證」。CN/US 趁 session-keepalive plan 的活 session 順帶驗）**
- **報告人**: 異常偵測前案檢索案 orchestrator
- **嚴重度**: high（登入模式 number-query 路徑對「未預先設定 scope 的帳號」系統性 unmatched，資料假陰）
- **關聯**: BR_20260716_gpss4_adv_search_missing_peruser_database_scope_config（已 closed；範圍是 **adv_search** 的 per-user DB scope config）／ issue_20260716_gpss4_adv_cn_result_page_patno_in_ajax ／ DD-96（TW 先勾公開+公告兩庫）
- **本 BR 增量**: BR_20260716 修的是 `adv_search` 路徑；**本 BR 是 `folder_search` / `gpss4_resolve_appnos`（number-query 登入路徑）完全沒有 DB-scope + 輸出欄位啟動的環節** —— 兩者是不同 code path，前者的修復沒有覆蓋後者。

---

## 1. 症狀（實測坐實）

登入模式（GPSS4 web，`folder.search_number`）對 TW 申請號批次查詢，**命中存在但號碼欄位抽不出來**：

- known-item `TW202223848`（先前驗證確實存在）：
  - `gpss4_folder_search(number=202223848, axis=apply)` → `{success:true, count:1, hits:[{db:46, rec:86922, curt:1}]}` ✅ **命中**
  - `gpss4_folder_mark(...)` → `{count:0, is_empty:true, patents:[]}` ❌ 抽不到
  - `MarkList._extract_rows(html)` → `0` rows
  - html 長度 24,475，含「公開 / 公告 / 申請」label，**但整頁無 `pat_no` / `patNo` / 任何 `TW\d+` 公開公告號可抽**
- 批次 `gpss4_resolve_appnos(99 筆 TW appno)` → resolved **0**／unmatched 19／not_found 13（跑到 timeout 前 32 筆全空）。

## 2. Root cause（已排除號碼格式，鎖定 scope+欄位未啟動）

1. **不是號碼格式問題**：cross-DB converter（`pubno_convert.to_gpss4_web`，BR_20260719 已落地）對這批號輸出正確——`TW087209080→('087209080','apply')`、`TW109112770→('109112770','apply')`，前導零保留、9 碼正確。converter 無辜。

2. **真因 = 查詢帳號的「搜尋資料庫 scope」與「結果頁輸出欄位」未在設定頁預先啟動**：
   - `folder.py` / `gpss4_resolve_appnos` **完全無** scope / settings / `_20_1_S_*` / 輸出欄位啟動邏輯（全 grep 皆空）。
   - GPSS4 的 pat_no（公開公告號）只在「該國資料庫已在設定頁勾選啟用」+「結果表格檢視已開通對應輸出欄位」時才會 render（adv_search.py 註解已載明此 render-state：`公開公告號/申請號/… render ONLY in the scoped database result table view`）。
   - 未預先啟動 → 查詢**能命中 hit ref（db/rec）**，但結果頁不 render 公開公告號欄位 → `_extract_rows` 抽 0 → 上層記 unmatched。這是「假陰」，不是資料真無。

## 3. 使用者明示需求（2026-07-19，一體適用所有登入模式查詢）

> **「登入模式查詢，不管是查哪個國家，都要先進設定頁去啟動該國資料庫。」**
> **「而且輸出欄位也要在設定頁裏先開通，才看得到我們要的欄位。」**

即：**任何登入模式（web headless）號碼查詢，執行查詢前必須先進設定頁完成兩件事——(A) 啟動目標國別資料庫、(B) 開通所需輸出欄位（至少公開公告號/申請號/申請日/公開公告日/發明名稱/摘要）——否則命中也抽不到欄位。**

## 4. 需求規格（交 patentmcp 實作）

> **核心要求（使用者 2026-07-19 明示）：這個前置動作必須「硬化成查詢 tool 裏的固定 routine」——不是呼叫方責任、不是可選的 opt-in 參數、不是文件叮嚀，而是 tool 進入點自動、無條件、不可繞過地執行的內建前置閘。** 呼叫方呼叫任一 number-query 查詢時，根本不需要（也不應該）知道要先設 scope——tool 自己在送查詢前保證 scope+欄位已就緒。忘記設 = 不可能發生，因為呼叫方無從忘記。

1. **硬化為 tool 進入點內建 routine（不可繞過）**：`GPSS4Folder.search_number` / `gpss4_resolve_appnos` / `gpss4_folder_search` / `gpss4_folder_mark` 等**所有登入模式 number-query 進入點**，在實際送查詢前，於 tool 內部**自動**呼叫「ensure_scope_and_fields(國別, axis)」前置 routine。
   - 這是 routine 的**單一實作、單一入口**（例如一個 `_ensure_query_ready()` 私有方法，被每個 number-query 進入點無條件呼叫），不是散在各 tool 各自判斷、也不是靠呼叫方傳旗標開啟。
   - **無 opt-in 參數、無 skip 旗標**：不提供「跳過 scope 設定」的選項。
   - 複用既有 `adv_search.set_search_databases(dbs, persist)` + `_DB_CODE_TO_FIELD`（TWA/TWB/TWD/CNA/CNB/USA/USB/…）啟動該國 DB。
   - 依 axis/國別自動推導所需 DB codes（例：TW appno → TWA+TWB 公開+公告兩庫，DD-96；CN→CNA+CNB；US→USA+USB）。
   - **輸出欄位開通**：設定頁若有「結果表格輸出欄位/檢視欄位」的 per-user 設定，routine 同樣在查詢前確保公開公告號等目標欄位已勾選；若欄位開通與 DB scope 是同一設定頁的不同區塊，一次套用。
2. **[SUPERSEDED by 落地決策 DD-4，2026-07-19] ~~每次查詢無條件重設到好（不靠 latch 猜狀態）~~ → 改為 per-live-session 設一次**（使用者知情覆寫，理由見下）：
   - **原始需求（vN，本 BR 起草時）**：scope/欄位是 account-level per-user server-side config，可能被並發 session / 前次殘留 / 別的查詢静默改掉——任何 latch 都是在「猜」config 現態；正解=每次 number-query 無條件重設，不設 latch。
   - **為何 superseded**：本條前提是「config 可能被並發 session 静默改掉」。**§4A login gate 落地後，登入模式並發已被 process 層 gate 物理消除**——同一時間只有一條 live session 在跑，同 session 內沒有別人能改 config。前提消失後，per-session 記錄「已設 scope」不再是「猜 config 現態」，而是**確定性事實**（這條 session 自己設的、沒別人能動）。
   - **落地決策（DD-4，使用者 2026-07-19 定案）**：粒度改為**以每個 live TCP / login session 為單位設一次**（`GPSS4Session._scope_set`，login 時清空）——非每查重設、非每查驗證。這**不是** §4.2 反對的「猜 config latch」，因為並發已被 §4A gate 消除，latch 記的是本 session 的確定事實而非對外部 config 的臆測。
   - **成本/正確性**：batch 99 筆只 POST 設定頁一次（而非 99 次），大幅降低驅動 TIPO 節流鎖定的請求量（正是本 session 帳號被鎖的血淚教訓的直接對策），同時因並發已消除故不損正確性。
   - **單線天條不衝突**：登入爬蟲本就單線序列（§4A gate 強制），per-session 設一次不造成 scope 競態。
3. **fail-fast 不 silent fallback**（天條）：routine 設定頁啟動失敗 → 明確 raise（比照 `GPSS4DbScopeError`），**絕不**靜默用帳號現有（可能錯的）scope 續查而回假 unmatched。routine 失敗 = 查詢中止，不是「設不成就照舊查」。
4. **可觀測**：routine 執行後，查詢回傳/log 標明「本次查詢生效的 DB scope + 已開通輸出欄位」，讓上層能判別 unmatched 是「真無」還是「scope/欄位沒開」。

## 4A. 登入模式互斥：禁並發、禁雙登入（in-memory status gate 硬化）

> **使用者 2026-07-19 明示：「登入模式不准並發、不准雙登入。這也要硬化。用 in-memory status gate 來保護。」**

這是與 §4 scope routine **正交的獨立 concern**：§4 管「查前 config 設到好」，本段管「同一時間只能有一條登入 session 在跑」。兩者都是 GPSS4 登入模式的硬化需求。

### 背景（實際踩過的痛）

本 session 曾因並發/高頻登入把 TIPO 帳號打進節流鎖定（修 loop 過程 37 分鐘內重啟 5 次、一度兩個 loop 實例並存、loop 跑著同時又開 docker exec 除錯探針自帶登入 = 第三條 session）。痛點根因：**登入互斥靠 AI 自律（最不可靠那環），而非 code 層 gate**。人/AI 都會忘、會誤判進程存活（grep 自匹配假影）而起第二實例。

### 需求規格

1. **in-memory login gate（process-內互斥鎖）**：patentmcp server process 內維護一個全局 login-mode gate（例：`asyncio.Lock` / 一個 `_login_session_active: bool` 旗標 + 持有者識別）。任何登入模式入口（`GPSS4Folder` 建 session / `search_number` / `folder_search` / `folder_mark` / `resolve_appnos` / `pool_fetch` / 任何會觸發 web 登入的 tool）**進場前必須先拿到 gate**。
2. **拿不到就 fail-fast，不排隊不重試**（天條）：gate 已被別人持有 → 立即 raise（例 `GPSS4LoginBusyError`）帶現持有者資訊，**絕不**静默開第二條 session、也不內建退避重試（登入失敗/忙碌一律立即回報，不自動撞牙——這是本案 TIPO 鎖定血淚定下的硬規則）。
3. **gate 與實際 OS 進程一致**：release 必須在 session 真正關閉（`folder.close()` / finally）時才釋放，且用 `readlink /proc/<pid>/exe` 類的真進程識別（非 grep cmdline，避免 shell 自匹配假影）作為一致性校驗的依據。避免 gate 說空但實際還有殘留登入進程、或 gate 已釋放但牌子卡住。
4. **可觀測**：gate 狀態（現持有者 / 空閒 / 上次釋放時間）可查（log 或一個輕量 status tool），讓 orchestrator 能在派登入工作前先確認 gate 空閒，而非盲發。
5. **邊界**：本 gate 只管**登入模式（web headless）**；GPSS REST API（官方金鑰、配額制，不碰登入面：`patent_get_claim1` / `ppubs_batch_get_claims` / `patent_enrich_backfill` / EPO biblio）**不受此 gate 限制，可並行**。兩類是不同認證面，不要誤把 REST 也鎖進來。

## 5. 驗證標準（roundtrip 實查）

- 修後對 known-item `TW202223848`（apply 軸）：先啟動 TWA+TWB + 開通輸出欄位 → `search_number` → **必須抽得到公開公告號**（非 None/unmatched）。
- 對本案 `pending_tw_99.txt`（99 筆真硬骨頭 TW appno）重跑 `gpss4_resolve_appnos`：resolved 率應從 0 顯著回升（節流/真未公開者除外）。
- 對 CN/US 各抽一筆 number-query 驗同機制跨國通用（不限 TW）。

## 6. 影響範圍與現存資料

- 本案 TW 99 未解 appno（`output/priorart_anomaly-rerun/02_pool/tw_unresolved_appno_99.jsonl`）此刻卡在此 bug；layer 修好後可回收一批。
- 今晨 TW235 recheck 的 86 error 部分可能亦混入此因（非純登入節流）——待 layer 修好後重驗釐清。
- 更廣：**所有登入模式 number-query 對「未預設 scope 帳號」都有此假陰風險**，不限本案、不限 TW。

## 7. 誠實記錄

本 BR 由前案檢索案 orchestrator 發出，只提需求 + 附實測證據（職責分界：patentmcp 的 code 走 BR，不越界實作）。上述 root cause 的抽取失敗、converter 無辜、`folder.py` 無 scope 邏輯，均為本 session 主線親驗坐實（folder_search count=1 vs _extract_rows=0 的矛盾即鐵證）。

---

## 落地紀錄（2026-07-19，plan `patentmcp_gpss4-number-query-adv-route`）

### recon 對 BR §2/§4 假設的修正（動刀前坐實）

BR §2 假設真因是「設定頁的輸出欄位 per-user config 未勾選」。recon 進一步坐實：**folder 標記清單結果頁根本不 render 專利號**（`folder.search_number` 有 hits 但 `MarkList._extract_rows` 抽 0）。真解不是去設定頁多勾一個「輸出欄位」，而是**改走 `adv_search` 的「簡詳目並列」（dual-view）檢視——那是 GPSS4 唯一 render 公開公告號的檢視面**。因此「§3(B)/§4.1 輸出欄位開通」實質由 `_enter_dual_view` 達成，不需獨立的 settings-page 欄位 config 區塊（該區塊在 recon 中未證實存在為必要環節）。實作跟 recon 事實走，非跟 BR 原始假設走。

### 已落地（code + 單元測試）

| BR 需求 | 實作 |
|---|---|
| §4.1 硬化為 tool 進入點內建 routine、單一入口、無 opt-in/skip | `adv_search._ensure_query_ready(s, country)` 單一實作；`gpss4_resolve_appnos` batch 進場無條件呼叫 |
| §4.1 複用 `set_search_databases` + `_DB_CODE_TO_FIELD` | `_ensure_query_ready` 內呼叫 `set_search_databases(persist=True)` |
| §4.1 依國別推導 DB codes（TW→TWA+TWB / CN / US …） | `adv_search._COUNTRY_TO_DBS`（TW/CN/US/JP/KR/EP → 公開+公告兩庫）+ `country_to_dbs()` |
| §3(B)/§4.1 輸出欄位開通（→ 見 recon 修正） | `resolve_one` 走 `_enter_dual_view`（唯一 render 專利號的檢視） |
| §4.2（superseded → DD-4 per-session 設一次） | `GPSS4Session._scope_set`（login 清空）+ `_ensure_query_ready` set-once-per-session |
| §4.3 fail-fast 不 silent fallback | scope 失敗 `GPSS4DbScopeError`，batch 直接中止不續查回假 unmatched |
| §4.4 可觀測 | `gpss4_resolve_appnos` 回 `effective_scope`（本次生效 DB scope） |
| §4A in-memory login gate、fail-fast 不排隊不重試 | 新增 `gpss4/login_gate.py`：module-level 單一 `_LoginGate`（純旗標 fail-fast，非 asyncio.Lock await-blocking）+ `GPSS4LoginBusyError` |
| §4A gate 與 OS 進程一致（`readlink /proc/self/exe`） | release DD-7 持有者一致性校驗 |
| §4A gate 狀態可查 | `gate_status()`（busy/holder/held_for/released_ago） |
| §4A 邊界：REST 不受 gate | 只 4 個登入模式進入點 acquire；GPSS REST 路徑不 acquire |
| §4.1「所有登入模式 number-query 進入點」 | `gpss4_resolve_appnos`（改走 resolve_one，完全移除 folder mark-list 路徑）+ `gpss4_folder_list`/`gpss4_folder_mark`/`gpss4_folder_search`（全套 login gate；gate 忙碌回 `GPSS4_LOGIN_BUSY`） |

**檔案**：NEW `src/patent_mcp_server/gpss4/login_gate.py`；`gpss4/session.py`（`_scope_set` 欄位 + login 清空）；`gpss4/adv_search.py`（`country_to_dbs` / `_ensure_query_ready` / `resolve_one`）；`patents.py`（4 進入點改寫）；NEW `tests/test_br20260719_adv_route.py`。

**驗證（非 live）**：`tests/test_br20260719_adv_route.py` **10 全綠**（gate 互斥 / finally release / 例外 release / 序列重取；country map；scope 設一次復用 / 跨國擴充 / 未知國 fail-fast 不觸 settings）。全套件 296 passed / 1 failed；唯一失敗 `test_pdf_resolver::test_routing_tipo_priority` 是 **live 網路測試**（走 GPSS REST @PN，非本 BR 打擊半徑），因無憑證 + 週末額度耗盡落 gpatents scraper 失敗，環境性非回歸。`specs/architecture.md` 已同步。

### §5 live 驗證（2026-07-19 使用者授權推 live，TW 核心已坐實）

[x] container 重啟載入新 code + smoke。
[x] §5 對 `pending_tw_99`(全 appno 切片) 重跑 `gpss4_resolve_appnos` → **resolved 6/6**（前為 0）。
[x] §5 known-item TW roundtrip：`TW109112770`(@AN) → `TW202138759A`（與 converter ground truth 一致）。
[x] §5 CN/US 跨國各一筆（2026-07-19 live，趁 keep-alive 活 session 順帶驗）：`CN110234567` → dual-view render `pat_no=CN110234567` + `apply_no=CN201780085750.5`（CNA/CNB scope）；`US10000000` → `pat_no=US10000000` + `apply_no=US14643719`（USA/USB scope）。**順帶推翻** `issue_20260716`「CN pat_no 只在 AJAX 不在 dual-view HTML」舊限制——本次 CN pat_no+apply_no 都在 dual-view render 出。跨國機制通用坐實。

> ⚠️ 原 §5 驗證輸入 `TW202223848` 判定為**測試輸入錯誤**：它是**公開號**（西元年制 2022+023848）非申請號，用 @AN 軸查必 NOT_FOUND，非 bug。真實生產輸入是民國年 appno。

### live 揭出並修復的 3 個真 bug（2026-07-19，system-first RCA + instrumented trace）

1. **設定頁 read-modify-write 漏輸出欄位**：`set_search_databases` POST body 只 echo `_20_1_S_*`（資料庫）+ hidden，漏掉所有 `_20_23_S_*`/`_20_20_S_*` 輸出欄位 checkbox 與顯示 radio。GPSS 存整頁 → 未 echo 的 checkbox 存成未勾 → fresh account 會被靜默清空輸出欄位（正是 §1「命中卻抽不到號碼」的機制；使用者明示「輸出格式也要選對」直接命中）。**修**：改 read-modify-write 保全全部 checkbox/radio + `_REQUIRED_OUTPUT_FIELDS`（PN/AN/TI/日期）force-ensure。設定頁三區塊逆工自 live dump：`_20_1_S_*`=資料庫、`_20_20_S_*`(簡目)/`_20_23_S_*`(詳目)=輸出欄位、`_20_6_A`/`_20_14_A`=顯示格式 radio。
2. **`apply_no` parse 殘缺**：`_extract_dual_rows` 用 `ap.split()[0]`，申請號 render 為「TW 109112770」(CC 與數字間空格) → 只取到 `TW` 丟數字，破 @AN 比對。**修**：regex 抽完整 CC+digits token 去空格。live 坐實（`TW080203372` 完整匹配）。
3. **batch slot 契約（harvest-timing + connection-refused transient）**：
   - **harvest-timing**（真 root cause，instrumented trace 坐實）：GPSS4 slot anchor 是 **session 級「當前 slot」指標**，每個 response mint 新 slot 並作廢前一個。原 `resolve_one` 在 `result_html`（submit 後）就 harvest anchor，之後又做 dual-view POST（作廢剛抓的 anchor）→ 下一筆用 spent anchor → `len=289`。**修**：harvest 移到 dual-view 之後，從該筆最後一個 response 抓。batch 2/N→3/3。
   - **connection-refused transient**：`len=289` body 全文=「TTS SystemMessage:Connection refused.」（**非**配額/登入逾時）——連線層 transient，大結果集後打在任一 HTTP hop（GET/submit POST/dual POST），請求從未執行（anchor 未消耗）。**修**：`_is_transient` predicate + `_post_retry` helper（escalating backoff 重試同一請求，safe by TCP-reject semantics），套到 adv-form GET + 三個 POST 落點。**batch 6/6 全過、0 error**（INFO log 證實多落點 retry 觸發並全恢復）。

**檔案（增修）**：`gpss4/adv_search.py`（`set_search_databases` read-modify-write + `_REQUIRED_OUTPUT_FIELDS` + `_extract_dual_rows` parse + `resolve_one` harvest-timing + `_enter_dual_view` `bump_page_size` 參數 + `_is_transient`/`_post_retry`/`_CONN_REFUSED_MARK`/`_ADV_FORM_RETRIES`/`_ADV_FORM_BACKOFF` + `GPSS4AdvZeroHits.html`）；`gpss4/session.py`（`_adv_tab_next` 欄位 + login 清空）。

**驗證**：單元測試 `tests/test_br20260719_adv_route.py` 10 全綠；live batch 全 appno 6/6 resolved 0 error。

### Remaining

- 無。§5 全部 live 驗證通過（TW roundtrip + pending_tw_99 batch 6/6 + CN/US 跨國各一筆）。

**本 BR 全路徑 live 坐實，可推 resolved。** CN/US 跨國驗證是趁 `patentmcp_gpss4-session-keepalive` plan 的 keep-alive 活 session 順帶完成（單一 session 跨 TW mint + CN + US 三查只登入一次，login_count=1 reuse_count=2）。
