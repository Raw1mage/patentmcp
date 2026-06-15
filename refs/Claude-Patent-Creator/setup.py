#!/usr/bin/env python3
"""
Minimal setup.py - delegates to pyproject.toml
PyTorch installation is handled by 'patent-creator setup' CLI command
"""

from setuptools import setup

# All configuration is in pyproject.toml (PEP 621)
# PyTorch is installed separately by the CLI setup command
# to ensure correct GPU/CPU version based on hardware detection

if __name__ == "__main__":
    setup()
