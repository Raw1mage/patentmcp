# BUG REPORT (工作流): 來源梯未窮舉即宣告無解 — skill §5 漏載「官方路由 + 單線批量軟性抓圖」新工具，且未把爬蟲定位成被授權機制

**Date**: 2026-06-28
**Status**: REOPENED (2026-07-06 — 原修復 2026-06-28 已 Resolved,但 closed 8 天即復發於 delegation 層;skill §5 修復未投影到委派契約,見文末復發記錄)
**Priority**: High

> **修復摘要**:`patentworks/SKILL.md §5` 三項全做——(1) 加「來源梯窮舉門檻(Exhaustion Gate)」硬規則(宣告任一欄位缺失前須逐級走完來源梯並留證);(2) 補載 `fetch_patent_pdf`/`extract_representative_figure`/`patentmcp_batch_download_figures`/`ppubs_batch_get_claims` 並刪除過時「PDF 端點系統性故障」論斷;(3) 重寫爬蟲天條天平(同意後批量軟性機制是正規合規路徑,`scraping:true` 非違規證據)。
**Target**: `skills/patentworks/SKILL.md` §5 來源優先序 + `flows/priorsearch.md` 代表圖/全文取得段
**Reporter**: AI Agent (代表 User)
**Source Session**: iSafe2.0 報告 R2 後續問答（使用者連續四次糾正同一認知毛病）

---

## 1. 磨擦點與問題描述 (Friction Points)

### A. AI 反覆「遇到一個障礙就宣告終局」，而非沿來源梯窮舉

* **現象**：本 session 同一個認知毛病被使用者**連續四次**抓到——
  1. GPSS 對 US 案回傳 claim 1 為空 → 我（在 R2）寫「Claim 1 從缺」，沒走 ③PPUBS fallback。實測 `ppubs_batch_get_claims` 一次就抓到完整 3201 字逐字 Claim 1。
  2. 代表圖缺 → 我寫「三條路全斷、無解」，沒查 `fetch_patent_pdf`（官方路由優先）。實測三件案 PDF（1.4MB/2.1MB/2.1MB，各含 20 個內嵌影像）全部抓回。
  3. `extract_representative_figure` 失敗 → 我寫「沒有圖」。實際是該工具的 FIG.1 文字定位器對掃描版 PDF 失效，**圖就在已下載的 PDF 裡**（20 個 image XObject）。
  4. 我把 `provenance.scraping:true` 當紅燈猛剎車 → 宣稱「違規觸發爬蟲」，**完全不知道 patentmcp 已內建 `patentmcp_batch_download_figures` 單線批量軟性爬蟲合規機制**，把「機制存在」和「我無權啟動」混為一談。
* **共通根因**：把「某工具回空 / 某條路被封 / 某定位器失敗」一律解讀成「整件事終局無解」，而非「沿來源梯走下一級 / 換工具 / 從已在手的中間產物再加工」。
* **這是 skill 該防的事**：skill §5 寫了五級來源梯，但**沒有一條硬規則要求「宣告某資料缺失前，必須逐級走完來源梯並留證」**。於是 AI 可以在第①級回空就停手、字面上不違反任何規範。

### B. skill §5 漏載一整批「官方路由優先 + 高階抽圖 + 單線批量軟性抓圖」工具

* **現象**：patentmcp 實際已有以下工具，但 SKILL.md §5 與 priorsearch.md **完全沒提**：
  | 工具 | 實測行為 | skill 現況 |
  |---|---|---|
  | `fetch_patent_pdf` | 「Routes official sources first」，三件案 PDF 全抓回 | 未載 |
  | `extract_representative_figure` | BR_20260628 D 的修復版（定位 FIG.1 高解析渲染），取代「選最大檔」爛策略 | 未載 |
  | `patentmcp_batch_download_figures` | **單線批量軟性爬蟲合規機制**（Concurrency=1 + 隨機延遲，正是 §5 天條要求的受控形式） | 未載 |
  | `gpss_download_patent_pdf` / `_xml` / `_representative_figure` | GPSS headless 單件抓取 | 部分提及但標「系統性故障」 |
* **後果**：§5 還停在舊認知——line 55 寫「PDF 二進位下載端點系統性故障，只能走降級路徑」。但 `fetch_patent_pdf` 實測**可用**。AI 讀到的 skill 把「圖/PDF 無解」當既定事實，自然不會去試這些新工具。**skill 的過時內容直接製造了 AI 的錯誤心智模型。**

### C. 爬蟲被定位成「紅燈禁區」，而非「被收斂成單線+限速+需同意的內建能力」

* **現象**：§5 天條（line 50-52）的措辭重心是「**明確口頭同意 + 嚴禁擅自執行**」，讀起來像「爬蟲=危險紅線」。但 patentmcp 的實際設計哲學是相反的：**爬蟲不是禁區，而是被工程收斂成 `patentmcp_batch_download_figures` 這種單線批量軟性機制**——BR_20260628 整份文件就是這機制的設計依據。
* **後果**：天條只寫了「未經同意不准爬」，**沒寫「同意後就用這個內建合規機制爬，這是正規路徑不是越界」**。於是 AI 把 `scraping:true` 當違規證據、把整個爬蟲能力當需要迴避的東西，反而否定了 repo 花力氣設計的合規路徑。措辭的天平偏了。

---

## 2. 建議修復 (Proposed Remediation)

### 修復 1（核心）：§5 加一條「來源梯窮舉門檻（Exhaustion Gate）」硬規則

* 明文規定：**宣告任一資料欄位（claim 1 / 代表圖 / 全文 / 書目）缺失前，必須逐級走完來源梯並在報告 §誠實缺口留下每一級的實測結果（成功/失敗/失敗原因）。** 只在第①級回空就停手 = 流程缺陷，不是合法降級。
* 對應 search_audit 精神：把「檢索強度」那套「先驗過程再驗產物」的機檢思維，延伸到「取文/取圖強度」。

### 修復 2：§5 全面更新工具清單，把新工具納入正確的梯級

* 補載 `fetch_patent_pdf`（官方路由優先，取 PDF/全文的首選）、`extract_representative_figure`（從 PDF 抽代表圖的高階工具）、`patentmcp_batch_download_figures`（批量抓圖）、`ppubs_batch_get_claims`（US claim 1 補抓，已實證可靠）。
* 刪除/修正 line 55「PDF 端點系統性故障」的過時論斷——改為「`fetch_patent_pdf` 官方路由優先，失敗才降級」。
* 明確「圖在 PDF 裡」的事實：取不到代表圖的最後一步，是從**已下載的 PDF** 本機抽圖（純 PDF 處理，非爬蟲），而非直接放棄。

### 修復 3：重寫 §5 爬蟲天條的天平 — 從「紅燈」改為「受控的被授權能力」

* 保留「使用前需明確同意 + 單線限速」兩條硬約束（這對）。
* **新增**：「同意後，`patentmcp_batch_download_figures` 等單線批量軟性機制是抓圖/抓 PDF 的**正規合規路徑**，`provenance.scraping:true` 是這機制的正常標記、非違規證據。不要把內建合規爬蟲當需要迴避的越界行為。」
* 讓 AI 讀完 §5 後的姿態是：「機制存在、合規、就是設計來幹這個的；我唯一缺的是使用者那句授權」——而不是「爬蟲危險、能不碰就不碰」。

---

## 3. 影響範圍 (Blast Radius)

* 任何讀此 skill 跑 priorsearch 的 session：都會重演「來源梯第①級回空就宣告無解」+「不知道有官方路由/批量抓圖工具」+「把爬蟲當紅燈」三連錯，導致報告 claim/圖欄位無謂缺失。
* 直接後果：交付品質被 AI 的過早終局判斷拉低，使用者得反覆糾正同一件事（本 session 四次）。

## 4. 驗證手段 (Validation Plan)

* 修復後，拿本 session 三件案回歸：讀新版 §5 的 AI 應能（a）US claim 1 自動走 PPUBS 補齊；（b）代表圖先試 `fetch_patent_pdf` + `extract_representative_figure`，失敗才從已下載 PDF 抽圖；（c）需爬蟲時直接認 `patentmcp_batch_download_figures` 為正規路徑、只缺使用者同意；（d）任何缺失都附「來源梯逐級實測結果」而非一句「無解」。

---

## 復發記錄 2026-07-06（closed 後 8 天復發 — 升級處置訊號）

**Session**: 影像式異常偵測報告 v3.1 聲學專章擴充（`research_acoustic-anomaly-detection`）

**預言成真**：本 BR §4 驗證計畫(b)(d) 正是本輪被違反的項目。聲學專章 13 件核心案的深度解析，全數（13/13）被子代理寫成「官方來源（GPSS、EPO、Google Patents）之圖式取得從缺，本專章以文本解析為主」——**未走任何取圖梯就宣告從缺**，與本 BR §1.A line 20-21 記錄的毛病字面同型。

**硬證據**：
- 工作區 PDF count = **0**（`output/priorart_acoustic-anomaly` 與 `/tmp` 皆無任何 `.pdf`）→ 子代理根本沒呼叫 `fetch_patent_pdf`／`gpss_download_representative_figure` 就下結論。
- 使用者一句話點破：「TIPO 的直接取圖法怎麼不用」。
- 補救實測（同 session、同 13 件案）：**GPSS 直接取圖 CN 案 4/4 全中**（CN120954165A/CN115457975A/CN104978810A/CN121214974A，本來就該取得）；US/WO 9 件經 `fetch_patent_pdf`（官方 google_citation PDF）+ `figure_extract.py` 抽圖全數取得（含 3 件無文字層影像型 PDF 手動渲染圖式頁）。**最終 13/13，零從缺**。證明「從缺」是流程缺陷，不是資料不存在。

**新維度（本 BR 原修復未涵蓋）— delegation 斷層**：
- 本 BR 的修復對象是 `SKILL.md §5` + `flows/priorsearch.md`（主代理讀的 skill）。但**子代理不讀 AGENTS.md、其取圖窮舉義務靠 orchestrator 的 task prompt 傳遞**。本輪主代理委派取文子代理時，prompt 未把「代表圖必走 GPSS 直接取圖 + PDF 抽圖雙路徑才可宣告從缺」寫進去 → 子代理無 skill §5 的 Exhaustion Gate 約束，重演終局判斷。
- **根因升級**：skill 層已修（6/28），但修復未投影到 **delegation contract**。取圖／取文窮舉門檻需成為委派 patent 檢索／取文子代理時的**強制 prompt 條款**（如同 tick-task 契約寫進 coding.txt），否則每次委派都是一次 skill §5 約束的漏斗流失。

**處置建議（reopen 評估）**：closed 8 天即復發，且復發面在 skill 未覆蓋的 delegation 層 → 建議 **reopen 或另立 delegation-contract 子 BR**，把「patent 子代理取圖/取文 prompt 必含 Exhaustion Gate 條款」固化進 orchestrator 的委派模板。單靠 skill §5 無法約束不讀 skill 的子代理。

**本輪即時補救**：13/13 代表圖已補齊入 v3.1 docx（2.74MB→4.34MB），圖來源純官方（`provenance.scraping=false`），已目視驗證聲學章渲染。event log 已記（`research_acoustic-anomaly-detection` scope）。

---

## 驗證 A 通過記錄 2026-07-06（委派契約條款本身正確有效）

**驗證設計**：把新寫的 SKILL.md §5「🔴 委派契約(Delegation Gate)」4 條款嵌進取圖子代理的 task prompt（模擬 opencode 將來的自動注入），dispatch 3 件跨路徑真實案，驗證條款能否讓子代理走窮舉、零無謂從缺。**這測的是「條款寫得對不對」，邏輯上先於 opencode 的自動注入橋**——注入橋只是自動搬運條款，條款本身錯了注入也白搭。

**結果：3/3 取得代表圖，逐案逐級留證，零無謂從缺。**（子代理回報 + 主代理 ls/stat 落實核對，非空報）

| 案 | 路徑 | 產出 | 決定性觀察 |
|---|---|---|---|
| CN120564339 | GPSS headless 失敗→figure_extract.py PDF 抽圖(page 2) | 829KB PNG 1654×2339 | 第①級失敗未停手,依契約降級成功 |
| US10096234B1 | extract_representative_figure→figure_extract.py(fig1_text, page 2) | 52KB PNG 1700×2200 | 官方路徑正常 |
| WO2018151004A1 | →figure_extract.py 回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`→視覺確認封面代表圖 pdftoppm 落地 | 162KB PNG 1654×2339 | **關鍵**:此觸發點正是原 BR 復發時子代理誤判「從缺」的同型;這次依契約**不宣告無圖**,條款擋住終局判斷 |

**結論**：SKILL.md §5 委派契約條款正確、止血已實測有效。BR 三段進度更新為：
- ✅ domain-local 止血（SKILL.md 委派契約）— 已 commit + **驗證 A 通過**
- ⏳ 根因（skill→子代理 prompt 自動注入橋）— handoff opencode `BR_20260706_skill_delegation_clauses_no_runtime_injection_into_subagent_prompt`，未修
- ⏳ 驗證 B（自動注入有效）— 等 opencode 根因修好

**BR 維持 REOPENED**：patentmcp 這 repo 對本 BR 的責任（止血 + 驗證條款正確）已執行完畢；最終 close 卡在 opencode 根因（跨 repo 依賴）。

**驗證 A 揭出的 patentmcp 工具層 friction（另立 issue 追蹤，非本 BR 範疇）**：
1. `patentdb/<國>/<案>/` 目錄 root 擁有權 → PNG 需 sudo 落地 chown；容器化流程無 sudo 會 EACCES。
2. WO 純掃描 PDF（無文字層）→ `figure_extract.py` text-based 定位器天然失效，目前靠人工視覺確認封面；缺 OCR / 「封面內嵌圖」自動化 fallback。
