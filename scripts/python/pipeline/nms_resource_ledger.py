#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry for NMS Resource Ledger (split modules)."""
from pathlib import Path
import sys

# Ensure sibling imports work when invoked directly
sys.path.insert(0, str(Path(__file__).parent))

# Re-export the public API from the ledger package
from ledger import *  # noqa: F401,F403

# Entrypoint
from ledger.cli_main import main

if __name__ == "__main__":
    main()
