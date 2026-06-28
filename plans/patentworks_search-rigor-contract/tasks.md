# Tasks: patentworks_search-rigor-contract

## 1. search_audit 核心工具（patentmcp）
- [x] 1.1 新增 `src/patent_mcp_server/search_audit.py`：matrix-log.jsonl parser + 五維覆蓋率計分（純函式，零網路）
- [x] 1.2 實作門檻邏輯：硬地板（DD-2）+ campaign 覆寫讀取 + PASS/WARN/FAIL 判定 + gaps 清單
- [x] 1.3 `patents.py` 加 `@mcp.tool() search_audit(matrix_log_path, campaign_path?)` 薄包裝（比照 screening_table 接線）

## 2. 單元測試 + 回歸驗證
- [x] 2.1 寫 3 組 fixture matrix-log.jsonl（充分 PASS / 缺 USPC FAIL / 筆數不足 FAIL），斷言 verdict + gaps
- [x] 2.2 重啟 patentmcp server，`GET /tools` 確認 search_audit 註冊成功、schema 正確
- [x] 2.3 回歸驗證：用 TWCID 既有薄檢索反推 matrix-log 餵 audit，確認被 FAIL（證明這道閘真能擋下這次問題）

## 3. priorsearch.md 改寫（檢索強度契約）
- [x] 3.1 §0：matrix-log.md → matrix-log.jsonl，補 schema（DD-1）
- [x] 3.2 新增 §「檢索強度契約」：門檻表（DD-2）+ campaign 覆寫/逃生門規則
- [x] 3.3 §2：USPC 升一級限縮軸，與 IPC/CPC 並列入矩陣（DD-5 表格）
- [x] 3.4 §3.B step4 複核閘語意反轉：先跑 search_audit 必 PASS、再驗 CSV（DD-4）
- [x] 3.5 §3.D step8：交付前 search_audit 強制閘（與 docx probe ok=True 並列）

## 4. 資料樹統一（消除平行管線）
- [x] 4.1 SKILL.md §Data Tree 改為指標，指向 priorsearch.md §0 為單一真相（DD-5）
- [x] 4.2 移植 candidates.csv 欄位格式 + 5 張圖命名到 priorsearch.md §0；fig2 命名修正（DD-6）
- [x] 4.3 通讀兩檔，確認無殘留的第二套目錄定義

## 5. 發布 + 收尾
- [x] 5.1 republish skill 到 XDG projection，diff 確認同步
- [x] 5.2 event_record 收尾（決策/驗證/architecture sync）
- [x] 5.3 plan_advance 至 verified
