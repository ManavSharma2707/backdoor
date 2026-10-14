"""Write the OpenAPI document that frontend types are generated from.

`python -m app.jobs.run openapi` regenerates `backend/openapi.json`. A test fails when the
committed file differs from what the app produces, so a route change cannot ship without it.
"""

import json
from pathlib import Path
from typing import Any

from app.core.config import Settings

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def build_schema() -> dict[str, Any]:
    from app.main import create_app

    # Fixed settings, so the document does not depend on the machine it was made on.
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    schema: dict[str, Any] = app.openapi()
    return schema


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_openapi(path: Path = OPENAPI_PATH) -> Path:
    path.write_text(render(build_schema()), encoding="utf-8", newline="\n")
    return path
