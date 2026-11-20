from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from citeverify_core.common.llm_client import get_llm_client  # noqa: E402

schema: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}
print(
    get_llm_client().complete_json(
        "Reply with JSON only.",
        "Return a JSON object with key ok set to true.",
        schema,
    )
)