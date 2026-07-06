# BUG REPORT (工作流): 來源梯未窮舉即宣告無解 — skill §5 漏載「官方路由 + 單線批量軟性抓圖」新工具，且未把爬蟲定位成被授權機制

**Date**: 2026-06-28
**Status**: Resolved (2026-06-28, plan `br20260628_tooling_skill_gpss_gaps`)
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
