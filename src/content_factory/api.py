"""Optional FastAPI HTTP API for content-factory.

Install with: pip install content-factory[api]
Run with: uvicorn content_factory.api:app --reload
"""

from __future__ import annotations

try:
    from fastapi import FastAPI, HTTPException
except ImportError:
    raise ImportError(
        "FastAPI is not installed. Install with: pip install content-factory[api]"
    )

from content_factory.models import Brief
from content_factory.storage import create_run_dir, find_run_dir, list_runs, read_json, write_json

api = FastAPI(title="content-factory", version="0.1.0")


@api.get("/runs")
def get_runs(output: str = "runs", n: int = 20):
    return {"runs": list_runs(output, limit=n)}


@api.get("/runs/{run_id}/artifact/{name}")
def get_artifact(run_id: str, name: str, output: str = "runs"):
    run_dir = find_run_dir(output, run_id)
    if run_dir is None:
        raise HTTPException(404, f"Run not found: {run_id}")
    from content_factory.storage import artifact_path

    try:
        ap = artifact_path(run_dir, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not ap.exists():
        raise HTTPException(404, f"Artifact not found: {name}")
    return {"content": ap.read_text(encoding="utf-8")}
