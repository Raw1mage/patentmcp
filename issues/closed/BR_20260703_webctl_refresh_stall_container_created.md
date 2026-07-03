# BR: `webctl.sh refresh` 卡死 >180s,容器停在 `Created` 未啟動 【已修復 2026-07-03】

## 現象(含硬證據)

- 2026-07-03 13:4x,執行 `./webctl.sh refresh` 驗證 dispatcher 上線,指令 **180s timeout 無任何輸出**(bash tool 強制終止)。
- 終止後 `docker ps -a --filter name=patentmcp` → `6c878afb2cf6_patentmcp | Created`(容器已建立但**未啟動**,且是 compose 的 temp-name);`.run/patentmcp.sock` 是舊 socket(root-owned, Jun 29),`curl /health` 與 `/tools` 皆空回應。
- 手動 `docker start 6c878afb2cf6_patentmcp` 後 5 秒內 health OK、`/tools` 正常回 26 tools(含新 `patent_search`)——證明 image/程式本身無問題,是 refresh 編排被中斷。

## RCA(已確認)

**不是 compose 死鎖,是「長時間靜默 build + 外部 timeout kill 落在 recreate 窗口」的複合症:**

1. 舊 `refresh` 用單一 `docker compose up -d --build --force-recreate`。image rebuild(uv sync + bytecode compile 5220 檔,1.58GB image)是慢的那段,且全程無 stdout 進度(bash tool 環境無 tty)→ 外觀上是「卡死無輸出」。
2. 180s timeout 把 compose 殺在 recreate 中段:舊容器已移除、新容器已 Create(compose 給 temp-name `<hash>_patentmcp`)、尚未 start → 留下 Created 殭屍。
3. 後續 `wait_healthy` 硬編 `docker inspect patentmcp`(canonical name),但殘留容器叫 temp-name → health 檢查永遠 missing,診斷盲區(BR 現象第 2 點的空回應即此)。
4. 舊 root-owned socket 殘檔只是伴生現象,非成因(新容器 bind 會覆蓋)。

## 實際修復(webctl.sh, 2026-07-03)

1. **build 與 recreate 拆兩步**:`compose build` 先跑完(慢的部分獨立、可觀察),再 `up -d --force-recreate`(recreate 窗口縮到秒級,中斷不再留 Created 殭屍)+ 每步 `webctl: [n/3]` 標記。
2. **`resolve_container()`**:health 檢查改用 `docker compose -p $PROJECT ps -q` 依 project label 解析容器(temp-name 也抓得到),fallback canonical name。
3. **timeout 時輸出診斷**:最後 status + 同 project 容器清單 + `docker logs --tail 20`。

## 驗證

- `bash -n` 過;`./webctl.sh refresh` 全程 **13.2s** 完成,三步標記可見,容器名回 canonical `patentmcp`、`healthy`、`/tools` 26 tools。
- 殘留 temp-name 容器已藉 `--force-recreate` 收斂回 canonical name。

## 影響範圍

- 所有依賴 `webctl.sh refresh` 的部署驗證流程;無資料損壞。self-heal script 不受影響。
