# PatentWorks Analysis Flow Specification (RAGBase)

本文件是專利分析流程（Analysis Flow）的核心規格與知識庫（RAGBase），定義了分析模組在 `PatentWorks` 架構下的職責邊界、資料契約，以及與 `patentmcp` 和 `docxmcp` 協作的指導原則。

---

## 一、 職責與定位 (Module Boundary)

分析層 (Analysis Layer) 是一個**與資料來源無關 (Source-agnostic) 的語意理解與特徵比對中介層**。

### 1. 解耦定位
* **檢索層 (Retrieval/Screening)** 負責「搜出前案與建表去重」；**撰寫層 (Drafting)** 負責「套用各國法域規則進行法律文件起草」。
* **分析層 (Analysis)** 則專注於「將任何來源的技術資料，正規化為特徵對照表與起草基礎 (Drafting Basis)」。

### 2. 資料來源多樣性
分析層必須能同時消化以下來源，不應假設輸入資料必定來自 `patentmcp` 檢索表：
- `retrieval_mcp`：來自 MCP 伺服器篩選後的 CSV 表格。
- `user_provided`：使用者自行貼入的交底書文字、摘要或說明書片段。
- `file`：透過 `docxmcp` 物理拆解出的本地文獻。
- `mixed`：上述來源的混合。

---

## 二、 資料契約 (Data Contract)

為了確保分析層與前後模組的相容性，必須遵循以下輸入與輸出資料契約：

### 1. 輸入契約 (AnalysisInput)
```typescript
type AnalysisInput = {
  // 分析的資料來源類型
  sourceType: "retrieval_mcp" | "user_provided" | "file" | "mixed";
  
  // 待分析的文獻或材料清單
  materials: Array<{
    id?: string;                                                  // 材料唯一識別碼（如專利公開號）
    title?: string;                                               // 材料名稱 / 專利名稱
    content?: string;                                             // 直接傳入的文字內容
    handle?: { token: string; rel: string; download_url?: string }; // 二進位檔案（PDF/Docx）的 token 指標
    metadata?: Record<string, unknown>;                           // 額外的元數據
  }>;
  
  // 分析的目標維度
  analysisGoal:
    | "technical_features" // 提取發明技術特徵
    | "novelty"            // 新穎性比對（單篇前案是否完整揭露）
    | "claim_mapping"      // 產出要件對照表 (Claim Chart)
    | "drafting_basis"     // 提取專利起草基礎
    | "landscape"          // 領域技術現況分析
    | "fto";               // 自由實施/侵權風險分析（限有效專利獨立項）
}
```

### 2. 輸出契約 (AnalysisOutput) —— 7 大核心分析維度
分析完畢後，Agent 必須輸出符合以下結構的結構化分析報告：

```typescript
type AnalysisOutput = {
  // 1. 正規化材料摘要
  normalizedMaterials: Array<{ 
    id: string; 
    title?: string; 
    gist: string; // 壓縮後的技術主旨
  }>;

  // 2. 本案/發明技術特徵表
  technicalFeatures: Array<{ 
    feature: string; 
    role: "required" | "optional" | "variant"; // 特徵角色分類
    support: string[];                         // 哪些輸入材料支持或提到此特徵
  }>;

  // 3. 要件對照對照表 (Claim Chart / Feature Matrix)
  elementMap?: Array<{ 
    feature: string; 
    references: Array<{ 
      materialId: string; 
      disclosure: string; // 前案中揭露此特徵的具體段落/內容
      gap?: string;       // 前案與本案此特徵之間的落差或技術差異
    }>;
  }>;

  // 4. 最接近前案分析
  closestPriorArt?: Array<{ 
    materialId: string; 
    reason: string;          // 判定為最接近前案的理據
    coveredFeatures: string[];  // 該前案已覆蓋本發明的哪些特徵
    missingFeatures: string[];  // 該前案遺漏/未揭露的特徵
  }>;

  // 5. 技術手段差異點歸納
  differences: Array<{ 
    point: string;        // 差異手段點
    basis: string;        // 法律/技術論證依據
    draftingUse?: string; // 起草時的使用建議（例如：寫入說明書的「發明內容」）
  }>;

  // 6. 專利起草基礎
  draftingBasis?: { 
    problem: string;      // 解決的技術問題
    solution: string;     // 採用的技術方案
    effects: string[];    // 產生的技術效果
    claimSeeds: string[]; // 請求項起草的關鍵字與限制條件種子
  };

  // 7. 專業審核警示
  reviewFlags: Array<{ 
    issue: string;                     // 潛在風險 / 不一致處 / 疑點
    severity: "low" | "medium" | "high"; // 嚴重程度
    humanReviewNeeded: boolean;        // 是否需要人類代理人/專利工程師人工介入
  }>;
}
```

---

## 三、 與 docxmcp & patentmcp 的整合實作原則

為確保中間內容生成層（Analysis Flow）的「專業性」與「執行效率」，在編排工作流時必須遵循以下三大原則：

### 1. 物理拆解與語意分析的明確分工
* **物理拆解（由 `docxmcp` 與 `patentmcp` 處理）**：
  * 利用 `patentmcp` 的 `fetch_patent_pdf` 下載專利原始 PDF。
  * 調用 `docxmcp` 的 `decompose(format=pdf)` 將專利 PDF 解構成 sections、段落文字及附圖。
* **語意分析（由 Analysis Flow 處理）**：
  * Agent 讀取拆解後的段落與 Claims，進行語意對照與特徵提取。**嚴禁將整本 PDF 的 raw content 塞入 Prompt 中**，應以摘要、引文片段與 handle 指標為主要處理介質，防止 Token 溢出與幻覺。

### 2. 降低 Token 成本的「前置去重」與「分段深讀」
* **家族去重 (INPADOC Family De-duplication)**：
  * 在分析多篇前案時，必須優先檢查是否有同家族的案件（利用 `epo_family` 或 `patentmcp` 欄位）。
  * 同一個發明家族的複數案件，**只選擇一件代表案進行深度拆解與分析**，其他成員標註為「同家族，參照代表案」，減少約 40% 的 Token 浪費。
* **分段深讀 (Shortlist Triage)**：
  * 相關性判讀（Screening）時僅讀**「摘要 (Abstract)」與「獨立項 (Claim 1)」**。
  * 只有通過初篩、確定列入相關名單（Shortlist）的少數關鍵前案，才啟動 `docxmcp` 的完整 Claims 拆解與深度 analysis。

### 3. 「壓縮蒸餾」不變式（保存 Token 理解）
* 當 Agent 讀取並分析完一篇文獻後，**必須立刻將理解沉澱為壓縮文字寫回篩選 CSV 檔案**：
  * *1-2句技術要點*：用本發明的語境，精簡描述該前案實質在做什麼。
  * *命中/落差要件*：前案有哪些本發明的元件，缺少哪些。
  * *一句話理由*：為何給予此相關度評級。
* 這個步驟可將大段的 Token 理解「固化」在結構化表格中，後續 Drafting 模組或其他 Agent 讀取表格時不需重讀原始大文件。
