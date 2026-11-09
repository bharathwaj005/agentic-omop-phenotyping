# >>> fresh-clone defaults
import os as _os
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
# A fresh clone has no .env: required settings get safe test defaults (a real .env or environment value always wins).
# The test suite uses a fake LLM, so model names below are labels only; no secrets are needed or set.
_os.environ.setdefault("PROJECT_ROOT", str(_ROOT))
_d = _ROOT / ".local" / "hdd_root"; _d.mkdir(parents=True, exist_ok=True); _os.environ.setdefault("HDD_ROOT", str(_d))
_os.environ.setdefault("A_MODEL_SMALL", "qwen2.5:7b")
_os.environ.setdefault("A_MODEL_STRONG", "qwen2.5:7b")
# <<< fresh-clone defaults
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
