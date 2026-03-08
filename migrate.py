#!/usr/bin/env python3
"""
Git Provider Migrator — entry point.

All logic lives in the `migrator` package.
Run: python migrate.py [args]
"""

from migrator.cli import main

if __name__ == "__main__":
    main()
