"""R17.1.1 structured capability summary — patentmcp_init returns prose + capabilities.

plan patentmcp_r17-minimum-operational-toolset, tasks 2.3, TV-5/TV-6.
"""
import asyncio
import json
import os

os.environ.setdefault("PATENTS_SKILLS_ROOT", "skills")

from patent_mcp_server import patents


def _init_result():
    """Invoke the init tool the way the module exposes it, tolerant of the
    FastMCP callable wrapper. The registered coroutine returns {doctrine, capabilities}."""
    # The @mcp.tool decorator returns a FunctionTool; its underlying coroutine is
    # reachable via .fn on FastMCP's FunctionTool, else fall back to the registry.
    tool = patents.mcp._tool_manager._tools.get("patentmcp_init")
    assert tool is not None, "patentmcp_init not registered"
    return asyncio.run(tool.fn())


def test_init_returns_doctrine_and_capabilities():
    r = _init_result()
    assert set(r.keys()) == {"doctrine", "capabilities"}


# ── TV-5: doctrine byte-identical to guide / prompts-get ───────────
def test_doctrine_byte_identical_to_guide():
    r = _init_result()
    assert r["doctrine"] == patents._guide_doctrine()


def test_doctrine_byte_identical_to_prompt_face():
    # prompts/get face projects the same _guide_doctrine(); assert equality
    r = _init_result()
    assert r["doctrine"] == patents.patentmcp_init_prompt()


# ── TV-6: endpoint visibility + no host-executable container socket ─
def test_every_transport_endpoint_has_visibility():
    caps = _init_result()["capabilities"]
    for e in caps["transport"]["endpoints"]:
        assert e["visibility"] in ("container", "host-visible", "protocol"), e


def test_container_socket_tagged_container():
    caps = _init_result()["capabilities"]
    mcp_eps = caps["transport"]["endpoints"]
    container = [e for e in mcp_eps if e["path"] == "/mcp"]
    assert container and container[0]["visibility"] == "container"


def test_no_container_socket_presented_host_executable():
    caps = _init_result()["capabilities"]
    blob = json.dumps(caps)
    # a host-executable recipe pinning a container socket path is exactly the
    # R17.6 scenario-2 failure — assert it never appears
    assert "--unix-socket" not in blob
    assert ".sock" not in blob


def test_capabilities_cover_required_axes():
    caps = _init_result()["capabilities"]
    for key in ("transport", "file_ingress", "file_egress", "webdav_state",
                "companion_skill", "conditional_families"):
        assert key in caps, key
    # portable egress is the resources/read floor
    assert caps["file_egress"]["portable"]["kind"] == "resources/read"
    # webdav lifecycle present
    assert "cache_provision" in caps["webdav_state"]["lifecycle"]
    assert "cache_close" in caps["webdav_state"]["lifecycle"]
    # companion skill is patentworks
    assert caps["companion_skill"]["name"] == "patentworks"
