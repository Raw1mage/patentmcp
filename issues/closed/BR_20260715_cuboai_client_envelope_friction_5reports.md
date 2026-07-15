# BR: cuboai client 首次外部連線 5 份使用磨擦回報 — envelope-層失敗 friction log 全漏抓

**嚴重度**：高（含高/中/低 5 子項）　**狀態**：Closed（§0 核心 friction 假陰性 + 延伸發現兩缺陷 + 子項 04 影像 fallback 已修，2026-07-15；剩 05/01 為低優先 remaining，另見文末）
**來源**：cuboai client（Windows 11 / Claude Code，`.mcp.json` → `https://cms.thesmart.cc/patentmcp/mcp` streamable-http），首次以外部連線產製「Cubo AI 專利技術精讀報告」（15 件公報、7 技術族群）時回報。原件 `~/GoogleDrive/Projects/cuboai/issues/{01..05}-*.md`。
**Target**：patentmcp 工具層 + `_http_app.py` gateway/檔案端點 + `figure_extract.py` + friction log 攔截語義

---

## 0. Meta 發現（本 BR 最重要的一條）：envelope-層失敗，friction log 全漏抓

同 session 剛上線的 unified observability log（`plan observability_tool-friction-log`）對這一輪工作報 **0 friction**，但 client 實際踩到 5 個磨擦。逐一對照根因：

| 子項 | client 遇到 | 工具實際回傳 | friction log 為何漏 |
|---|---|---|---|
| 01 | 工具叫不到 | （沒進到 patentmcp） | 在 client/gateway 側，伺服器沒收到 |
| 02 | download_url 缺 prefix → 下載到 HTML | **`200 + text/html`**（SPA catch-all） | `success:true`，無 exception |
| 03 | 代表圖對 US/CN 硬失敗 | **`{"success": false, "error": "..."}`** | 回 error envelope，不 raise |
| 04 | poppler/無文字層失效 | error envelope | 同上，不 raise |
| 05 | US claim1 空 | **`{claim1_empty: true}`** | 這是「正常回傳」 |

**根因**：friction log 目前只攔 (a) 工具拋 exception、(b) absorb 一處顯式埋點。而 client 真正踩的磨擦全是 **「工具回 `success:false` / error envelope / 空欄旗標」的語意層失敗** —— 它們不拋 exception，exception 攔截層看不到；access log 只看到 200（BR02 的 HTML 也是 200）。這印證 plan 的 DD-2「靜默磨擦需顯式埋點」覆蓋不足。

**建議（往後單獨開 plan 修 friction log）**：在 `friction_tool` wrapper 補一層**回傳值檢查** —— 工具回 dict 且 `success == false`（或帶 `error` / `error_code` / `claim1_empty` 等旗標）時，自動記一筆 `kind="silent"`。讓 02/03/04/05 這類 envelope 失敗自動落地，不必逐處埋點。

---

## 同族復發回顧（code-thinker §3 BR 受理前置）

**這 5 份不是新問題，多數是已 closed 舊 BR 的復發或未修盡 —— 復發本身即證據，先前修的是症狀。**

| 子項 | 同族舊 BR | 定性 |
|---|---|---|
| 01 | `closed/BR_20260628_tools_not_surfaced_gpss_uspc_family_claim_gaps`（configured mcp 沒 patentmcp） | 同構復發 —— client/gateway 側能力曝光，非伺服器故障 |
| 02 | 無同族 | **新根因** —— gateway base path 未注入 + catch-all 該回 404 |
| 03 | `closed/BR_20260629_cn543_wrong_figure_silent_fallback`、`closed/BR_20260628_drawing_concurrency_scraping_remediation`（P1 gpss→P2 gpatents→P3 PDF 圖梯）、`BR_20260712_orchestrator_skipped_patentworks_probe` | 未修盡 —— 非 TW 自動降級從未真正接上 |
| 04 | `issue_20260706_figure_extract_dir_ownership_and_scanned_pdf_no_ocr`、`closed/BR_20260628_figure_pdf_tooling §C`、`closed/BR_20260628_workflow_source_ladder_not_exhausted` | 反覆第 N 次 —— 掃描件無 OCR/影像式 fallback |
| 05 | `closed/BR_20260628_tools_not_surfaced §D`（已加 `claim1_empty` 旗標）、`closed/BR_20260627_anomaly_detection §3` | 旗標已加但體驗未閉環 |

**共通契約裂縫**：02/03/04 全指向同一條 —— 「工具回 `success:false` / 回 200-HTML / 回空旗標，而非讓呼叫端知道發生了磨擦」。與 §0 meta 發現同源。

---

## 01 — 工具未載入 Agent session，需自行完成 MCP handshake（高，已繞過）

**現象**：`.mcp.json` 已設 patentmcp（streamable-http），但 session 內工具搜尋 `patentmcp` 回「查無」，等於「設定好卻叫不到工具」。
**繞過**：client 自行以 stdlib HTTP 實作 MCP streamable-http 握手（`initialize` → 取 `mcp-session-id` → `notifications/initialized` → `tools/list`/`tools/call` 皆帶 session-id，回應為 SSE 自行解析）。
**根因判定**：這是 **client/gateway 端能力曝光**問題，非 patentmcp 伺服器故障（伺服器側 access log 這一輪明明有 opencode/Python-urllib/curl 三種來客成功握手）。
**patentmcp 側可做**：README / landing 提供「Claude Code / Agent 連線檢查清單」+ 最小握手範例（含「直接 POST tools/list 未先 initialize → `-32600 Missing session ID`」的明確提示）。

## 02 — download_url 缺 `/patentmcp` gateway 前綴 → 下載到 HTML 而非檔案（高，已找到根因）

**現象**：工具回的 handle `download_url` 形如 `/files/{token}/blob/{rel}`（後端根路徑相對 URL）。直接接 host（`https://cms.thesmart.cc` + download_url）下載會得到 **2270 bytes 的 `text/html`**（SPA index），而非檔案本體。
**client 實測證據**（同一 token，`US10959646B2.pdf`）：

| URL | status | content-type | size |
|---|---|---|---|
| host + download_url（無前綴） | 200 | **text/html** | 2270 |
| host + `/patentmcp` + download_url（有前綴） | 200 | application/pdf | 2,032,803 |

**根因（雙層）**：
1. `download_url` 產生於 `_token_store.py:111` / `_file_server.py:114`，回**後端根路徑**相對 URL `/files/...`，不含 gateway 掛載點 `/patentmcp`。`_http_app.py:670-675` 的 NOTE 明載這是**刻意**保持相對（設計假設「UDS gateway 前綴會自動補」），但 client 直連時前綴沒補上。
2. 頂層 SPA catch-all 對任何未匹配路徑回 `200 + index.html`（那 2270 bytes），而非 404 —— 讓「路徑錯」偽裝成「下載成功」，最難察覺。
**繞道（已驗證）**：下載前補 `/patentmcp` 前綴 + 存檔後檢查 magic bytes（PDF=`%PDF`、PNG=`\x89PNG`）偵測誤存 HTML。
**建議修**：(1) 工具回**完整絕對 URL**，或回**已含 gateway 前綴**的相對路徑（後端注入 gateway base，如透過 `X-Forwarded-Prefix`）；(2) 檔案端點對無效 token/路徑回 **404 或 JSON 錯誤**，不落入 SPA catch-all 回 200-HTML。

## 03 — 代表圖工具實為「僅限 TW」，非 country-agnostic，批次逾時（高，已找到根因）

**現象**：`gpss_download_representative_figure`（描述宣稱 country-agnostic）對 US 公報幾乎全數失敗：`{"success": false, "error": "GPSS result list has no row matching the requested patent — refusing to fall back to a neighbour row."}`。本次 12 件 US 全敗、3 件 CN 有 1 件（CN110874560A）亦敗。`patentmcp_batch_download_figures` 對 15 件一次呼叫 >2 分鐘逾時。
**client 實測**（同工具）：US 各種號碼格式全 failed；`TWI721885B`/`TW202142166A` success。
**根因**：此工具驅動 TIPO GPSS 明細/圖式頁，圖式家族只有 **TW（GPSS 母體）** 穩定命中。對 US/CN，GPSS 號碼查詢的 result list 無精確吻合列，工具（正確地）拒絕取相鄰列 → 硬失敗，換號碼格式無效。批次逾時是同根因 × `Concurrency=1 + pacing` 對 15 個必敗查詢串行所致。
**繞道（已驗證 15/15）**：改走 `fetch_patent_pdf` → 補 `/patentmcp` 前綴下載 PDF → 本地 PyMuPDF 偵測圖面頁裁切（見 04）。次繞道：`epo_family(pubno)` 找 TW 同族成員再呼叫 GPSS。
**建議修**：(1) 非 TW 且 GPSS 無命中時**自動改走 EPO OPS images / Google patentimages**，或誠實在描述標「主要支援 TW」；(2) 內建族群回退（INPADOC family 找 TW 成員取圖）；(3) 批次工具跳過必敗來源、支援部分成功回傳、避免整批序列化 pacing 逾時。

## 04 — `extract_representative_figure` 需 poppler 且對無文字層 PDF 失效（中，已找到根因）

**現象**：(1) 該工具回 `TOOL_LANDED` 要求本地跑 `figure_extract.py`（R13 landing plane，合規）；(2) 腳本硬相依 poppler CLI，Windows 預設無 → `MISSING_DEPENDENCY`；(3) 即使裝 poppler，`fetch_patent_pdf`（google_citation）取得的公報 PDF 多為影像掃描、無文字層，定位器全盤失效。
**根因**：`figure_extract.py` 定位策略 = `pdftotext` 抽文字 → 比對 `FIG.1/图1/圖1` → reference-numeral 密度。整條建立在「PDF 有文字層」之上。實測 `US20230118938A1.pdf`（13 頁）PyMuPDF `get_text()` 每頁 0 字元 → 落 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT`，一張圖產不出。根因二：(a) 平台相依 poppler（Windows 不友善）；(b) 演算法假設有文字層。
**繞道（已驗證 15/15，純 PyMuPDF 免 poppler，影像式）**：每頁 90dpi 灰階算列投影 → 依「有墨水列連續段(run)數」分文字頁(nruns 大)vs 圖面頁(nruns 小)→ 判圖面 `0.002≤暗比≤0.11 且 nruns≤16 且 短run≤18` → 取最長連續圖面段首頁 → bbox 裁白輸出 200dpi PNG。
**建議修**：(1) `figure_extract.py` 增「無文字層」影像式後備（像素投影/連通區塊），不只靠 pdftotext；(2) 提供純 PyMuPDF（免 poppler）路徑降跨平台相依；(3) 偵測無文字層時主動改走影像式，而非回 `NO_FIGURE_PAGE_BUT_IMAGES_PRESENT` 讓使用者卡住。

## 05 — `patent_search` 之 US claim1 多為空，需再呼叫取回（低，已繞過）

**現象**：`patent_search(applicant="YUN YUN AI BABY CAMERA", num=50, source=gpss)` 取 15 筆，其中 3 筆 CN + 1 筆 US 公開含 claim1，其餘 11 筆 US 公報 `claim1` 為空且帶 `claim1_empty:true`（欄位長度僅約 19 佔位）。
**繞過**：對缺項清單呼叫 `ppubs_batch_get_claims(publication_numbers=[...])` 一次補回（source 多為 tipo），併回原記錄。運作正常。
**建議修**：(1) `patent_search` 提供 `include_claim1=true` 選項，在來源支援時一併回帶；(2) 或對 `claim1_empty:true` 筆數給明確提示 + 補齊建議工具。
**環境註記（非缺陷）**：Windows console cp950 輸出 CJK 會 `UnicodeEncodeError`；設 `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` 或寫 UTF-8 檔即可。

---

## 延伸發現（同族缺陷，修 BR03 時在批次工具內發現，記錄不擴大戰線）

修 03 單件降級時，讀 `patentmcp_batch_download_figures`（patents.py:3908）發現兩個獨立缺陷，**超出 client 這輪回報範圍**（client 核心是單件），記錄待後續處理：

1. **批次 PDF fallback 已隨 R13 斷鏈**：`:3975` GPSS miss 後呼叫 `extract_representative_figure(pub)`，但 patentworks R13 兩平面已把該工具改為回 `TOOL_LANDED` redirect（landing plane，`patents.py:1868`）——批次拿到的是 redirect envelope 不是圖，PDF fallback 實際不再產圖。批次要嘛內部改走 `fetch_patent_pdf` + 標 landed，要嘛整體也回 landed redirect。
2. **批次 cooldown 用 `/tmp`（違反 XDG 天條）**：`:3919` `cooldown_file = os.path.join(tempfile.gettempdir(), "patent_cooldown.json")` → 落 `/tmp`（world-readable）。應改 `$XDG_RUNTIME_DIR`/`$XDG_CACHE_HOME`。

單件 `gpss_download_representative_figure` 的降級已修（本 session）；批次重構待後續 plan。

---

## 修復排程（本 session）

- [x] 02 gateway prefix：`_handle()` 新增 `gateway_download_path`（帶 /patentmcp 前綴）+ `download_url_note`，48 工具 handle 統一產生點；兩處 cherry-pick 改 `{**handle}` 繼承新欄位。**檔案端點 404 已存在**（blob() 本就回 404 JSON；client 撞的 200-HTML 是 cms 頂層 SPA catch-all，不在本 repo）。
- [x] 03 代表圖非 TW 自動降級：wrapper 層 GPSS miss（no-row/diff-patent/no-figure）→ 非 TW 自動走 `fetch_patent_pdf`（官方優先）+ routed `next_step`（figure_extract.py）；TW miss 與網路錯誤維持 pass-through。批次部分成功→見「延伸發現」，待後續。
- [x] 04 figure_extract 影像式後備（已修 2026-07-15）：dual-engine（PyMuPDF fitz 優先／退 pdftoppm+Pillow）落 `figure_extract.py`，無文字層 PDF 改走 90dpi 灰階列投影偵圖面頁；pymupdf>=1.28.0 進 docker image（非 host）→ 容器內 `import fitz` 1.28.0 驗證，fitz 路徑免 poppler（解 Windows `MISSING_DEPENDENCY`）。
- [ ] 05 patent_search include_claim1（低，remaining）：caller 現以 `ppubs_batch_get_claims` 繞道可行，非阻塞。
- [ ] 01 README 連線檢查清單（低，remaining）：patentmcp 側僅能提供文件；client 已自行繞過。
- [x] （friction log）補 envelope 回傳值檢查（已修 2026-07-15，commit 22e9bb7）：`friction_log.py` 新增純函式 `detect_envelope_friction` 在成功回傳路徑旁路偵測（success:false / error_code / advisory 旗標）→ 自動記 kind=silent；TOOL_LANDED 白名單不誤報；fail-open 守 DD-4，不改回傳契約。9 案驗證通過。修了 §0 假陰性根因。
- [x] （批次工具 R13 斷鏈）已修 2026-07-15：`patents.py:batch_download_figures` GPSS miss fallback 拿到 `extract_representative_figure` 的 TOOL_LANDED redirect 現正確視為 landed（加 TOOL_LANDED/doc_dir/token 判定，兩處）。
- [x] （批次工具 /tmp）已修 2026-07-15：cooldown 由 `tempfile.gettempdir()`（/tmp world-readable）→ `$XDG_RUNTIME_DIR/patentmcp` 0700。
