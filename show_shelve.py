#!/usr/bin/env python3
"""
Show all keys/values from a Python shelve (default: aws_resources.db).
Usage:
  python show_shelve.py                # reads aws_resources.db in current dir
  python show_shelve.py /path/to/db    # read a specific shelve file
"""

import sys
import shelve
from pprint import pformat

def show(db_path="aws_resources.db"):
    try:
        with shelve.open(db_path, flag="r") as db:
            keys = sorted(db.keys())
            if not keys:
                print(f"(empty) — {db_path}")
                return
            print(f"Contents of {db_path}:\n")
            for k in keys:
                v = db[k]
                # pretty-print complex values; keep simple types on one line
                if isinstance(v, (dict, list, tuple, set)):
                    print(f"- {k}:")
                    print(pformat(v, indent=2, width=100))
                else:
                    print(f"- {k}: {v!r}")
    except Exception as e:
        print(f"Could not open shelve at '{db_path}': {e}")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "aws_resources.db"
    show(path)
