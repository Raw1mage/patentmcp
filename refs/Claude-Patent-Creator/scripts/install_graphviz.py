#!/usr/bin/env python3
"""
Graphviz Installation Helper for claude-patent-creator
Run this script to check and install Graphviz on your system
"""

import sys
from pathlib import Path

# Script is in scripts/, go up to project root, then into mcp_server/
project_root = Path(__file__).parent.parent
mcp_server_path = project_root / "mcp_server"
sys.path.insert(0, str(mcp_server_path))

try:
    from graphviz_installer import GraphvizInstaller  # type: ignore # noqa: E402
except ImportError:
    print(f"Error: Could not find graphviz_installer module in {mcp_server_path}")
    print("Please ensure the module exists in the mcp_server directory.")
    sys.exit(1)


def main():
    print("=" * 60)
    print("Graphviz Installation Helper")
    print("claude-patent-creator MCP Server")
    print("=" * 60)
    print()

    installer = GraphvizInstaller()
    print(installer.get_diagnostic_info())
    print()

    if installer.status["ready"]:
        print("[OK] Graphviz is ready to use!")
        print(f"  Version: {installer.status['version']}")
        print(f"  Location: {installer.status['dot_executable']}")
        return 0

    print("[WARNING] Graphviz is not properly installed.")
    print()

    response = input("Would you like to attempt automatic installation? (y/n): ")

    if response.lower() in ["y", "yes"]:
        print()
        print("Attempting automatic installation...")
        print()

        success, message = installer.try_auto_install()
        print(message)
        print()

        if success:
            print("[OK] Installation completed!")
            print()
            print("IMPORTANT: You may need to restart your terminal or IDE")
            print("           for the changes to take effect.")
            return 0
        else:
            print("[X] Automatic installation failed or not available.")
            print()
            print("Please follow the manual installation instructions above.")
            return 1
    else:
        print()
        print("Manual installation required.")
        print("Please follow the instructions above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
