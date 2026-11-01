"""Compatibility entry point. Projects installed before the move to backend/ still call <repo>/smart_router.py.

The real implementation lives in backend/smart_router.py. Remove this file once every installed project's
center.connection.json points at backend/smart_router.py (re-run scripts/install_project.py for each).
"""
import runpy
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / 'backend'
sys.path.insert(0, str(BACKEND))
runpy.run_path(str(BACKEND / 'smart_router.py'), run_name='__main__')
