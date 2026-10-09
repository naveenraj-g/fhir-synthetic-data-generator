"""Write the API's OpenAPI document to a file (used to generate the frontend's typed client).

    uv run python scripts/export_openapi.py ../frontend/openapi.json
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable from scripts/

# Importing the app must not create a database file or need Redis.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.main import app, mount_routers  # noqa: E402

mount_routers(app)  # routers are normally mounted in the lifespan handler

target = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
with open(target, "w", encoding="utf-8") as fh:
    json.dump(app.openapi(), fh, indent=2)
print(f"wrote {target}")
