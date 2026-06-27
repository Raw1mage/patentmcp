# Event: PatentWorks 獨立分析工作流 (Analysis Flow) 實作

## 需求
- 實作資料來源無關（Source-agnostic）的獨立「分析（Analysis）」技能，以解決分析能力與檢索篩選強耦合的問題。
- 使分析模組能獨立處理專利檢索產出（如 scored CSV）、使用者直接提供材料、或兩者混合的技術 disclosure，並輸出符合 `AnalysisOutput` 的結構化撰寫基礎給起草（Drafting）模組。

## 範圍

### IN
- 建立新流程檔案：[analysis.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/analysis.md)。
- 修改路由設定：[SKILL.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/SKILL.md)。
- 調整前後對接流程：[screening.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/screening.md) 與 [drafting.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/drafting.md)。
- 同步更新架構規格：[specs/architecture.md](file:///home/pkcs12/projects/patentmcp/specs/architecture.md)。

### OUT
- 不修改 python `patentmcp` MCP 伺服器的工具定義或底層程式碼。

## 任務清單
- [x] 1. 建立新分析流程檔案 `skills/patentworks/flows/analysis.md`
- [x] 2. 修改 `skills/patentworks/SKILL.md`（新增 analysis 意圖與路由）
- [x] 3. 修改 `skills/patentworks/flows/screening.md`（新增 handoff 指引）
- [x] 4. 修改 `skills/patentworks/flows/drafting.md`（新增讀取 AnalysisOutput 指引）
- [x] 5. 進行自我驗證，並更新事件日誌的 Debug Checkpoints
- [x] 6. 比對與同步架構規格 `specs/architecture.md`

## Debug Checkpoints

### Baseline
- 當前 `patentworks` 技能只有 `disclosure`、`screening` 和 `drafting` 工作流，缺乏獨立的 `analysis` 流程。
- 分析需求耦合於 `screening.md` 中，使得非篩選來源（例如使用者直接提供的技術 disclosure 或前案）無法單獨進行分析。

### Execution
- 成功建立了全新的分析流程檔案：[analysis.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/analysis.md)。該檔案完全定義了符合 `design.md` 的 `AnalysisInput` 及 `AnalysisOutput` 資料契約。
- 修改了技能主控檔：[SKILL.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/SKILL.md)，在描述中加入第四項分析任務，並更新管線圖與意圖路由對照表。
- 調整了篩選流程檔案：[screening.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/screening.md)，在結尾新增與分析流程的 `## 銜接` 規則。
- 重構了起草流程檔案：[drafting.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/drafting.md)，使起草步驟 `## 1. 揭露與分析擷取` 優先消費 `AnalysisOutput` 的結構化資料，並在前案定位步驟 `## 2. (選)前案定位與差異劃界` 中將前案分析職責導向 `analysis.md`。
- **(新增) 建立並對齊分析範本**：
  * 在 `skills/patentworks/reference/analysis/` 下建立了 4 個符合專利實務的 Markdown 報告範本：
    1. [prior-art-template.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/reference/analysis/prior-art-template.md)（前案檢索與可專利性比對報告範本，包含 102/103 對照與 Claim Seeds）
    2. [fto-template.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/reference/analysis/fto-template.md)（自由實施侵權比對表與迴避方案）
    3. [landscape-template.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/reference/analysis/landscape-template.md)（技術地圖分群與白地布局建議）
    4. [invalidity-template.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/reference/analysis/invalidity-template.md)（無效宣告特徵拆解與關鍵日證據對照）
  * 在 [analysis.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/analysis.md) 中，將這四個範本檔案以輸出範本（`Output Template`）連結至各個對應情境段落。

### Validation
- **流程語意完整性驗證**：
  1. 檢查 [SKILL.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/SKILL.md) 成功在四種任務中將 `flows/analysis.md` 包含在內，且語彙及流程邏輯符合 `disclosure -> screening -> analysis -> drafting` 管線。
  2. 檢查 [analysis.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/analysis.md) 設定的輸入/輸出參數，其完全涵蓋了特徵向量、要件對照表、差異點、最接近前案、起草基礎（claimSeeds等）與 Review Flags 等關鍵欄位，符合資料來源無關（Source-agnostic）的設計原則。
  3. 檢查 [screening.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/screening.md) 與 [drafting.md](file:///home/pkcs12/projects/patentmcp/skills/patentworks/flows/drafting.md) 的修改部分，兩者對 Analysis 模組的呼叫與承接邏輯具備一致的連結。
  4. 驗證新建立的四個範本檔案，皆已準確使用專利分析的產業標準與法規比對模型。
- **無干擾與破壞性變更**：
  * 本次修改皆位於 `skills/` 目錄下的引導 Markdown 檔案，無影響任何 python 後端 `patentmcp` 的代碼結構。專案編譯與執行不受影響。
