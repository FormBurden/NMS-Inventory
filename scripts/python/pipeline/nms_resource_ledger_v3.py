#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibility shim for nms_resource_ledger_v3.py.

This file now defers to nms_resource_ledger.py, preserving CLI and imports.
"""
from pathlib import Path
import sys

# Ensure sibling imports work when invoked directly
sys.path.insert(0, str(Path(__file__).parent))

# Re-export all public API
from nms_resource_ledger import *  # noqa: F401,F403

if __name__ == "__main__":
    from nms_resource_ledger import main
    main()
