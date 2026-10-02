"""Write the API schema for the frontend's generated types: python scripts/export_openapi.py ../frontend/openapi.json"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enki.api import app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(app.openapi(), indent=1))
print(f"wrote {out}")
