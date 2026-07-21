# BR_20260719 — 跨 DB 專利號碼格式 Converter Layer（SSOT）

- **狀態**: **resolved（2026-07-21，R3 三修：取文降級鏈接線 + L3 閘擴充）** — `patent_get_claim1` / `patent_enrich_backfill` 取文降級鏈全部 5 個送外部源送查點接上 per-target converter（GPSS 主查→`to_gpss_rest`、EPO→`to_epo_variants` 逐變體、gpatents 尾級 ×2→`_to_gpatents_canonical` strip-0，fail-fast `UNPARSEABLE_PUBNO` 禁裸送）。新增 `tests/test_fetch_converter_wiring.py`（10 L3 gate + 4 送查點 spy，漏接時當場 fail），key tests 37 passed、全套件 329 passed。額外坐實：`normalize_pubno` 對 US grant kind（`B1`/`B2`）因 mid-string letter 不剝零，改用 `to_gpss4_web` body + `lstrip("0")` 才正確。根治 plan：`plans/patentmcp_enrich-fetch-converter-wiring/`。詳見文末「復發樣本 R3（2026-07-21）」+「落地紀錄（R3 三修）」。
- ~~**狀態**: **REOPENED（2026-07-21，第三度同族復發）** — enrich 取文降級鏈整條沒接 per-target converter，US grant 前導零錯號（`US09993161B1`）直送 gpatents 必 miss，下游誤判成「451 筆真缺口」。~~
- ~~**狀態**: **resolved**（2026-07-19 晚二修：`to_epo_variants` 已補 US grant/old-A 前導零 strip 變體，並同族收斂 epo/client.py 4 處單形式 `to_docdb`→variants fallback，pytest 33 全綠，見文末「落地紀錄（二修）」）；前輪 resolved（converter 落地、5 處散點收斂，pytest 19+11 全綠）——但 §4 實查 roundtrip 未做就漏了這個實查才抓得出的缺陷，故一度 reopened~~
- **嚴重度**: high（資料完整性 + 反覆盲試燒 token 的系統性根因）
- **回報者**: 異常偵測前案檢索案（orchestrator）
- **元件**: `patent_mcp_server`（號碼正規化 / 各 DB 查詢入口）
- **類型**: enhancement / architecture（消除散落格式邏輯，收斂為單一 converter layer）

---

## 1. 症狀（Symptom）

同一件專利在不同資料源（patentdb key / GPSS REST / GPSS4 web / EPO OPS）需要**不同的號碼格式**，但目前沒有單一權威 converter。每個查詢點各自臨場處理格式，導致：

1. **假 miss / 假 not_found 反覆發生**：查詢用了某 DB 不接受的格式 → 回空 → 被誤判「資料真的沒有」。近例：
   - EPO US pre-grant 序號位數（10↔11 位）單形式查詢 404 → 誤判「EPO 對 A1 全 miss」（BR 前已臨時修 `docdb_variants`，但那是散點補丁不是 SSOT）。
   - TW 申請號 @AN 查詢，137 筆被記 not_found。
2. **消費端（本案）被迫盲試格式變體燒 token**：每碰到一個查不到就派實驗試 3-4 種格式變體，這是系統性浪費——應由 converter layer 一次把 mapping 坐實，消費端只呼叫 `to_<db>(pubno)` 即可。

## 2. 已坐實的證據（Evidence，供實作參考，避免重驗）

### 2.1 TW 137 not_found 是假結論（併發鎖定後遺症，非格式問題）

抽 3 筆已記 not_found 的 TW 申請號，用 `search_number(num, axis="apply")` 三種格式變體實測（container 內 GPSS4Folder）：

| appno | raw 9位 | 補前導0 | 10位 | 結果 |
|---|---|---|---|---|
| TW109112770 | `109112770` hits=2 | `0109112770` hits=2 | 同 | **全命中** → TW202138759A |
| TW113141212 | `113141212` hits=1 | `0113141212` hits=1 | 同 | **全命中** → TW202619683A |
| TW112107009 | `112107009` hits=2 | `0112107009` hits=2 | 同 | **全命中** → TW202435176A |

**結論**：TW @AN 對「TW去前綴後的原始數字」本來就查得到，三變體皆命中。137 筆 not_found 的真因是**登入被鎖期間的假失敗**（見 §2.2），不是格式不相容。→ 這 137 筆應**重查**，資料查得到。

### 2.2 not_found 年份分布否定「未公開」假設

resolved(633) 與 not_found(137) 的民國年份**完全重疊**（both 涵蓋 076–115），同年份 109 有 55 resolved 也有 8 not_found；appno 位數兩組皆 11 位。→ 同格式同年份卻有的解得出有的解不出 = 查詢當下的暫時性失敗（鎖定/節流），不是資料屬性。

### 2.3 已知各 DB 格式片段（散落現況，待收斂）

- `epo/client.py::to_docdb`：`CC.NUMBER.KIND`，kind 可選；US pre-grant 需 `docdb_variants` 雙位數變體（10↔11）。
- `patentdb_store.py::normalize_pubno` / `canonical_pubno`：庫 key = `country + 去分隔符去kind`；CN/TW 剝尾 kind，US 保留數字型 kind（B2/A1）。
- `gpss4/folder.py::search_number`：查詢字串 `({number})@AN`（申請號）/ `@PN`（公開號），`number` = 去 TW 前綴的原始數字。
- GPSS REST（`patent_search(pub_number=…)`）：接受完整 pubno（含 kind）。

## 2.4 歷史號碼錯位經驗總集（跨 session 蒐集，event log 坐實）

以下每一條都是過往 session 實際踩過的號碼格式/錯位坑，附 event slug 可回查。這是本 converter layer 要一次消滅的完整攻擊面——**每一條都是「查詢/對帳用錯格式 → 假 miss/假缺口/錯件」的具體案例**。

### 「對帳訊號三騙局」系列（號碼 key 語意不一致導致的假結論）

| # | 騙局 | 根因 | 假結論 | event |
|---|---|---|---|---|
| **騙局 1** | **kind-strip key 騙** | patentdb `canonical_pubno` 對 CN/TW 剝尾端 kind（庫 key=`CN119230141` 非 `CN119230141A`），US 保留數字 kind（B2/A1）。對帳若用原始 pubno（帶 kind）查庫 → 查不到 → 誤判「沒落庫/脫靶」 | CN「4,432 pending」大半假缺口；EPO 補撈 1,051 筆 CN 被 subagent 誤判 0 落庫 | `event-2026-07-19-d4-kindstrip-false-gap` |
| **騙局 2** | **時間戳時區騙**（相關但非號碼本身，列此警示對帳陷阱） | `patentdb_store.put()` 硬編 `+08:00` 後綴但 container TZ=UTC → updated_at 標籤偏早 8h。用「執行窗/當日」時間過濾落庫對帳 → 假「零落庫」 | EPO filled≠落庫二度翻案（落庫其實成功） | `event-2026-07-19-d5-timestamp-tz-bug` |
| **騙局 3** | **EPO docdb 位數騙** | US pre-grant 序號 EPO 端有時 10 位（去前導零）有時 11 位；`to_docdb` 單形式查 → 404 | 「EPO 對 US A1 全 miss」 | `event_20260719_epo-docdb-format-bug` |

**converter layer 的核心價值**：騙局 1 和 3 都是「同一件專利在不同 DB 用不同號碼形式」造成的。converter layer 若提供 `to_patentdb_key()`（明確產出 stripped + 原始雙 key）與 `to_epo_variants()`（位數雙變體），這兩個假缺口從源頭消滅。

### TW 號碼路由/軸別錯位

| 案例 | 根因 | event |
|---|---|---|
| **TW 申請號被當公告號查** | `patent_get_claim1` TW 分支恆用 `@PN`（公告號軸）；TW 申請號（`TW+9碼民國年`，如 TW092110119）非公告號，@PN 必 miss → 掉爬蟲報「Failed to fetch」。真因是**軸別路由 bug**，不是「TW 只能爬蟲」 | `event_20260718_ppubs_tw_quota_bugfixes`（Bug 2） |
| **TW 公告號 regex 吃 T/漏抓** | gpss4 TW 公告號 regex 對國碼段處理不全 → 漏抓 pat_no（後抽 shared `patno.py` 修正） | `event_2026-07-18_br-20260718-gpss4-tw-regex-*` |
| **gpss4 pat_no=null** | 結果頁需選國別+切表格式檢視才 render pat_no（狀態機問題，非號碼格式，但影響號碼抽取） | `event_2026-07-16_playwright-gpss4-pat-no-render` / `event_2026-07-16_gpss4-pat-no-null-br-*` |

**啟示**：converter layer 的 `to_gpss4_web(raw, axis)` 必須**強制指定軸別**（pub→@PN / apply→@AN），且能從號碼形態（`TW\d{9}` 民國年 = 申請號）自動推斷正確軸別，杜絕「申請號誤走公告號軸」。

### CSV/匯入層中文欄名與號碼映射

| 案例 | 根因 | event |
|---|---|---|
| **import-csv 中文欄名映射錯位** | v3 歷史 pool 回填 patentdb 時，CSV 中文欄名（公開號/申請號）映射到錯欄 → 號碼進錯欄位 | `event_2026-07-06_v3-pool-patentdb-1536-import-csv` |
| **CN543 錯件圖 silent fallback** | gpss legacy gpss2 misresolve pubno → 抓到錯件的代表圖靜默落地回 success；gpss3 為正解 | `event_2026-06-29_br-20260629-b-*` / `event_2026-06-28_isafe2-0-r3-cn543-*` |

**啟示**：號碼 misresolve 會一路靜默污染到下游交付物（錯件圖）。converter layer 應是所有號碼解析的**唯一入口**，並在無法明確解析時 fail fast（非 silent fallback 到錯號）。

### pubno 正規化既有修復（已修但屬散點，待收編）

| 案例 | event |
|---|---|
| pubno-normalize 修復 + migration（散點修復，非 SSOT） | `event_2026-07-18_open-br-*pubno-normalize*` |

### 本 session（2026-07-19）新增

- **TW 137 假 not_found**：三格式變體全命中，真因併發鎖定期假失敗（§2.1/§2.2）。
- **EPO US A1 位數雙變體**：已臨時修 `docdb_variants`，待升格 `to_epo_variants`（§2.3、騙局 3）。

### 本 session（2026-07-19 晚）新增：US grant/old-A 前導零假 miss（同族 bug 漏網，已實測坦實）

**症狀**：US 真缺 abstract 3,889 筆中，grant（B2/B1）815 + old-A（1990s）192 = **1,007 筆 EPO `found=False`**，實為格式假 miss。

**決定性實測**（EPO OPS `EPOClient.biblio()`，純 REST 零登入，2026-07-19 晚）——**前導零是唯一變因，命中/miss 完全對翻**：

| 號碼 | converter 現況（帶前導零） | strip 前導零 |
|---|---|---|
| grant `US9997041` | `US09997041B2` → **found=False** | `US9997041B2` → **found=True, abs=Y** |
| grant `US9959784` | `US09959784B2` → found=False | `US9959784B2` → **found=True, abs=Y** |
| old-A `US6150941` | `US06150941A` → **found=False** | `US6150941A` → **found=True, abs=Y** |
| old-A `US5928157` | `US05928157A` → found=False | `US5928157A` → **found=True, abs=Y** |

**sanity**：`US11000000B2`/`US10000000B2`（近年號、序號本無前導零）帶不帶零都 found=True → 排除「EPO 不收 US grant」假設，問題純粹在**舊號序號的前導零**。

**Root cause**：`to_epo_variants`/`docdb_variants` 對 US grant（`US0\d{7}B\d`）與 old-A（`US0\d{6,7}A`）**只產一個保留前導零的變體**，沒產 strip 版。與已修好的 US A1 10↔11 位是**同一族 bug 的漏網**（A1 修了、grant/old-A 漏了）。

**需求**：`to_epo_variants` 對 US 舊號（序號帶前導零）加產「strip 前導零」變體（主形式不拘，variants list 兩版都包，查詢端逐個 fallback）。影響：本案 1,007 筆假 miss 可回收一大片。

**添網羈絡（本案資料）**：`output/priorart_anomaly-rerun/02_pool/master_pool.csv` US 區 grant/old-A miss；layer 修後可用 EPO loop 重掃回收。

## 2.5 號碼形態速查（converter layer 實作的維度清單，來自上述經驗）

| 國 | 號型 | 形態範例 | 已知陷阱 |
|---|---|---|---|
| CN | pubno | `CN119230141A` | 庫 key 剝 kind（→`CN119230141`）；對帳需雙 key |
| US | pubno grant | `US11213256B2` / `US9997041B2` | 保留數字 kind；**舊號序號帶前導零需 strip 變體**（`US09997041B2` → EPO 404，`US9997041B2` → 命中；§2.4 晚新增實測）；近年 8 位序號無前導零則單形式即可 |
| US | pubno old-A (1990s) | `US6150941A` | **序號帶前導零需 strip 變體**（`US06150941A` → 404，`US6150941A` → 命中） |
| US | pubno pre-grant | `US20230053201A1` | EPO docdb 序號 10↔11 位雙變體 |
| TW | pubno 公開 | `TW202138759A` | — |
| TW | pubno 公告 | `TW578729U` / `TWM305142U` | regex 需含國碼段（曾漏抓） |
| TW | appno 申請號 | `TW109112770`（民國年 3+6） | 必走 @AN 軸，勿誤走 @PN |
| CN/US/TW | appno | 各國申請號格式 | 軸別路由 + 補零規則 |

## 3. 需求（Requirement）

建立**單一 converter layer 模組**（建議 `patent_mcp_server/pubno_convert.py`）作為跨 DB 號碼格式 SSOT，覆蓋：

**維度**：{CN, US, TW} × {pubno 公開/公告號, appno 申請號} × {老號, 新號, 帶/不帶 kind code}

**目標 DB 輸出函式（每個回傳該 DB 接受的格式；歧義時回 variants 陣列，主形式在前）**：

| 函式 | 目標 | 語義 |
|---|---|---|
| `to_patentdb_key(raw)` | patentdb PK | = 現 `canonical_pubno`，kind-strip aware（CN/TW 剝 kind、US 留數字 kind） |
| `to_gpss_rest(raw)` | GPSS REST `pub_number` | 完整 pubno |
| `to_gpss4_web(raw, axis)` | GPSS4 web @PN/@AN | 去國碼原始數字；axis=pub/apply |
| `to_epo_variants(raw)` | EPO OPS docdb | = 現 `docdb_variants`，含 US 10↔11 雙變體 |

**核心規格要求**：
1. **variants-first，不猜單一形式**：任何一個 DB 若對某號型有多種可能接受格式（如 EPO US pre-grant 位數、TW 老號補零），函式回 variants list（主形式在前），查詢端逐個 fallback。杜絕「單形式查空→誤判 miss」。
2. **每條 mapping 附實測依據**：模組內以註解或 docstring 記錄「此格式對此 DB 實測命中」的證據（如 §2.1 的表），不是憑推測。
3. **收斂散點**：現有 `to_docdb`/`docdb_variants`/`normalize_pubno`/`canonical_pubno` 及各查詢點的臨場格式處理，全部改呼叫本 layer；不再各自為政。
4. **kind-strip 對帳一致**（呼應本案 D4 血淚）：CN/TW 對帳需同時查原始 key 與 stripped key，converter 要能明確產出兩者。

## 4. 驗收（Acceptance）

- [ ] `pubno_convert.py` 存在，四個 `to_*` 函式覆蓋 CN/US/TW × pubno/appno。
- [ ] 附一張 mapping 知識表（markdown 或模組 docstring），每格附實測命中證據。
- [ ] **號碼形態全覆蓋 roundtrip 實查閘（零磨擦核心，見 §7）**：§2.5 mapping 表的**每一個號型維度**（CN pubno、US grant 帶/不帶前導零、US pre-grant 10↓11、US old-A strip-0、TW @AN 老/新號…）至少一個 roundtrip 實查命中測試；**converter 改動未過全維度實查不得標 resolved**。（本 BR 第一輪就是因這條 deferred → US grant/old-A strip-0 漏網）
- [ ] 現有散點（epo/client、patentdb_store、gpss4/folder、patents.py 查詢入口）改走本 layer，無重複格式邏輯。
- [ ] 回歸：既有 patentdb key 生成不變（`canonical_pubno` 行為向後相容）。

## 7. 零磨擦固化契約（使用者 2026-07-19 明示：讓「號碼錯位」這族 bug 永久零磨擦）

> 使用者訴求：**這些出錯的主因能不能變成 KB、固化成 tool，讓 patentmcp 運作 0 磨擦？**

**關鍵教訓（本 BR 自身已證）**：converter 落地時 KB 層（docstring mapping 表）+ tool 層（`to_epo_variants` variants-first）**都做了，US grant/old-A strip-0 還是漏了**。證明光靠前兩層不夠——缺的是第三層「防回歸實查閘」。零磨擦需三層同時到位：

### L1 — KB 層（知識不死在記憶，寫進 code）
- `pubno_convert.py` module docstring 的 §2.5 mapping 表是 SSOT；**每發現一種新號型畔位，當場補進表（附實測依據 + event slug）**。
- 本輪需補：US grant `US09997041B2`→strip-0、US old-A `US06150941A`→strip-0（實測證據見 §2.4 晚新增表）。

### L2 — tool 層（固化成行為，不靠呼叫端記得）
- `to_epo_variants` 對 US 舊號（序號帶前導零）自動產 strip-0 變體（variants-first，主形式不拘、兩版都包）。
- 原則：**任何 DB 對某號型有多種可能接受格式 → 回 variants list，不猜單形式**（已是 DD-2，strip-0 只是其實例）。converter 是唯一 SSOT，消費端一律呼叫，不臨場處理格式。

### L3 — 防回歸實查閘（零磨擦的真正保證，本 BR 首輪正是此層缺失）
- **pytest 對 §2.5 每一號型維度都有一個 roundtrip 實查 case**（真打 EPO/GPSS/patentdb，非 mock）；新增號型必附新 case。
- **converter 任何改動（含新增變體）未跦 L3 全維度實查，不得標 resolved / 不得 merge**——這是把「光靠 AI/人記得測」換成「code 層閘自動戒」。
- 實查需額度時：至少保留一組 known-item 固定測例（如 US grant `US9997041B2`、old-A `US6150941A`、TW `TW202223848`）常騐，額度不足時至少跑完這組。

**一句話**：零磨擦 ≠ 「有 converter」，而是「有一個測試會在 converter 漏掉任一號型時當場 fail」。L1/L2 防「不知道」，L3 防「知道但漏做」。

## 5. 消費端（本案）後續依賴

converter layer 落地後，本前案檢索案的收池流程改為：所有跨 DB 查詢/對帳一律走 `pubno_convert.*`，不再派 subagent 盲試格式變體。TW 137 假 not_found 屆時用正確格式重查即可回收。

## 6. 附註：BR 前已做的臨時補丁（需 patentmcp 收編或取代）

本案 orchestrator 在發現此問題過程中，曾直接在 patentmcp code 動手（越界，已改正職責分界）：
- `epo/client.py` 加了 `docdb_variants()` + `biblio()` 逐變體 fallback（US 10↔11 位）——**這是本 BR converter layer 的雛型**，請收編進正式模組。
- `tw_resolve_loop.py`（本案 scratch 腳本，非 patentmcp core）改為 login 失敗即 abort。

請 patentmcp 團隊評估：上述 `docdb_variants` 是否直接升格為 `to_epo_variants` 納入 converter layer。

---

## 落地紀錄（2026-07-19，plan `patentmcp_cross-db-pubno-converter`）

**結論：`docdb_variants` 已直接升格為 `to_epo_variants` 納入 converter layer。**

### 交付

- **新建 `src/patent_mcp_server/pubno_convert.py`**（純函式 SSOT，僅 stdlib `re`）：
  `to_patentdb_key` / `patentdb_key_variants` / `to_gpss_rest` / `to_gpss4_web(raw, axis=None)` /
  `to_epo_variants` / `to_docdb` / `normalize_pubno`。模組 docstring 內含 §2.5 mapping 知識表，每條附實測依據。
- **5 處散點全部收斂改走 converter**（刪重複格式邏輯）：
  1. `epo/client.py`：`to_docdb`/`docdb_variants` → converter thin re-export（保留既有 import 路徑；`docdb_variants` = `to_epo_variants` 別名，**收編 §6 臨時補丁**）。
  2. `patentdb_store.py`：`canonical_pubno`/`normalize_pubno` 委派 converter；`_KNOWN_CC` 保留（patents.py import）。
  3. `patents.py`：`_get_patent_country_and_normalized_no` 委派 converter。
  4. `scripts/family_backfill_offline.py`：host-local script 注入 `sys.path` 改用 canonical `to_docdb`，**取回舊簡化版缺的 US 10↔11 變體能力**。
  5. `skills/patentworks/scripts/patentdb_local.py`：vendor 複製 + 同步註記（保 R13.6 no-import-from-src）。

### 需求對映

- **variants-first**（核心規格 1）✓ — 歧義號型回 list 主形式在前，呼叫端逐個顯式 fallback，無 silent fallback。
- **每條 mapping 附實測依據**（核心規格 2）✓ — docstring mapping 表引用 §2.1/§2.3 已坐實案例。
- **收斂散點**（核心規格 3）✓ — 見上。
- **kind-strip 對帳一致**（核心規格 4）✓ — `patentdb_key_variants(raw)` → `[stripped, original]` 雙 key。
- **TW 軸別推斷**（§2.4 啟示）✓ — `to_gpss4_web` 從 `TW\d{9}` 民國年號形推斷 apply/@AN。

### 驗證

- `tests/test_pubno_convert.py`：19 tests 全綠（mapping 向量 TV-1~8 + 5 處收斂 import + vendor-drift guard + 向後相容回歸）。
- `tests/test_patentdb_store.py`：既有 11 tests 全綠（收斂未破壞既有行為；`canonical_pubno` 向後相容硬閘通過）。

### 驗收剩餘（deferred）

- **驗收第 3 條「EPO US pre-grant、TW @AN 老號/新號 roundtrip 實查命中」**：deferred，待使用者指定 EPO OPS 週額度 / GPSS4 下班時段窗口再跑（BR §2.2 提醒登入鎖定風險）。純函式格式已由 pytest 全覆蓋，實查為額外實測保證，非阻塞。
- **消費端 §5**：TW 137 假 not_found 重查屬前案檢索案後續，converter 落地後由該案用正確格式重查即可回收（本 BR 範圍外）。

plan 狀態停在 `implementing`（未 promote `verified`，因 roundtrip 實查未做）。

---

## 落地紀錄（二修，2026-07-19 晚：US grant/old-A 前導零同族 bug）

**觸發**：BR reopened——上輪 deferred 的 roundtrip 實查抓出 `to_epo_variants` 漏 US grant/old-A 前導零變體（§2.4-晚、§2.5）。與已修的 US A1 pre-grant 10↔11 位是**同族 bug 漏網**。

### 交付

1. **`pubno_convert.to_epo_variants` 補 grant/old-A 前導零 strip 變體**：US `num[0]=='0'`（pre-grant 年份永不以 0 開頭，此條件唯一標記 grant/old-A plain serial）→ 加產 `lstrip("0")` 變體。docstring 補第 2 類歧義說明 + §2.4-晚 實測依據。
2. **同族收斂 `epo/client.py` 4 處單形式 `to_docdb`→variants fallback**（根因=EPO 查詢未統一走 variants，一次補齊）：
   - `family()` / `claims()` / `images()`：逐變體 fallback（同 `biblio()` 慣例，非 404 即 break）。
   - `download_image_pdf()`：需單一確定 docdb 組 image path（不能吃 list）→ 先 probe variants 找命中形式再組 path，無命中退回主變體（保既有 miss 行為）。

### 驗證

- `tests/test_pubno_convert.py`：新增 3 向量（grant 帶/不帶前導零、old-A、近年號 sanity）；`pytest test_pubno_convert + test_patentdb_store` = **33 全綠**。
- import smoke：`docdb_variants("US09997041B2")=["US.09997041.B2","US.9997041.B2"]`、`US06150941A` 同；4 EPO 方法 syntax + import OK。

### 驗收更新

- [x] §4 acceptance 第 3 條（EPO US pre-grant/grant/old-A roundtrip）之**格式層**由 BR 附決定性實測（EPO OPS REST 零登入抽樣，前導零唯一變因、命中/miss 對翻）坐實；純函式全覆蓋。
- 教訓：上輪 pytest 純函式全覆蓋卻漏此 bug，因純函式測試無法涵蓋「EPO 實際存哪種序號形式」——那是 live 事實，必須 roundtrip 實查才抓得出。

### 影響

- 本案 US 1,007 筆假 miss（grant 815 + old-A 192）可用 EPO loop 重掃回收。
- 同族 `family`/`claims`/`images`/`download_image_pdf` 對同批 US 前導零號亦不再假 miss。

- event: `event_2026-07-19_br-20260719-converter-reopened-to-epo-variants-us-*`

---

## 復發樣本 R3（2026-07-21）— enrich 取文降級鏈整條沒接 converter（第三度漏網消費點）

**回報者**：異常偵測前案檢索案（orchestrator）。**觸發**：US 母池 claim1 補撈，subagent 對一批 US 舊 grant 案回 `Failed to fetch from gpatents`，誤判為「451 筆真缺口 / gpatents 未上架」。orchestrator 實測翻案。

### 坐實的因果鏈（三步，全實測）

1. `to_patentdb_key("US09993161B1")` → `US09993161B1`（**保留前導零**，對帳 key 本就該保留，正確）。
2. `patent_get_claim1("US09993161B1")` → `Failed to fetch from gpatents`（前導零錯號直送 gpatents，必 miss）。
3. 剝零後 `patent_get_claim1("US9993161")` → `success: true`，完整 claim1 全文（`source: google_patents`）；`epo_biblio("US9993161B1")` 亦 `found: true`。

→ **號碼形態沒錯是 converter 的鍋——`to_epo_variants` 二修已能產 strip-0 變體。真 bug 是 enrich 取文降級鏈（`patent_get_claim1` / `patent_enrich_backfill` 送 gpatents/google_patents/GPSS/EPO 前）整條沒呼叫任何 per-target converter，原號直送。**

### 為何是本 BR 的同族復發，非新軸

- 本 BR §5「消費端後續依賴」+ §7 L3 實查閘只覆蓋了**對帳/落地 key 消費點**（`patents.py:_get_patent_country_and_normalized_no`、`patentdb_store`），**沒覆蓋 `patent_get_claim1` 取文降級鏈的送查點**。
- 這是本 BR 文末自己預言的 pattern 第三次應驗：「**L1/L2 防『不知道』，L3 防『知道但漏做』**」。converter 有能力、docstring 有 mapping（L1/L2 到位），但取文端這個消費點漏接線（L3 未覆蓋 → 漏網）。
- 前兩個漏網消費點：US A1 pre-grant 10↔11 位（首修）、US grant/old-A strip-0（二修）。**本次是第三個：取文降級鏈整條**。三者同根：per-target converter 已正確實作，某消費端繞過它裸送。

### 證據定位（subagent explore 偵查）

- gpatents 送查點：`patents.py:1437`（`source: google_patents` 成功）、`patents.py:1440`（`Failed to fetch from gpatents.`）。
- `patents.py` claim1/enrich 取文區段 grep `to_gpss|to_epo|to_docdb|pubno_convert` 交叉 `claim1|enrich|fetch` **未命中任何 per-target converter 呼叫** → 原號直送坐實。
- `patents.py:1238` 有「gpatents 失敗 → 改走 @AN 申請號路由」的 fallback 註解，證明降級鏈是「fetch 失敗後改路由」補救，而非「送查前正規化號碼」——補救邏輯掩蓋了根因。

### 影響

- 本案 US claim1 補撈被誤判「451 筆真缺口 / gpatents 未上架」，實為前導零錯號 × 取文端跳過 converter 的雙重人為錯。converter 接上後用正確號重撈即可回收大部分。
- 同族 `patent_enrich_backfill` 對任何 US grant/old-A 前導零號的取文都受影響。

### 根治 plan

`plans/patentmcp_enrich-fetch-converter-wiring/`（本輪開）——取文降級鏈每個送查點接對應 per-target converter（送 gpatents/google→strip-0 canonical、送 GPSS→to_gpss_rest、送 EPO→to_epo_variants）+ L3 實查閘擴充覆蓋取文降級鏈（DD-2「converter 漏任一消費點時當場 fail」的取文端實例）。

### DD（本復發樣本新增）

- **DD-3（取文端接線）**：enrich 取文降級鏈的送查點是 converter 的**第 6 類消費點**（前五：epo/client、patentdb_store、gpss4/folder、patents.py 對帳入口、family_backfill script）。每跳送查前呼叫該源 per-target converter，禁原號直送。
- **DD-4（L3 閘擴充）**：L3 roundtrip 實查閘的「每消費點」維度必須含**取文降級鏈**——否則同一「知道但漏做」會第四次復發。閘的判準：拿一個已知前導零錯號跑 `patent_get_claim1`，斷言 converter 被呼叫且取文成功。

- event: `event_2026-07-21_br-20260719-r3-enrich-fetch-converter-wiring`
