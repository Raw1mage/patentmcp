# Flow: Analysis (專利技術分析工作流)

本工作流旨在將任意來源的專利材料、產品特徵或技術交底書進行結構化分析。此流程與資料來源無關（Source-agnostic），但會依據不同的**分析目的（Scenarios）**，區分為四種獨立的分析子流程，各自定義專屬的輸入、輸出與分析比對步驟。

---

## 核心原則與不變式

1. **資料來源無關**：不應假設資料必來自 `screening` 或 `patentmcp`；可直接處理使用者提供的純文字、第三方論文、或檔案 Token Handle。
2. **Handle-first 限制**：針對大型專利全文、PDF、完整 claims 等，應利用 `stage_file` 或 download_url handle 傳遞，僅在 Agent context 中保留正規化的 gist (摘要) 或核心特徵，避免 bytes 灌爆 context。
3. **無捏造證據**：所有技術特徵比對、要件對照表與落差分析，必須嚴格基於輸入材料，不可憑空捏造。

---

## 情境一：前案檢索與可專利性分析 (Prior Art & Patentability)

### 1.1 目的
針對給定的技術想法、具體特徵或揭露文件，與候選前案進行比對（102 新穎性與 103 進步性比對），評估其可專利性並提煉起草說明書所需的技術特徵與撰寫基礎。

### 1.2 輸出範本
- 生成分析報告時，Agent 應嚴格對齊並套用：[前案檢索與可專利性比對報告範本](../reference/analysis/prior-art-template.md)。

### 1.3 輸入契約 (PriorArtInput)
- `sourceType`: `"retrieval_mcp" | "user_provided" | "file" | "mixed"`
- `inventionDisclosure`: 本案技術想法或發明材料（發明名稱、背景痛點、技術方案、效果等）。
- `priorArtMaterials`: 候選前案清單，每筆包含：
  - `id`: 專利號或文獻識別碼。
  - `title`: 文獻標題（選填）。
  - `content` 或 `handle`: 內容文字或檔案 Token。

### 1.4 輸出契約 (PriorArtOutput)
- `inventionFeatureMatrix`: 本案關鍵技術要件拆解，標明每個特徵是 `"required"`（獨立項必要特徵）或 `"optional"`（從屬項附加特徵）。
- `elementMap`: 102/103 要件對照表。對照前案文獻是否公開本案特徵（標明：揭露/未揭露/部分，並附上段落出處）。
- `closestPriorArt`: 最接近前案之 ID、判定原因，以及被其覆蓋之特徵與本案的區別技術特徵（Gaps）。
- `draftingBasis`: 撰寫基礎，包含：
  - `problem`: 解決的技術問題。
  - `solution`: 核心技術手段組合。
  - `effects`: 有益效果。
  - `claimSeeds`: 供起草請求項使用的種子詞彙或核心句。
- `reviewFlags`: 標示 102 新穎性風險、103 進步性風險、交底書邏輯斷層等疑點（含嚴重度與是否需要人類複核）。

### 1.5 分析步驟
1. **發明特徵拆解**：閱讀技術材料，拆出具備專利法意義的技術特徵點，建立 `inventionFeatureMatrix`。
2. **前案要件對照**：讀取前案文獻（若為 Handle 則用工具讀取），逐一比對本案特徵，填寫 102/103 要件對照表（`elementMap`）。
3. **102 與 103 評估**：
   - 檢查是否有單篇前案完全揭露本案獨立項所有必要特徵（102 新穎性/Anticipation 問題）。
   - 評估是否只需結合複數前案，即可輕易達成該特徵組合且效果可預期（103 進步性/Obviousness 問題），並尋找非預期技術效果的抗辯點。
4. **撰寫提煉**：總結區別技術特徵，建立 `draftingBasis` 與標記 `reviewFlags`。

---

## 情境二：侵權迴避 / 自由實施分析 (Freedom to Operate, FTO)

### 2.1 目的
評估要上市或研發的產品/技術，是否會侵犯目標市場的「他人有效專利」，並在有風險時提供產品修改（迴避設計）建議。

### 2.2 輸出範本
- 生成分析報告時，Agent 應嚴格對齊並套用：[FTO 分析報告範本](../reference/analysis/fto-template.md)。

### 2.3 輸入契約 (FTOInput)
- `productDescription`: 自家產品的具體系統架構、元件組成、或方法步驟描述。
- `activePatents`: 目標市場的他人有效專利清單，每筆必須包含：
  - `id`: 專利號。
  - `claims`: 該專利的獨立權利要求（Independent Claims）全文。
  - `status`: 專利法律狀態（必須為有效或公告中）。

### 2.4 輸出契約 (FTOOutput)
- `productFeatures`: 自家產品拆解出的具體特徵。
- `infringementChart`: 侵權比對表。將產品特徵與各篇專利的**獨立項特徵**進行逐一比對。
- `riskEvaluation`: 侵權風險等級（High/Medium/Low）。
- `designAroundOptions`: 針對 High/Medium 風險專利提供的迴避設計方案。

### 2.5 分析步驟
1. **產品特徵解析**：將產品說明拆解為一個個具體、可比對的技術元件或步驟。
2. **專利獨立項解構**：提取他人專利的「獨立項」，將其權利要求拆解為複數個特徵點。
3. **全要件比對（All Elements Rule）**：對比產品是否包含專利獨立項的所有特徵。
4. **擬定迴避策略**：針對有風險的專利，給出「省略特徵」、「替換非等效元件」的具體迴避指引。

---

## 情境三：技術現況與地圖分析 (Landscape)

### 3.1 目的
宏觀分析某個技術領域的專利分布、大廠競爭格局與研發空白地帶（技術白地）。

### 3.2 輸出範本
- 生成分析報告時，Agent 應嚴格對齊並套用：[技術地圖分析報告範本](../reference/analysis/landscape-template.md)。

### 3.3 輸入契約 (LandscapeInput)
- `searchQuery` 或 `cpcCode`: 目標分析領域。
- `patentDataset`: 該領域的專利清單，每筆包含：
  - `id`: 專利/公開號。
  - `applicant`: 申請人。
  - `pubYear`: 公開年份。
  - `abstract`: 摘要。
  - `cpcCodes`: 分類號（選填）。
- `dimensionPreference`: 偏好的分類角度。

### 3.4 輸出契約 (LandscapeOutput)
- `technicalClusters`: 主題分群。將所有專利依照技術手段/痛點分類的統計。
- `keyPlayerMatrix`: 競爭對手布局矩陣。
- `evolutionTimeline`: 技術演進歷程。
- `technologyWhiteSpaces`: 技術白地與機遇。

### 3.5 分析步驟
1. **語意摘要標籤化**：分批讀入專利清單的摘要與分類號，識別其所屬的技術子領域。
2. **技術手段與玩家交叉統計**：統計各申請人在不同技術群組下的專利占比，找出領頭羊。
3. **年份演進分析**：分析技術類別在時間軸上的專利數量變動。
4. **尋找技術白地**：通過交叉比對，找出技術地圖上的空白點，撰寫報告結論。

---

## 情境四：專利無效分析 (Validity / Invalidity)

### 4.1 目的
針對某一件特定的他人專利（標的專利），尋找並比對其申請日之前的公開文獻，以作為提起無效宣告、推翻其專利效力的證據。

### 4.2 輸出範本
- 生成分析報告時，Agent 應嚴格對齊並套用：[專利無效分析與證據比對表範本](../reference/analysis/invalidity-template.md)。

### 4.3 輸入契約 (InvalidityInput)
- `targetPatent`: 標的專利資訊，包含：
  - `id`: 專利號。
  - `criticalDate`: 標的專利之優先權日或申請日（截止日）。
  - `claims`: 需要被無效的權利要求（Claims）全文。
- `priorArtCandidates`: 在截止日之前公開的潛在前案文獻，每筆包含：
  - `id`: 文獻公開號。
  - `pubDate`: 公開日期。
  - `content` 或 `handle`: 文獻內容。

### 4.4 輸出契約 (InvalidityOutput)
- `targetClaimConstruction`: 標的專利請求項的特徵點拆解。
- `invalidityClaimChart`: 無效對照矩陣。
- `evidenceStrength`: 證據強度判定（Anticipation/Obviousness/Weak）。
- `argumentDraft`: 無效抗辯文字草稿。

### 4.5 分析步驟
1. **權利要求解析（Claim Construction）**：將標的專利的獨立項與從屬項進行極細的特徵點拆解。
2. **前案資格篩選（Critical Date Gate）**：確認前案文獻公開日皆早於標的專利的截止日。
3. **證據逐項比對**：逐一比對合規前案，將前案的具體說明書文字與標的特徵對照，填入對照表。
4. **抗辯論述草擬**：評估證據強度，草擬無效論述。
