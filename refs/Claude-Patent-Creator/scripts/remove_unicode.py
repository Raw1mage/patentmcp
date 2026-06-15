#!/usr/bin/env python3
"""
Remove all non-ASCII Unicode characters and replace with ASCII equivalents
"""

import sys
from pathlib import Path

# Unicode to ASCII replacements
REPLACEMENTS = {
    # Checkmarks and X marks
    "✓": "[OK]",
    "✅": "[OK]",
    "✔": "[OK]",
    "✗": "[X]",
    "❌": "[X]",
    "✘": "[X]",
    # Arrows
    "→": "->",
    "←": "<-",
    "↓": "|",
    "↑": "^",
    "⇒": "=>",
    "⇐": "<=",
    # Warning and info
    "⚠": "[WARNING]",
    "⚠️": "[WARNING]",
    "ℹ": "[INFO]",
    "ℹ️": "[INFO]",
    # Emojis (game, celebrations, etc.)
    "🎮": "[GPU]",
    "🍎": "[APPLE]",
    "💻": "[CPU]",
    "📦": "[PACKAGE]",
    "✨": "",  # Remove sparkles
    "🎉": "",  # Remove party popper
    # Bullets and markers
    "•": "*",
    "·": "*",
    "◦": "-",
    "▸": ">",
    "▪": "*",
    "▫": "-",
    # Quotes
    '"': '"',
    """: "'",
    """: "'",
    "‚": ",",
    "„": '"',
    # Dashes
    "—": "--",  # em dash
    "–": "-",  # en dash
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    # Misc symbols
    "©": "(c)",
    "®": "(R)",
    "™": "(TM)",
    "°": " deg",
    "±": "+/-",
    "×": "x",
    "÷": "/",
    "≤": "<=",
    "≥": ">=",
    "≈": "~=",
    "≠": "!=",
    "§": "Section ",  # Section symbol
    "¶": "Para. ",  # Paragraph symbol
    "�": "",  # Replacement character (corrupted encoding)
    # Box drawing characters - replace with ASCII equivalents
    "═": "=",
    "║": "|",
    "╔": "+",
    "╗": "+",
    "╚": "+",
    "╝": "+",
    "╠": "+",
    "╣": "+",
    "╦": "+",
    "╩": "+",
    "╬": "+",
    "─": "-",
    "│": "|",
    "┌": "+",
    "┐": "+",
    "└": "+",
    "┘": "+",
    "├": "+",
    "┤": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
}


def replace_unicode(text):
    """Replace Unicode characters with ASCII equivalents"""
    for unicode_char, ascii_equiv in REPLACEMENTS.items():
        text = text.replace(unicode_char, ascii_equiv)
    return text


def process_file(filepath):
    """Process a single file"""
    try:
        # Read with UTF-8
        with Path(filepath).open(encoding="utf-8") as f:
            content = f.read()

        # Check if file has any non-ASCII characters
        has_unicode = any(ord(c) > 127 for c in content)

        if not has_unicode:
            return False  # No changes needed

        # Replace Unicode characters
        new_content = replace_unicode(content)

        # Check if anything changed
        if new_content == content:
            return False

        # Write back with UTF-8 (but now ASCII-safe)
        with Path(filepath).open("w", encoding="utf-8") as f:
            f.write(new_content)

        return True

    except Exception as e:
        print(f"Error processing {filepath}: {e}", file=sys.stderr)
        return False


def main():
    """Process all Python and Markdown files"""
    project_root = Path(__file__).parent.parent

    # File patterns to process
    patterns = ["**/*.py", "**/*.md"]

    # Directories to exclude
    exclude_dirs = {"venv", ".git", "__pycache__", "node_modules", ".venv"}

    files_processed = 0
    files_changed = 0

    for pattern in patterns:
        for filepath in project_root.glob(pattern):
            # Skip excluded directories
            if any(excluded in filepath.parts for excluded in exclude_dirs):
                continue

            # Skip this script itself
            if filepath.name == "remove_unicode.py":
                continue

            files_processed += 1

            if process_file(filepath):
                files_changed += 1
                print(f"Updated: {filepath.relative_to(project_root)}")

    print(f"\nProcessed {files_processed} files")
    print(f"Changed {files_changed} files")
    print("All Unicode characters replaced with ASCII equivalents")


if __name__ == "__main__":
    main()
