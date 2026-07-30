# BR_20260730 — compose project label 漂移：跑著的 container 屬 `patentmcp`，webctl 用 `patentmcp-${USER}`，`restart` 撞名失敗

| Field | Value |
| --- | --- |
| Title | compose project 漂移導致 `webctl.sh restart` 撞名衝突，且兩個 project 各自持有不同的 sessions volume |
| Component | patentmcp 容器生命週期（`webctl.sh` / `docker-compose.yml`） |
| Reporter | patentmcp coordinator（修 BR_20260730 skill-shipping 時附帶發現） |
| Date | 2026-07-30 |
| Severity | medium — `restart`/`refresh` 這條唯一的正規重啟路徑失效；且存在 token store 在切 project 時「換 volume 而非搬 volume」的靜默資料遺失風險 |
| Priority | P2 — 有 `docker restart <cid>` 可繞（src 是 live bind mount），不阻塞日常；但正規路徑壞掉不該長期放著 |
| Affected paths | `webctl.sh:20`（`PROJECT="patentmcp-${USER}"`）；跑著的 container `3d7a1ccc4d7d` 帶 `com.docker.compose.project=patentmcp` |

```
State:
Fix: unfixed
Effect: n/a
Custody: unclaimed
Blocker: none
Disposition: accepted
Venue: patentmcp
```

## 1.1 症狀（verbatim）

```
$ ./webctl.sh restart
webctl: [1/3] building image
 Image patentmcp:latest Built
webctl: [2/3] recreating container
 Container patentmcp Creating
 service:patentmcp:1 Error response from daemon: Conflict. The container name
 "/patentmcp" is already in use by container "3d7a1ccc4d7d...". You have to
 remove (or rename) that container to be able to reuse that name.
```

image build 成功（[1/3] 過），死在 [2/3] recreate。

## 1.2 證據

跑著的 container 與 webctl 認定的 project 不是同一個：

```
$ docker ps -a --filter name=patentmcp --format '{{.ID}} | {{.Names}} | {{.Label "com.docker.compose.project"}}'
3d7a1ccc4d7d | patentmcp | patentmcp          <- 實際
$ echo "patentmcp-${USER}"
patentmcp-pkcs12                               <- webctl.sh:20 認定的
$ docker compose -p patentmcp-pkcs12 ps -a
NAME   IMAGE   COMMAND   SERVICE   CREATED   STATUS   PORTS     <- 空的
```

**兩個 project 各自持有一個 sessions volume**：

```
$ docker volume ls --filter name=patentmcp
patentmcp-pkcs12_patentmcp-sessions | local
patentmcp_patentmcp-sessions        | local
$ docker inspect 3d7a1ccc4d7d --format '{{range .Mounts}}{{.Name}}{{end}}'
patentmcp_patentmcp-sessions                                    <- 活著的那個用這顆
```

container 建於 `2026-07-22T00:59:55Z`。

## 1.3 RCA（初判，未完整定性）

`docker-compose.yml` 沒有寫 `name:`，所以 project 名完全由 `-p` 決定。
`webctl.sh:20` 一律帶 `-p "patentmcp-${USER}"`；但現存 container 的 label 是裸
`patentmcp`——與 `docker-compose.yml:6` 註解示範的 `docker compose -p patentmcp-${USER} up -d --build`
不符，形狀像是某次**未經 webctl、直接 `docker compose up`**（省略 `-p`，compose 遂以目錄名
`patentmcp` 為 project）所建立，此後就與 webctl 分屬兩個 project。

`container_name: patentmcp`（`docker-compose.yml:19`）是衝突的放大器：它把容器名釘死成全域唯一，
於是「不同 project、同一個容器名」必然撞牆——沒有這行的話兩個 project 只會各自生出
`<project>-patentmcp-1`，會變成**靜默跑出兩份服務**（那更糟，但症狀更難察覺）。

**注意**：以上為依現場證據的初判。未實際重現「哪一次操作造成漂移」，故不宣稱 root cause 已定。

## 1.4 為什麼不在 BR_20260730（skill shipping）順手修

避免 scope drift，且動 project 會碰 volume：

- 切到 `patentmcp-pkcs12` 會**掛上另一顆空 volume**，等於 token store 靜默換人——
  handles 全失效。這是資料面動作，不該夾帶在一個補 HTTP 端點的 commit 裡。
- 該次驗證只需要 process 重讀新 code，而 `./src` 是 live bind mount，
  `docker restart <cid>` 就地重啟即可達成，不需重建、不動 volume。

漂移早於該次改動（container 建於 07-22），與其無因果關係。

## 2. 修復方向

需先決定的取捨（**這是 decision，不是純執行**）：

1. **認定哪個 project 為正**。若認 `patentmcp-${USER}`（webctl 現況、多用戶隔離的原意），
   則必須**先把 `patentmcp_patentmcp-sessions` 的內容搬到 `patentmcp-pkcs12_patentmcp-sessions`**，
   或明確接受 token store 清空（現存 handle TTL 3600s，實務上可能可接受——需確認）。
2. **`container_name: patentmcp` 是否保留**。保留則全域唯一、跨 project 必撞；
   移除則 compose 自動命名，但 `webctl.sh:23` 的 `CONTAINER="patentmcp"` fallback 與
   `scripts/patentmcp-self-heal.sh` 的探測需一併對齊。
3. **webctl 應否自我防禦**：`restart` 前偵測「存在同名但屬別的 project 的 container」→
   fail fast 並印出具體修復指令，而不是丟一個看不出所以然的 daemon conflict。
   （對照 `BR_20260703` 已為 webctl 加過 `resolve_container()` 的類似韌性處理。）

## 3. 驗證計畫

- `./webctl.sh restart` 從乾淨狀態跑完三階段並 `wait_healthy` 回 0
- 重啟後 `GET /health` 200、`GET /skills` 200（BR_20260730 的端點未被回歸）
- `docker volume ls` 確認只剩一顆被實際掛載的 sessions volume，且切換前後
  token store 內容符合第 1 點的決定（搬移 or 明確清空）
- `scripts/patentmcp-self-heal.sh --check` 在新 project 名下仍能正確探測
