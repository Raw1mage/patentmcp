# Proposal: patentmcp_webdav-r13-refactor

## Why

- patentmcp 已通過 mcp-integration-standard 基本面（R1/R2/R3/R4/R7/R8，見
  `specs/patentmcp/mcp-standard-conformance/`），但標準此後演進出兩個新層次：
  1. **R13 compute/landing split**（standard.md §R13，specbase 為 reference impl）：
     確定性 repo-local 工作不得躲在 container tool 後面付 token 往返/跨 UID 稅；
     應以 skill-attached local scripts 落地，container 只留真正需要憑證/網路的 compute。
  2. **WebDAV working cache**（docxmcp `specs/mcp/webdav-working-cache/` 已驗證 pattern）：
     token namespace 對 host 暴露成 online 掛載工作區，消滅逐檔 GET/PUT 與 tarball 儀式。
- patentmcp 的 screening 工作流正踩在這兩個缺口上：`build_screening_table` 把純資料
  轉換（去重/切 Claim1/欄位選擇/CSV 組裝）綁進 container；檢索產物（CSV/PDF/figure
  批次）只能逐檔 blob GET 取出。

## Original Requirement Wording (Baseline)

- "用mcp integration standard spec重構本mcp。換句話而，改成docker+webdav+skill with script"（2026-07-03）

## Requirement Revision History

- 2026-07-03: initial draft created via plan-init.ts

## Effective Requirement Description

1. **WebDAV working cache（完整 docxmcp 版，使用者拍板）**：subject-anchored cache
   provision/export/close 生命週期、per-owner credential + AuthProvider、dirty close
   gate、class-2 DAV method 表（OPTIONS/PROPFIND/GET/PUT/DELETE/MKCOL/MOVE/LOCK/UNLOCK）、
   class-aware reaper（deliverable-cache 免 idle reap、safety-net warn-first）。
2. **R13 積極拆（使用者拍板）**：所有確定性後處理（建表/去重/Claim1 切割/CSV 欄位
   選擇/報表組裝）落地為 `skills/` 內 local scripts；container 收斂為 repoless 網路
   閘道（search/fetch 回 records JSON + blob handle）。
3. **Breaking change 容許（使用者拍板）**：功能移出的 container tool 以 typed
   redirect（specbase TOOL_LANDED pattern）指引 landing script，一個版本後移除。
4. mcp.json `instructions` 依 R13.5 宣告 compute-plane（container tool）vs
   landing-plane（local script）verb 分工。

## Scope

### IN
- WebDAV route 群 + AuthProvider + cache 生命週期（provision/export/close/list）
- token store 增補 deliverable-cache class、dirty/export 追蹤、mkdir/move helper
- landing scripts（skills 內，R13.2/R13.6：self-contained、--repo/--in 參數、scope 硬防護）
- container tool 下架/stub redirect + mcp.json instructions/version 同步
- skill 文件（patentworks）同步：三層心智、FS/token 分工、export 紀律

### OUT
- gateway C code（dumb splice 穿透即可，DD-10 precedent）
- 已完成的 R1/R7/R8 conformance 面（不重做）
- 檢索來源梯 / search_dispatcher 邏輯（維持現狀）
- docxmcp 側任何改動

## Non-Goals

- 不做 persistent 個人永久空間（cache ephemeral，truth store 為家）
- 不做 container-per-user、不改 per-user compose project 佈局
- 不改 anonymous token TTL/LRU 語意（新增 class，不動舊語意）

## Constraints

- 天條 §11：no silent fallback——auth 失敗/跨 owner/target 不可達一律 typed fail-fast
- 爬蟲 gate（allow_scraping）語義不得因重構弱化
- landing scripts 執行器自選（R13.2）；本 repo Python 生態 → `python3` scripts
- bytes 不經 model context（handle 契約維持）

## What Changes

- `src/patent_mcp_server/`：HTTP app 增 WebDAV/dav routes + auth provider + cache 生命週期
- `src/patent_mcp_server/screening_table.py`：純轉換半段抽出為可 import 的 lib + landing script 入口
- `skills/patentworks/scripts/`：新增 landing scripts
- `mcp.json`：version bump + instructions 宣告兩平面
- container tools：建表類下架 → typed redirect stub

## Capabilities

### New Capabilities
- <capability>: <brief description>

### Modified Capabilities
- <existing capability>: <behavior delta>

## Impact

- <affected code, APIs, systems, operators, or docs>
