# Handoff: mcp_r15-self-describing-guide

## Execution Contract

- 交付 `patentmcp_guide` MCP tool + `prompts/list`+`prompts/get patentmcp_guide` handler + `mcp.json`/server instructions signpost + doctrine one-source 投影(SKILL.md 為 source,啟動 fail-fast)。
- Done 定義:rebuild container 後,`patentmcp_guide` tool 與 `prompts/get patentmcp_guide` 回 byte-identical doctrine;instructions 含 signpost;source 缺失時啟動 fail-fast;對照 mcp-integration-standard §13 R15.1/R15.2/R15.3/R15.5 逐項通過。

## Required Reads

- `plans/mcp_r15-self-describing-guide/{proposal,design,spec}.md`
- `src/patent_mcp_server/patents.py`(FastMCP 初始化 line 26-40、`_RO` line 49、`@mcp.tool`/`@mcp.prompt` 註冊點)
- `src/patent_mcp_server/_http_app.py`(`_skills_root()` line 35-41 定位 SKILL.md)
- `skills/patentworks/SKILL.md`(doctrine source)、`Dockerfile`(COPY skills/ 確認)
- `/home/pkcs12/projects/opencode/specs/mcp-integration-standard/standard.md`(R15 + §13 checklist)

## Stop Gates In Force

- 無 approval gate(單 repo、既有 rail、readOnly tool);smoke 失敗即 blocker,不宣告完成。

## Execution-Ready Checklist

- [x] recon 完成:FastMCP 有 @mcp.prompt、_skills_root() 可複用、Dockerfile 已 COPY skills/
- [x] designed gate 通過、docs profile 已設
- [ ] docxmcp `bin/mcp_server.py` + `bin/_mcp_prompts.py` 範本已對照(prompts 註冊形態)
