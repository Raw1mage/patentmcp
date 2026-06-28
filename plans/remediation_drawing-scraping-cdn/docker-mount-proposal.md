# C 草案：跨容器 token volume 對齊方案（待使用者批准）

> **狀態**：DRAFT — 待使用者批准後才施作。本文件**不**自動修改 `docker-compose.yml` / `mcp.json`。
> **來源**：BR_20260628 §C「跨容器 Token Volume 隔離」。

## 1. 問題現況（實證）

- `patentmcp` 與 `docxmcp` 是**兩個獨立 Docker 容器**，各自掛獨立 named volume：
  - patentmcp：`patentmcp-sessions:/var/cache/patentmcp/sessions`（`docker-compose.yml:34`）
  - docxmcp：自身的 session volume（不同 named volume）
- patentmcp `fetch_patent_pdf` / `extract_representative_figure` 產出的 PDF token，交給 docxmcp `decompose` 時回 `token_not_found`——因為 token 對應的實體檔在 patentmcp 的 volume，docxmcp 容器內看不到該路徑。
- 現行 workaround：先用 `download_url` 把 bytes 抓回 host 本機目錄，再以絕對路徑交給 docxmcp（中轉一次，多一道 I/O）。

## 2. 為何不能在工具內偷偷解決

- token store 的隔離是 Docker volume 邊界決定的，**非程式 bug**；工具層無法跨容器看到對方 volume。
- 依天條 11，不得用 silent fallback 掩蓋；正解是 infra 對齊，需重啟兩容器，屬 `architecture_change`，故走 approval gate。

## 3. 對齊方案（偵查後修正評估）

> **2026-06-28 偵查發現（關鍵約束）**：讀 `docxmcp/docker-compose.yml` 後確認 docxmcp 有**明文 bind-mount ban policy**：
> `# NO -v <host-path>:<data-dir> bind mounts. Verified by AC-01.`
> 且註解明示「`./.run → /run/docxmcp` 是 cross-cutting bind-mount ban policy 下**唯一允許**的 bind mount」（DD-13 lint）。
> → **原推薦的方案 A 直接違反 docxmcp 天條並會打爆其 AC-01 lint，撤回。**

### ❌ 方案 A（撤回）：共用 host bind mount 中轉目錄
~~兩容器各 bind 同一 host 目錄到 `/xfer`。~~
- **撤回原因**：docxmcp 明文禁 host-path bind mount（DD-13 + AC-01）。在 docxmcp 側加 `/xfer` host bind 會破壞它的 policy 與 lint 測試。違反天條「不違反其他 repo 的 policy」。

### 方案 B：共用 external named volume（技術可行，但需跨 repo 改 docxmcp）
建外部 named volume `patent-xfer`，兩 compose 都掛 `patent-xfer:/xfer`（named volume，**非** host-path bind，不違反 ban 文字）。
- 優點：純 Docker 管理；不違反 docxmcp 的 host-path bind ban。
- 缺點：
  - 仍需**改 docxmcp 的 compose**（跨 repo 改另一個受 policy/AC 保護的 repo 架構）+ 讓 docxmcp token store 認得 `/xfer` 外部路徑（docxmcp 側功能開發）。
  - 須先確認不觸發 docxmcp 其他 AC（即使 named volume 過 AC-01，仍是它架構政策的變更，應走 docxmcp 自己的 spec 流程）。
  - host 端不易直接檢視。

### 方案 C（偵查後建議）：patentmcp 側固化 host 中轉 SOP，零跨 repo
不改任何容器 infra，把現行 workaround「patentmcp `download_url` → host 落地 → docxmcp 官方攝取（`docxmcp_stage_dir` / tarball upload）」固化進 patentworks skill。
- 優點：
  - **零 infra 風險、零跨 repo 改動、不違反任何 repo 的 policy**。
  - 利用 docxmcp **既有官方跨容器攝取入口**（`docxmcp_stage_dir` inline files-map、或 HTTP tarball upload）——本就是設計來跨容器收檔的合法路徑。
  - BR 痛點真因是「AI 不知道要先中轉」，固化 SOP 即解決。
- 缺點：多一道 host I/O（單件 PDF，成本可忽略）。

### 偵查後結論
- **A 不可行**（違反 docxmcp 天條）。
- **B 可行但需跨 repo 改 docxmcp 架構政策**——超出本 patentmcp plan 單方面可決定的範圍，應由 docxmcp 自己的 spec 流程主導。
- **C 是唯一在 patentmcp 側單方面、零 policy 衝突可立即落地的方案**，且善用 docxmcp 既有官方攝取入口（符合 AGENTS.md「善用既有 infrastructure，不重複造輪子」）。

## 4. 影響面 / 回滾

- **影響**：需重啟 patentmcp + docxmcp 兩容器（停機 3~5s）；docxmcp repo 也要同步改 compose（跨 repo 協調）。
- **回滾**：移除新增的 volume 行 + env，重啟即還原；不影響既有 token store 與 session volume。
- **不變**：既有 `patentmcp-sessions` named volume 與 token TTL 行為完全不動。

## 5. 最終決議（2026-06-28，使用者批准「完整做完」後）

- **採方案 C（host-pipe SOP）**，理由見 §3 偵查結論。
- **A 撤回**（違反 docxmcp bind-mount ban / AC-01）。
- **B 留給 docxmcp 自身 spec 流程**：若未來要 named-volume 共享，需在 docxmcp repo 走它自己的 plan（新增 `patent-xfer` external volume + token store 認 `/xfer` 路徑），非本 patentmcp plan 可單方面決定。
- **已實證**（2026-06-28，host-side，bytes 不經 model context）：
  - patentmcp blob 端點：`GET http://localhost:8000/files/{token}/blob/{rel}` → http=200, 50026 bytes, `%PDF-1.4` magic。
  - host-pipe → docxmcp `POST /files`（UDS tarball）→ 回有效 `tok_566A2...`，bytes 50026 完整。
- **SOP 固化位置**：`skills/patentworks/reference/priorsearch/pdf-figure-extraction.md` §3.4（跨容器 token 中轉 host-pipe）+ §3.2 步驟2 警告。
- **無 infra 變更**：`docker-compose.yml` / `mcp.json` **均未修改**，零容器重啟、零跨 repo policy 衝突。
