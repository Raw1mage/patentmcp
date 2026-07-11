# Design: patentworks_iterative-convergence-search

## Context

影像式人類異常偵測前案檢索的方法論從「固定事件×場域矩陣笛卡兒積」改為「資料驅動逐輪收斂演算法」。前次 campaign 已跑出 58 塊固定矩陣（US27/TW13/CN18），但使用者判定該結構預設軸向、無法證明覆蓋完整，改採本 spec 的逐輪收斂。

## Goals / Non-Goals

**Goals**
- 以 IPC 聯集為唯一固定錨，逐輪加軸收斂到每個標的 <1000。
- 產出可證明「所有可能情況都涵蓋」的數字表證據鏈。
- 全程 GPSS 官方、真本國案、零 EPO fallback 造假。

**Non-Goals**
- 不做完整笛卡兒積（只對超標者下鑽）。
- 不預設固定軸向。
- 不含報告本體撰寫（下游流程）。

## Architecture

逐輪收斂檢索是一個**資料驅動的固定點迭代**：以 IPC 聯集為錨，逐輪增加關鍵字軸做 AND 限縮，直到每個標的的 total 收斂到 <1000。

```
輸入: 關鍵字池 (人/事/時/地/物, 三語)  +  IPC 聯集 (固定錨)
                    │
        ┌───────────┴───────────┐
        │  第 N 輪                │
        │  對「第 N-1 輪 ≥1000」 │
        │  標的 + 1 個新關鍵字軸  │  → round-N-log.jsonl (數字表)
        │  跑 N-tuple AND         │
        └───────────┬───────────┘
                    │ 篩 total ≥ 1000
                    ▼
        仍超標 → 進第 N+1 輪 (再 +1 軸)
        全 <1000 → 收斂完成 → 家族去重全池
```

### 收斂狀態機 (GRAFCET 語意)
- **S1 輪次生成**: 產生本輪 query 集合（第 1 輪 = 單關鍵字；第 N 輪 = 對超標者笛卡兒式加 1 軸）。
- **S2 執行檢索**: 每 query 跑 `patent_search` num=1 只取 total，記入 round-N-log.jsonl。
- **S3 收斂判定**: total <1000 → 標記 converged；≥1000 → 標記 over1000 進下一輪。
- **S4 終止**: 無 over1000 標的 → 收斂完成，進家族去重。

## Decisions

### DD-1: 唯一固定軸 = IPC 聯集，其餘自由組合
IPC 13 群聯集是每條 query 的必備錨。人/事/時/地/物為自由可組合軸，不預設固定軸向。理由：使用者 2026-07-09「IPC 固定必備，其餘自由排列組合」。IPC 本身已涵蓋多模態感測分類（G06V/G06T/H04N 視覺 + G01S 雷達/聲學 + A61B 生醫），故 devices keyword 軸對 total 影響小（A/B 對照 CN-E1 4276 vs 4319），但保留作組成對照。

### DD-2: <1000 為唯一收斂判準
任一組合（即使單項）total <1000 即算該標的涵蓋完整。理由：使用者定案「任何一個檢索組合，即使只有單項，能限縮到 1000 以下就算數」。1000 是 GPSS 可全量下載檢視的實務上限。

### DD-3: 逐輪加軸下鑽，非笛卡兒積
第 N 輪只對「第 N-1 輪仍 ≥1000」的標的下鑽，增加 1 個關鍵字軸。避免組合爆炸（37 單項全笛卡兒積 = 天文數字）。理由：使用者「針對數量超過者做兩兩 and…再針對仍超過者做三關鍵字…依此類推」。

### DD-4: 第 1 輪 keyword_field = TI/AB（非 CL 全文）
GPSS `patent_search` 三段以上 AND + CL 全文會穩定 parse error（CN E4/E5 已踩過）。第 1 輪求數字表，TI/AB 足夠。收斂到後輪小格再視需要升 TAC。

### DD-5: 時間軸 T 保留於池但列低優先
即時/夜間類詞當限縮軸很弱（幾乎每篇即時偵測都寫 real-time），第 2 輪起若用 T 軸限縮效果差。保留於池但收斂時優先用物/事/地/人軸。

### DD-6: GPSS 官方唯一主路徑，禁 EPO fallback 造假
databases 過濾必須落實：US=USA,USB｜TW=TWA,TWB｜CN=CNA,CNB。EPO fallback 回非本國案視為造假（天條）。此為前次 root cause（databases=["TW"] 非法碼 → fallthrough EPO → CN 噪音）的固化防呆。

## Code Anchors

- `output/priorart_anomaly_vision/01_search/round1_keyword_pool.md` — 第 1 輪關鍵字池字典
- `output/priorart_anomaly_vision/01_search/round1-log.jsonl` — 第 1 輪數字表（已跑 9/111）
- `src/patent_mcp_server/gpss/client.py:26-28` — DB 代碼常數（DB_US/DB_CN/DB_DEFAULT）
- `skills/patentworks/scripts/_lib/search_audit.py` — rigor gate（DD-7 compound boolean 已修）

## Submodule / Cross-spec Refs

- `plans/patentworks_search-rigor-contract/` — rigor gate owning spec（boolean_combos proxy）
- `plans/patentmcp_search-dispatcher/` — patent_search 來源梯路由

## Risks / Trade-offs

- **輪次爆炸風險**:若過多標的持續 ≥1000,第 3+ 輪的三/四關鍵字組合數會膨脹。緩解:DD-3 只對超標者下鑽,且優先用高鑑別力軸（事/地）而非弱軸（時）。
- **GPSS parse error**:三段以上 AND + CL 全文穩定失敗（DD-4）。緩解:第 1 輪 TI/AB,收斂後小格再升 TAC。
- **IPC 吸收 devices 軸**:IPC 已涵蓋多模態感測分類,純加 devices keyword 對 total 影響小（DD-1 A/B 對照）。取捨:仍保留 devices 軸作池組成對照,不因 total 無感而移除。
- **收斂 vs 召回取捨**:<1000 硬門檻可能把某些寬事件面向切得過細。緩解:驗收看「每標的有出口」而非「單格召回極大化」。

## Critical Files

- `output/priorart_anomaly_vision/01_search/round1_keyword_pool.md` — 第 1 輪關鍵字池（收斂字典）
- `output/priorart_anomaly_vision/01_search/round1-log.jsonl` — 第 1 輪數字表
- `src/patent_mcp_server/gpss/client.py` — DB 代碼常數 + GPSS 檢索
- `skills/patentworks/scripts/_lib/search_audit.py` — rigor gate（landing plane SSOT）
