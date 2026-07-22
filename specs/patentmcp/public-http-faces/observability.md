# Observability: patentmcp_public-http-faces

觀測面全部來自 `src/patent_mcp_server/_http_app.py` 的 access-log middleware +
各 route handler 的 `_log.info` 埋點，落地到 `src/patent_mcp_server/friction_log.py`
的統一事件 store（events sqlite，category='access' 與 friction 同源）。

## Events

- **`access` / `http`（統一存取日誌）** — `_access_log_mw`（`_http_app.py:308-350`）以 pure-ASGI middleware 包住整個 app，**每個對外 HTTP 請求落一筆**，經 `friction_log.record_access`（:236-253）寫入 events store，category='access'、kind='http'。fail-open（recorder 自吞例外，logging 絕不弄斷請求）；pure ASGI 只 peek `http.response.start` 的 status，不 buffer body，故 SSE/streaming 回應不受影響。涵蓋全部面：`/`（landing）、`/mcp`、`/sse`、`/dav`、`/webdav`、`/files`、`/tools*`、`/skills`。
  - 欄位（W3C Extended Log 語義）：`method`、`uri`（cs-uri-stem；**query string 刻意丟棄**，:340）、`status`、`duration_ms`、`client_ip`（scope.client[0]）、`user_agent`、`mcp_client`（UA 的 `/` 前段，:345）。
- **`[dav] {method} {subject}/{rel} owner={owner} status={code}`** — `dav()` handler 每次 WebDAV 請求收尾記一筆（`_log.info`，:596/:603/:633）。三種 status 分支各自可觀察：401（無/錯 Basic 憑證，owner=?）、403（cross-owner，owner=實際身分）、2xx（成功，owner=實際身分）。這是 WebDAV 面授權結果的主要觀測點。
- **啟動日誌 `patentmcp http listening on {listeners} (/mcp, /files, /skills, /)`** — `serve()`（:750-751）記錄實際綁定的 UDS + TCP listener，用於確認 socket 是否成功綁在 `.run/patentmcp.sock`（gateway 連得上與否的第一手證據）。

## Metrics

以下均可由 events store 的 category='access' 列聚合（無獨立 metrics exporter；觀測基礎是統一存取日誌）：

- **各傳輸面請求量** — 依 `uri` 前綴分桶：`/mcp`（streamable 呼叫）、`/sse`（SSE 連線）、`/dav` vs `/webdav`（兩別名各自命中量，驗證 DD-4 別名確實被打）、`/files`（檔案下載）。用於偵測異常呼叫量（無認證公開 posture 下 rate-limit 建議的觀測依據，見 errors.md SSDLC 段）。
- **landing / schema 命中** — `uri` = `/`（landing 渲染）、`/tools`（HTML 索引頁）、`/tools/{name}`（每工具 schema 分頁）、`/tools.json`（機器可讀）各自命中量；可看文件站被消費的深度。
- **請求延遲** — `duration_ms` 分布，可分面觀察（`/mcp` 工具呼叫延遲 vs 靜態 landing）。
- **狀態碼分布** — `status` 聚合：2xx/401/403/404/500 各面比例。特別關注 `/tools/{name}` 的 404（unknown tool）、`/tools.json` 的 500（registry unavailable）、WebDAV 的 401/403（授權結果）。
- **client 分布** — `mcp_client`（UA 前段）+ `client_ip`，辨識呼叫來源（外網公開後尤其重要，用於偵測濫用來源）。

<!-- 注意：query string 不入日誌（:340），故 `?lang=` 語言切換等 query 參數不可從 access-log 還原；
     landing 語言選擇改由 `Content-Language` response header 觀測（若有蒐集）。 -->
