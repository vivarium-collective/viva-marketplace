from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# scripts/*.py are standalone CLI entry points, not part of the viva_marketplace
# package — add them to sys.path so tests can import them directly (e.g.
# `import validate_modules`).
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
