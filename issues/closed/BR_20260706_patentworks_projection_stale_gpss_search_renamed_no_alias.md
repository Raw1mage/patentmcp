# BR_20260706 — patentworks skill 投影過期：教 AI 呼叫已改名退役的 `gpss_search`（現為 `patent_search`），且 server 無 deprecation alias；導致 ~30 次 unknown-tool 迴圈、使用者被迫中斷

- **Scope**: patentmcp — skill projection sync（patentworks）+ tool rename 遷移契約
- **Severity**: HIGH（skill 是工具名的教學來源；教錯名字＝整條 priorsearch flow 開場即死，燒掉大量回合）
- **Status**: RESOLVED (2026-07-06)

> **修復紀錄（2026-07-06）**：
> - **D1（投影過期）**：已以 SSOT rsync 重同步 XDG 投影；驗證 `grep -c patent_search` 投影 priorsearch.md = 10、`gpss_search` = 0（完全對齊 SSOT），並觸發 daemon skill 索引 rescan。治本半邊（skill() freshness gate / commit hook）屬 opencode 側，見彼側 BR 交叉引用。
> - **D2（缺 alias）**：`patents.py` 已註冊 `gpss_search` / `epo_search` / `gpatents_search` 三個 deprecation stub（一個版本週期），回 typed `{success:false, error_code:"TOOL_RENAMED", use:"patent_search"}`，不執行舊邏輯。測試 `tests/test_tool_renamed_stubs.py`（3 pass）；容器重建後 live 實測 `mcpapp-patentmcp_gpss_search(cpc=..., keyword=...)` 回 TOOL_RENAMED envelope ✔。
> - **文件化**：新建 `CHANGELOG.md` 補 `7c4330d` rename 對照表（含參數對映與下架參數）。
- **Discovered during**: 異常偵測前案檢索 v3（session cwd: gdrive `20260615 異常偵測 前案檢索`，2026-07-06）

## 現象（硬證據）

1. Session 以 `skill(name="patentworks")` 載入 skill，載到的是 **XDG 投影**：
   - `~/.local/share/opencode/skills/patentworks/.capability-installed.json`：`installedAt: 2026-06-28T08:08:30Z`（檔案 mtime 06-29），`sourceHash: 432adab...`
   - 投影的 `flows/priorsearch.md`：`gpss_search` 出現 **8 次**、`patent_search` **0 次**——整份 flow 的檢索主力工具寫的是 `gpss_search`。
2. **SSOT 已改版**：`~/projects/patentmcp/skills/patentworks/flows/priorsearch.md`（mtime **2026-07-03 13:43**）：`patent_search` **10 次**、`gpss_search` **0 次**。
3. **Server 端已無 `gpss_search`**：commit `7c4330d` "feat(search): unify all search tools into single patent_search dispatcher"；`patents.py` 只剩私有 `_gpss_search_impl`（`patents.py:2514`），`@mcp.tool()` 公開名單無 `gpss_search`，統一入口為 `patent_search`（`patents.py:2648`，"the ONLY search-class MCP tool"）。
4. **後果**：AI 依 skill 教學呼叫 `gpss_search` / `mcpapp-patentmcp_gpss_search` 合計 ~30 次全落 opencode invalid sink（該側另有 BR，見「影響範圍」）；使用者被迫人工中斷（"暫停一下，發生大量磨擦"）。
5. `CHANGELOG.md` grep `patent_search|gpss_search` 無 rename 遷移記載（rename 未文件化）。

## RCA

兩個相扣缺陷：

- **D1 — 投影不隨 SSOT 更新（stale mirror）**：`7c4330d` 改名時同步改了 SSOT skill（正確），但 XDG 投影是 06-28 安裝的快照，之後 **沒有任何機制**（rename commit 後未重跑 `install-skills`；`.capability-installed.json` 的 `probeCachedUntil` 只有 1 小時，過期後也不觸發 sourceHash 重驗）把投影拉齊。`skill()` 永遠載投影 → AI 被舊教材教壞。這是 plan-builder SKILL.md §14 早已警告的「投影是 cache 不是 source」的實際翻車案例——但該警告只約束「gate/producer scripts 用 SSOT 路徑」，**skill() 本身沒有 freshness gate**。
- **D2 — tool rename 無 deprecation alias / typed redirect**：`gpss_search` 被直接移除而非留一個 cycle 的 alias。若 server 保留 `gpss_search` 為 stub、回 typed error `TOOL_RENAMED: use patent_search`（比照 `SCRAPING_REQUIRED` 的 fail-fast 慣例），AI 第 1 次呼叫就會被糾正，而不是 30 次 unknown-tool。改名時也未在 CHANGELOG 記遷移對照。

## 建議修復

1. **（治本）rename/介面變更 → 投影同步成為 commit 契約**：凡動 `skills/patentworks/**` 或改 `@mcp.tool` 公開名，同 commit（或 CI hook）必跑 skill 投影同步（`install-skills`），並 bump `.capability-installed.json` 的 `sourceHash`。
2. **（防呆）skill() freshness**：`.capability-installed.json` 已有 `sourceHash` + `sourceRepoPath`——載入時（或 daily probe）重算 SSOT hash，不符即 warn/auto-resync。（此半邊屬 opencode skill loader，已在 opencode 側 BR 交叉引用。）
3. **（緩衝）deprecation alias**：`patents.py` 註冊 `gpss_search` deprecation stub 一個版本週期，回 `{error_code: "TOOL_RENAMED", use: "patent_search"}`；比照者：未來任何工具改名一律留 stub。
4. **（文件化）CHANGELOG 補 `7c4330d` 的 rename 對照表**（`gpss_search`→`patent_search`，含參數對映：`databases`/`cpc`/`ipc`/`keyword` 沿用）。

## 影響範圍

- 任何依 stale 投影跑 patentworks priorsearch/screening flow 的 session：開場檢索即死。
- 放大 opencode invalid-sink 迴圈成本（該側缺 did-you-mean，見 opencode `issues/BR_20260706_invalid_sink_no_did_you_mean_for_mcp_app_tools.md`）。
- 相關前案：本 repo `BR_20260628_workflow_source_ladder_not_exhausted_skill_missing_tools.md`（skill 文件與工具實況脫節的同類病；當時是「skill 沒記載存在的工具」，本次是反向「skill 記載了不存在的工具」——同一根因：skill 與 server 介面無同步契約）。

## 驗證手段

1. 重跑投影同步後：`grep -c patent_search ~/.local/share/opencode/skills/patentworks/flows/priorsearch.md` ≥ 10 且 `grep -c gpss_search` = 0。
2. 新 session 載 patentworks → 直接呼叫 `patent_search(cpc="G08B21/04", keyword="fall detection", databases=["USA"], num=3)` 一次成功。
3. （若做 alias）呼叫 `gpss_search` 回 `TOOL_RENAMED` typed error 而非 unknown-tool。
