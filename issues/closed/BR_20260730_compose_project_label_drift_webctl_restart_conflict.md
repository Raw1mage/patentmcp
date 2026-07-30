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
Fix: fixed(8d53020)
Effect: deployed
Closed: 2026-07-30 by session:ses_04db723af
Custody: session:ses_04db723af
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

## 1.5 更正（2026-07-30，實測推翻 §1.4 的前提）

§1.4 寫「切到 `patentmcp-pkcs12` 會**掛上另一顆空 volume**，token store 靜默換人——handles 全失效」。實測**完全寫反**：

```
$ docker run --rm -v patentmcp_patentmcp-sessions:/d alpine sh -c 'ls -la /d; du -sh /d'
total 16
drwxr-xr-x 2 root root 12288 Jul 27 14:01 .      <<< 空的，而這顆正被活著的容器掛載
12.0K	/d

$ docker run --rm -v patentmcp-pkcs12_patentmcp-sessions:/d alpine sh -c 'ls -la /d | head; du -sh /d'
drwxr-xr-x 93 root root 12288 Jul 17 16:45 .       <<< 91 個 token 目錄，2.4M
drwxr-xr-x  2 root root  4096 Jul 17 15:26 tok_26PFYHWASJSBYVGZQ3NSE27C4VIHAV4V
...
2.4M	/d
```

**正確的局面**：

| volume | 內容 | 掛載狀態 |
| --- | --- | --- |
| `patentmcp_patentmcp-sessions` | 空（12K，僅目錄） | 活著的容器正掛這顆 |
| `patentmcp-pkcs12_patentmcp-sessions` | 91 個 token 目錄、2.4M、**Jul 17** | webctl 認定，目前未掛 |

**這把整張 BR 的風險評估翻轉了**：

- 切 project **不會**弄丟任何現役資料——現役那顆本來就是空的（token TTL 3600s，早已自然清完）
- 反而是切過去會**掛上一顆 Jul 17 的死資料**（2.4M、全數過期）
- 所以 §2 第 1 點的「搬移 vs 接受清空」取捨**不存在**：兩邊都沒有值得保留的東西，真正該問的是「兩顆都該不該直接刪」

**我為何寫錯**：當時只看了 `docker volume ls` 與 `docker inspect` 的**名字與掛載關係**，就推論「沒掛的那顆是空的」——沒打開來看。這與本日 skill-shipping BR 的根因同形：**未被檢查覆蓋的地方，必然回綠**。推論看起來合理（新 project → 新 volume → 空），但 project 漂移發生在 07-22，而舊 volume 的資料是 07-17——**漂移發生前它才是現役那顆**，順序正好相反。

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

---

## 4. 決議與修復（2026-07-30，使用者拍板「全收」）

§2 列的三個取捨，在 §1.5 更正後只剩兩個（volume 搬移取捨不存在）：

**取捨 1（volume）——消失**。兩顆都沒有值得保留的東西：現役那顆空的，廢的那顆是 7/17 已過期 token（TTL 3600s）。直接删除廢 volume，無需搬移。

**取捨 2（`container_name` 是否保留）—— 保留**。移除它會讓兩個 project 各自生出 `<project>-patentmcp-1`，變成**靜默跑出兩份服務**——比撞名難察覺得多。寧可吵，不要靜默分裂。這是刻意選擇的失敗形狀。

**取捨 3（webctl 自衛）—— 加入**，並且不只這一道。

### 兩道防線（職責不同，缺一不可）

1. **結構防線——消除根因**：`docker-compose.yml` 加頂層 `name: patentmcp-${USER:-nouser}`。有了它，裸 `docker compose up`（無 `-p`）也會落在正確 project，**不再退回目錄名**——也就是說造成這次漂移的那個操作，以後不會再造成漂移。

   用 `:-nouser` 而非 `:?` 是實測後的決定（compose v5.3.1）：

   | 情境 | 結果 |
   | --- | --- |
   | `USER` 有設、無 `-p` | project = `patentmcp-pkcs12` ✓ 根因消除 |
   | `USER` 有設、有 `-p` | `-p` 覆蓋 `name:` ✓ webctl 保有控制權 |
   | **`USER` 未設、有 `-p`、用 `:?`** | **整個失敗**（`required variable USER is missing a value`, exit 1）|

   第三列是關鍵：interpolation **即使 `-p` 已覆蓋此鍵仍會求值**，所以 `:?` 守衛會把 systemd/cron 下的**正確路徑**一起打死。

2. **行為防線——攔截已發生的漂移**：`webctl.sh::assert_no_project_drift()`。`start` 與 `restart` 兩處都在動作前呼叫；偵測到同名容器屬別的 project 就 fail fast（exit 1，**唯讀不動服務**）並印出實際歸屬 + 修復指令。

   在 `restart` 路徑刻意排在 build **之前**——衝突會讓 recreate 必敗，先花幾分鐘 build 只是延後同一個錯誤（正是 §1.1 症狀：[1/3] 過、[2/3] 死）。

### 驗證（§3 四項全過）

```
驗證前（漂移狀態）
  ./webctl.sh restart   -> guard fail fast, exit=1, 容器未受影響（唯讀）
  ./webctl.sh start     -> guard fail fast, exit=1

對齊
  docker compose -p patentmcp down   -> 舊 project 拆除
  ./webctl.sh start                  -> guard 放行，project=patentmcp-pkcs12
  docker volume rm patentmcp_patentmcp-sessions   -> 廢 volume 清除

對齊後
  ① ./webctl.sh restart     -> 三階段跑完 + wait_healthy, exit=0, 28s
  ② GET /health            -> 200
     GET /skills             -> 200 {patentworks, file_count 30}
     GET /skills/patentworks.zip -> 200, 130270B, 30 members, 全數 patentworks/ 前綴
  ③ docker volume ls        -> 只剩 patentmcp-pkcs12_patentmcp-sessions（實際掛載中）
  ④ self-heal.sh --check    -> healthy, exit=0

compose name: 三情境
  bare config（無 -p）      -> patentmcp-pkcs12（非目錄名 patentmcp）✓
  -p 覆蓋                   -> patentmcp-pkcs12 ✓
  USER 未設 + -p           -> exit=0（不會打死正規路徑）✓
```

### Architecture Sync

`specs/architecture.md` 原本**完全沒有**容器生命週期章節（grep `webctl|compose project|container_name` 零命中）——這是本次暴露的真正文件債。已补上 `## Container Lifecycle / Compose Project 邊界`：三個檔案的分工、`container_name` 全域性的取捨、project 名決定 volume 前綴因此切 project 等於換 token store。
