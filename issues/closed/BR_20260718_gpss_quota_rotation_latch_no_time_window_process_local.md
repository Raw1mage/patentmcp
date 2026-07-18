# BR_20260718 — GPSS 帳號額度 rotation latch 缺時窗維度且 process-local（跨窗白廢帳號 + 並行擠兌）

- **狀態**: open
- **元件**: `src/patent_mcp_server/gpss/client.py`（`GPSSClient._exhausted` / `_advance_account` / `search`）
- **嚴重度**: high（直接壓低多帳號池的有效額度；並行補撈時擠兌兩組帳號）
- **回報者**: 異常偵測前案檢索專案（15,830 筆並行補撈實戰暴露）

## 1. 症狀

多帳號 GPSS 池（`GPSS_USER_CODES` 2 組）在兩種情境下有效額度遠低於物理額度：

1. **跨時窗白廢帳號**：GPSS 額度時段制（平日 08–18 窄窗 10,000 / 下班+週末寬窗 30,000，過邊界自動重置）。但一組帳號一旦在某時窗撞 `Over download quantity` 被標 exhausted，**即使 18:00 窗口翻新、額度回滿，該帳號在本 process 生命週期內永遠被跳過**，直到重啟。
2. **並行擠兌（DD-97）**：`gpss_client` 是 module singleton，`_exhausted` 是 **process-local** in-memory set。並行 subagent 各自起獨立 MCP 連線/或各撞各的偵測，都從 cursor #0 開始榨，兩組帳號同時被撞穿，彼此不知情。

## 1.5 History Review（同族 BR / 復發 / KB 命中）

- **owning spec / plan**: `patentmcp_gpss-account-rotation`（DD-1~DD-6，rotation 機制本體）。本 BR 是該 plan 的**契約缺陷延伸**——rotation 只設計了「撞牆→跳下一組→全撞穿 fail-fast」，**從未設計「額度會隨時窗回復」這條物理事實**。
- **同構**: 消費端專案 `research/anomaly-noncontact-priorart` design.md **DD-97 擠兌鐵律**（已記錄「rotation 是單次 tool call 內 in-memory 狀態，並行各自從 #0 撞穿」）—— 該 DD 是本 BR 的**症狀側觀察**，本 BR 是其**根因側修復提案**。
- **code 註解自承**（client.py:156-157）: *"An account marked exhausted stays skipped for the lifetime of this process; a restart clears it (the GPSS window resets anyway)."* —— 設計者當初明知額度會 reset，卻用「反正你會重啟」規避，把時窗維度的責任丟給運維。長駐 MCP server 場景下這假設破裂。

## 2. RCA（已 code 坐實）

| 事實 | 證據 |
|---|---|
| `gpss_client` module singleton，import 建一次活整個 process | `patents.py:157` |
| `_exhausted: set` 只有 `.add()`，全 codebase 無 `.clear()/.discard()/reactivate/window` | `gpss/client.py:174,205`；grep 全空 |
| exhausted 記的是「cursor index 撞過牆沒」，非「帳號×時窗剩餘額度」 | `_advance_account` L201-210 |
| 偵測 reactive：只在 GPSS 回 `Over download quantity` 才 mark | `search()` L385-393 `_is_quota_exhausted` |
| process-local，跨 subagent 不共享 | singleton 在各自 process |

**根因一句話**：exhausted latch 與額度的物理真相（**帳號級 + 時窗級**）錯開兩個維度——它記 process 而非帳號、記布林而非時窗。

## 3. 修復提案（使用者已定調：時窗復活 ＋ 跨 process 共享狀態表）

核心設計：**用 `window_key` 給 exhausted 記錄加時間維度，一個機制同時解兩病。**

1. **時窗鍵**：`window_key(now)` = GPSS 重置邊界量化（平日 08:00 / 18:00、週末各為一段）。exhausted 記錄鍵改成 `(account, window_key)`。
2. **隱式復活**：跨邊界 `window_key` 變 → 舊時窗記錄自動失配 → 帳號重新可用，**無需顯式 clear**。過度復活自癒——真沒恢復的帳號下次撞 `Over download quantity` 立即重標。
3. **跨 process 共享**：exhausted 記錄從 process-local set 提升到 **`patentdb/` bind-mount 內的 sqlite sidecar**（例：`gpss_quota_state.sqlite`，schema `(account TEXT, window_key TEXT, exhausted_at INT, PRIMARY KEY(account,window_key))`）。並行 subagent 共讀共寫 → 一組被撞穿，其他 process 立即看到、直接跳，根治 DD-97 擠兌。
4. **（optional 加值）proactive budget**：GPSS 按輸出筆數計，可在每次 search 後 `consumed[(account,window)] += records`，撞牆前主動跳帳號。需在 `search()` 回傳路徑埋計數點，工程量較大，可後續迭代。

### 施作前提（已坐實，降低施作風險）

- tests **未綁** `_exhausted`/`_advance_account` 內部名，只綁公開 `_is_quota_exhausted` 與 rotation **行為**（`test_gpss_rotation.py` TV-3/TV-4/TV-5/exhausted_skipped）→ 內部可安全重構，但須保這些行為契約綠。
- uvicorn 單 worker（非多 worker），跨 process 需求純來自並行 subagent 各自 MCP 連線。
- `patentdb/` 已 rw bind-mount + WAL side files（`docker-compose.yml:64,67-72`），sidecar sqlite 落此天然可行、跨 `--force-recreate` 存活。
- `_resolve_db_root()`（`patentdb_store.py:24`）可複用定位落點；`patentdb_store.py` 未 import gpss，反向 import 安全。

### 驗證計畫

- 新增 test：`test_tv3` 後模擬跨 `window_key` 邊界 → 被標 exhausted 的 A1 在新時窗**重新被嘗試**（現行為是永遠跳過）。
- 新增 test：兩個 GPSSClient 實例（模擬並行 process）共享 sidecar → 一個標 A1 exhausted，另一個下次 search 直接跳過 A1。
- 保回歸：既有 TV-1~TV-5 全綠。

## 4. Workaround（修復落地前，消費端現行對策）

DD-98 四 rail 分工：CN 走 GPSS `patent_search` 序列（不並行同帳號）、US/TW-EPO 走 EPO（不吃 GPSS 額度）、TW-appno 走 GPSS4 web 會員登入（零 API 額度）。以 rail 隔離規避擠兌，但這是繞行、非根治。
