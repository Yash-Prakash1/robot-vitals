"""Put src/ on the import path so tests import the modules directly.

Keeps the repo zero-install: no packaging, no editable pip install, just run
pytest from the repo root.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
