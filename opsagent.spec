# PyInstaller spec for OpsAgent-MCP
# Builds a single self-contained executable that includes all MCP servers.
#
# Build:
#   pip install pyinstaller
#   pyinstaller opsagent.spec
#
# Output: dist/opsagent  (or dist/opsagent.exe on Windows)

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

# Collect everything from fastmcp and mcp (they use dynamic imports internally)
fastmcp_datas, fastmcp_binaries, fastmcp_hiddenimports = collect_all("fastmcp")
mcp_datas, mcp_binaries, mcp_hiddenimports = collect_all("mcp")

# copy_metadata includes the .dist-info directories that importlib.metadata needs
# at runtime (e.g. fastmcp calls importlib.metadata.version("fastmcp") on import)
metadata_datas = (
    copy_metadata("fastmcp")
    + copy_metadata("mcp")
    + copy_metadata("langchain-anthropic")
    + copy_metadata("langchain-core")
    + copy_metadata("langchain-mcp-adapters")
    + copy_metadata("langgraph")
    + copy_metadata("anthropic")
    + copy_metadata("httpx")
)

a = Analysis(
    ["cli.py"],
    pathex=["."],
    binaries=fastmcp_binaries + mcp_binaries,
    datas=fastmcp_datas + mcp_datas + metadata_datas,
    hiddenimports=[
        # CLI banner
        "banner",
        # Our MCP server modules
        "mcp_tools.workspace_server",
        "mcp_tools.git_server",
        "mcp_tools.notification_server",
        "mcp_tools.log_analyzer",
        # LangChain / LangGraph internals use dynamic imports
        "langchain_anthropic",
        "langchain_core",
        "langchain_mcp_adapters",
        "langgraph",
        "langgraph.graph",
        "langgraph.prebuilt",
        # FastMCP / MCP
        *fastmcp_hiddenimports,
        *mcp_hiddenimports,
        # Other deps
        "httpx",
        "dotenv",
        "click",
        "anthropic",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="opsagent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,         # CLI tool — keep console output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,     # set by GitHub Actions matrix per platform
    codesign_identity=None,
    entitlements_file=None,
)
