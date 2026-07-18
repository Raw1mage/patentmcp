# BR: 取代表圖走錯觸達機制 — RCA（軸B 主因：orchestrator 未載 patentworks → 對 live MCP tool 用 raw-socket curl / 軸A 殘餘：figure_extract.py 無頁首帶狀裁切）

**Date**: 2026-07-12
**Status**: Open（軸A 已修，僅軸B 待閉環）
**Priority**: High（軸B 流程缺陷）+ ~~Medium（軸A 工具增補）~~ **軸A DONE**

> **狀態更新（2026-07-18，open-BR 清理盤查）**：
> - **軸A（figure_extract header-trim）已修** ✅：`skills/patentworks/scripts/figure_extract.py`
>   已實作 `_trim_header_band()`（:394）+ `_autocrop_to_png(trim_header=...)`（:441）+
>   CLI `--trim-header`/`--no-trim-header`（:480-487）+ `_crop_render_png(trim_header=...)`
>   （:356），docstring 標記 `BR_20260712 軍A`。§3 軸A 修法 3 已落地。
> - **軸B（orchestrator 領域盤查強制性 + GPSS 首選圖工具命名曝光）待閉環** 🟡：
>   屬跨層紀律問題（AGENTS.md 領域進入點盤查仍是 prose 反射、無 code 閘；
>   `gpss_download_representative_figure` 在 README 產物段命名曝光不足）。
>
> **2026-07-18 驗證後細分**（軸B 拆兩塊，必要性不同）：
> - **B-1 patentmcp 域內（README 命名曝光）已閉環** ✅：`README.md:13` 產物段原只列
>   `gpatents_download_pdf/figure`（爬蟲尾級），現已改為首選
>   `gpss_download_representative_figure`（country-agnostic 官方乾淨代表圖）/ TW·CN 走
>   `patentmcp_batch_download_figures`，`gpatents_*` 降為尾級 fallback（對齊 §3 修法 5a）。
>   注：SKILL.md:235-236 早已有強 GPSS-first 取圖鐵律，故域內殘留僅 README 這一處。
> - **B-2 opencode harness 域（orchestrator 領域盤查 code 閘）待處理** 🟡：跨 repo，
>   非 patentmcp 責任（AGENTS.md 領域進入點盤查仍是 prose 反射、無 code 閘；屬
>   opencode companion-binding 機制）。本 BR 在 patentmcp 側的實質工作已全數落地，
>   保持 open 僅為追蹤 opencode 側的 harness 修法。
**Target**:
- 軸B（主因）：orchestrator 領域進入點盤查（AGENTS.md「領域進入點盤查」反射）→ 未載 skill 導致看不到 R13 兩平面圖 → 對 container-plane live MCP tool 反射用 raw `curl --unix-socket` + 手拼 JSON-RPC，而非 MCP toolcall
- 軸A（殘餘）：`skills/patentworks/scripts/figure_extract.py` 無 header-trim
**Reporter**: AI Agent（telecam WiFi-CSI 前案報告 v5.2 交付檢討）
**Source**: telecam `research/wifi-csi-crossmodal-priorart` 報告 4 張專利代表圖帶「说明书附图 / Sheet N of M」頁首帶狀文字

> **重要更正（本 BR 初稿的自我修正）**：初稿曾把「subagent 用 `figure_extract.py` 腳本」列為造輪子違規。**這是錯的更正**。patentworks R13 兩平面規則明載 `extract_representative_figure` 已 landed 為 host-local 腳本 `figure_extract.py`（舊 MCP tool 回 `TOOL_LANDED` redirect）——**呼叫該腳本是欽定路徑，非違規**。真正的軸B 違規是：對**仍是 container-plane live MCP tool** 的 `gpss_download_representative_figure` 用 raw-socket `curl` 手拼 JSON-RPC，而非直接 MCP toolcall。根因是 orchestrator 未載 patentworks → 看不到 R13 兩平面圖 → 無法分辨「哪些 op 是 landed 腳本、哪些是 live toolcall」→ blind 之下對 live tool 也 reflexively 用 curl。

---

## 0. 症狀

WiFi-CSI 前案分析報告交付後，4 張專利代表圖（US20220262164A1 + 3 件 CN）帶「说明书附图 / Sheet N of M / 页码」頁首帶狀文字，非乾淨代表繪圖。使用者指出取圖用錯工具。

## 1. RCA — 兩軸分類（code-thinker 磨擦分類：軸A 工具可用性 vs 軸B AI 用對）

### 軸B（主因，流程缺陷）：orchestrator 跳過 patentworks 領域盤查 → 對 live MCP tool 反射用 raw-socket curl（非 toolcall）

- **觸達機制錯誤（核心）**：`gpss_download_representative_figure(publication_number, all_figures=False)` 是 patentmcp **container-plane 的 live MCP tool**（R13 兩平面：網路/憑證工作留在 container 當 MCP tool）。正解觸達是**直接 MCP toolcall**（runtime on-demand 自動載入，105 個 patentmcp tool 皆可直呼）。實際卻走 raw `curl --unix-socket ~/projects/patentmcp/.run/patentmcp.sock` + 手拼 `init_session()` JSON-RPC 去戳 socket——**對一個一等 MCP tool 用最低階的 bash 觸達**。這正是 SYSTEM.md 紅線「禁止徒手替代專門工具 / 先查 lazy loader 再宣稱不可用」與 code-thinker 軸B「沒用對觸達方式」。
- **R13 兩平面必須先載 skill 才看得到**：patentworks R13 表把 op 分兩類——(a) `extract_representative_figure → figure_extract.py`（**landed host-local 腳本**，呼叫腳本正確）；(b) `gpss_download_representative_figure` / `patent_search` / `fetch_patent_pdf`（**仍是 container-plane live MCP tool**，走 toolcall）。**未載 skill = 看不到這張圖 = 無法分辨腳本 vs toolcall**。
- **根因（單一上游）**：AGENTS.md「領域進入點盤查（Domain-Entry KB Probe）」是 Mandatory 前置反射——偵測到專利領域任務時，開工/委派前必須先 `skill(patentworks)`。**orchestrator 未執行此反射**，連鎖導致：
  1. 看不到 R13 兩平面圖 → 對 live tool `gpss_download_representative_figure` 反射用 raw-socket curl，而非 toolcall；
  2. patentworks 的 runtime 委派注入**只在 skill 被 pin 時才注入子代理 prompt**（BR_20260706）——skill 未載 → 注入未觸發 → 子代理繼承同款「戳 socket」模式；
  3. 取圖工具梯（乾淨代表圖首選 `gpss_download_representative_figure`）從未進入決策脈絡。
- **這是 axis-B「工具沒壞、是我沒選對觸達 / 沒載對 KB」**：tool 存在且正確、R13 路由完備、SKILL.md 記載齊全，純粹因 orchestrator 漏掉強制 skill 盤查，使「toolcall vs 腳本」的分辨能力、正確路由、委派注入三者同時失效。
- **澄清非違規項**：subagent 呼叫 `figure_extract.py` 腳本本身**合規**（R13 landed plane）；不要把它算進違規。

### 軸A（殘餘，真工具缺陷）：figure_extract.py 整頁渲染、無頁首帶狀裁切

- `figure_extract.py`（patentworks 官方 ship 腳本，非自製）策略：定位 FIG.1 頁 → **整頁 poppler 渲染 PNG**（`_render_page_png`）。參數只有 `--pdf/--out/--dpi/--repo`，**無 bbox/crop/header-trim**。
- 對 page bounds 內嵌有「说明书附图 / Sheet N of M」帶狀文字的來源 PDF（US20220262164A1 官方 PDF、部分 CN 頁），整頁渲染必然帶入該帶狀 → 需下游 host-local PIL 裁切兜底（本次 US 案即如此：GPSS 無 US row，改保留官方 PDF 全頁 + PIL 裁上緣 11.5% + autocrop）。
- **這是 axis-A「工具能力缺一段」**：figure_extract.py 對「US/部分案帶頁首帶狀」缺 header-trim primitive，逼使下游 PIL 補裁。

## 2. 影響範圍

- 軸B：任何專利取圖/取文/前案吸收類任務，orchestrator 若漏載 patentworks，就會（a）選錯代表圖工具（用 figure_extract 而非 gpss_download_representative_figure）、（b）委派注入不觸發、子代理反射用整頁渲染。跨全部 domain skill 通用（不限專利）。
- 軸A：所有走 `figure_extract.py` 且來源 PDF page bounds 內含頁首帶狀文字的案（US 案尤甚，GPSS 無 US row），代表圖都會帶帶狀，需人工/PIL 兜底，無法批量乾淨自動化。

## 3. 建議修復

### 軸B（主因，優先）

1. **強化領域盤查反射的可觀測性/強制性**：AGENTS.md「領域進入點盤查」目前是 prose 反射（靠 AI 自律）。偵測到專利領域訊號（patentmcp 載入 / `.patentdb` / patentdb 目錄 / 使用者提「專利/前案/代表圖」）時，應在開工前顯化「patentworks 可載」並實際 `skill(patentworks)`，而非跳過。考慮 code 層 companion 綁定（如 docxmcp companion skill 綁定機制）把「載 MCP → 載 companion skill」升為 point-of-decision 前置閘。
2. **委派取圖子代理前，orchestrator 必先載 patentworks**——確保 runtime 委派注入觸發（L197-204 clause 進子代理 prompt）。這是 BR_20260706 委派注入機制生效的前提，本次因 skill 未載而落空。

### 軸A（殘餘，工具增補）

3. `figure_extract.py` 增補 header-band trim：
   - (a) 對定位到的圖頁，偵測頂部帶狀文字（「说明书附图」/「Sheet N of M」/「Patent Application Publication」/ 公開號行）並自動裁切；或
   - (b) 加 `--trim-header` / `--bbox` 參數讓上游可指定裁切；或
   - (c) 對 US 案優先路由到 `gpss_download_representative_figure`（country-agnostic，實測對 CN 直出乾淨圖；US 無 row 時再退官方 PDF 抽圖 + trim）。
4. 或在 patentworks SKILL.md 工具梯明確標註：**要「乾淨代表圖」首選 `gpss_download_representative_figure`（country-agnostic，無頁首帶狀）；`extract_representative_figure`/`figure_extract.py` 為整頁渲染，帶頁首帶狀時需下游 trim**——把「乾淨 vs 整頁」的取捨寫進路由，降低軸B 再犯。

## 4. 驗證手段

- 軸B：對一個專利取圖任務，斷言 orchestrator 開工前 log 有 `skill(patentworks)` 呼叫，且委派子代理 prompt 含 `<!-- delegation-clauses -->` 注入內容。
- 軸A：對 US20220262164A1 官方 PDF 跑增補後的 figure_extract.py（`--trim-header`），斷言回代表圖無「Patent Application Publication / Sheet 1 of 5」帶狀，無需下游 PIL 裁切。

## 5. 本次實際結果（供修復參照）

| 案 | 正解工具實測 | 結果 |
|---|---|---|
| CN121637048A（華為） | `gpss_download_representative_figure` `success:true` `figure_kind:full_g2` `full_figures_available:7` | 乾淨代表圖，無帶狀 ✓ |
| CN121330574A（中郵） | 同上 `full_figures_available:3` | 乾淨流程圖，無帶狀 ✓ |
| CN120659577 | 同上 `full_figures_available:23` | 乾淨 RF 場景圖，無帶狀 ✓ |
| US20220262164A1 | `success:false — GPSS no matching row`（US 案，GPSS 誠實拒抓鄰列） | 退官方 PDF 全頁 + PIL 裁上緣 11.5% + autocrop，等效乾淨 ✓ |

## 6. 同族第二實例（2026-07-13，telecam v5.3 第伍章代表圖任務）— 軸B「命名 affordance 誤導選錯工具」

**Date appended**: 2026-07-13
**Reporter**: AI Agent（telecam WiFi-CSI 前案報告 v5.3 第伍章交付）
**Source**: 使用者要求「用 patentmcp 代表圖下載功能」抓 11 件樣品專利代表圖時，orchestrator（本次已載 doc-workflow，但**未載 patentworks**）在盤點工具時**直覺選了 `gpatents_download_figure`**（README line 13「`gpatents_download_pdf/figure`(代表圖/PDF)」），使用者當場指正：「應該不是用 google patents 吧？應該有 GPSS 的工具可以直接下載。為什麼你會直覺去使用 gpatents 呢？這是 bug。」

### 與 §1 軸B 的差異（新的一層，非重複）

- §1 軸B ＝「**選對工具**（`gpss_download_representative_figure`）但**觸達錯**（用 raw-socket curl 而非 toolcall）」。
- 本實例 ＝「**選錯工具**」：直覺挑 `gpatents_download_figure`（Google Patents 爬蟲**尾級**取圖）而非 GPSS 首選工具。觸達層還沒到，決策層就先錯了。

### 根因：命名 affordance 讓 GPSS 首選圖片下載「不可見」

- patentmcp 的**檢索**入口已統一為 `patent_search`，其來源梯**首選 TIPO GPSS 官方 API**（README line 11），Google Patents 爬蟲是須明確授權的**尾級**。
- 但**取圖/取產物**工具的命名卻只暴露 `gpatents_download_pdf/figure`（README line 13）——冠 `gpatents_` 前綴，語意上把「下載代表圖」綁死在 Google Patents 平面。§5 表已證實真正 country-agnostic、直出乾淨圖的首選是 `gpss_download_representative_figure`（container-plane live MCP tool），但**它在 README 產物段沒有對等曝光**。
- 結果：AI 面對「下載代表圖」意圖，眼睛掃到的唯一命名對應是 `gpatents_download_figure` → 直覺選它。這是 code-thinker 軸B(a)「**沒選對**——面對意圖漏掉正解工具」，根因在**工具命名/文件曝光的 affordance**，不在 AI 臨場聰明度。命名把尾級工具擺在檯面、把首選工具藏在 skill 內文，選錯是必然而非偶然。

### 建議修復（疊加在 §3 之上）

5. **產物工具命名/曝光對齊檢索來源梯**：既然 GPSS 是檢索首選，取圖首選也應是 GPSS。至少三選一：
   - (a) README「取文/產物」段明列 `gpss_download_representative_figure` 為**乾淨代表圖首選**（country-agnostic），並標註 `gpatents_download_figure` 為爬蟲尾級 fallback；
   - (b) 提供來源無關的 `patent_download_figure`（比照 `patent_search` 統一入口），內部走同一來源梯（GPSS→…→gpatents），消除「冠 gpatents 前綴 = 只能走 Google Patents」的誤導；
   - (c) patentworks SKILL.md 工具梯把「代表圖首選 GPSS」寫進 point-of-decision，並靠領域盤查強制載入使其進決策脈絡。
6. **佐證 §3.1 的領域盤查強制性**：本次 orchestrator 載了 doc-workflow 卻**漏載 patentworks**，正是 §1 根因（未執行領域進入點盤查反射）的第二次復發——復發本身即證據，領域盤查仍靠 AI 自律、未有 code 層閘。

## 關聯

- BR_20260706（委派契約 runtime 注入）：本 BR 揭出該注入機制的**前提**——skill 必須先被 orchestrator 載入/pin，注入才觸發。skill 未載 = 注入落空 = 委派契約回歸。
- issue_20260706（figure_extract 目錄擁有權 + 掃描件無 OCR）：同一取圖工具鏈的獨立缺陷；本 BR 軸A（無 header-trim）為第三個 figure_extract friction。
- §6 同族第二實例（2026-07-13）：軸B 從「觸達錯」延伸到「選錯」，兩者共用同一根因——patentworks 領域盤查未強制執行 + GPSS 首選工具在產物層命名曝光不足。
