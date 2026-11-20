"""Celery tasks for asynchronous index computation."""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.extensions import celery, db
from app.indices.calculators import compute
from app.indices.configs import get_config
from app.models import IndexRun

logger = logging.getLogger(__name__)

READERS = {
    "csv": lambda path: pd.read_csv(path),
    "xlsx": lambda path: pd.read_excel(path, engine="openpyxl"),
    "xls": lambda path: pd.read_excel(path),
}


def _result_folder():
    from flask import current_app

    return Path(current_app.config["RESULT_FOLDER"])


def _upload_folder():
    from flask import current_app

    return Path(current_app.config["UPLOAD_FOLDER"])


def _load_dataframe(upload_key: str) -> pd.DataFrame:
    path = _upload_folder() / upload_key
    suffix = path.suffix.lower().lstrip(".")
    reader = READERS.get(suffix)
    if reader is None:
        raise ValueError(f"Unsupported file type: .{suffix}")
    return reader(path)


@celery.task(name="app.tasks.compute_indices", bind=True)
def compute_indices(self, run_id: int):
    """Compute an index run end to end and persist its result."""
    run = db.session.get(IndexRun, run_id)
    if run is None:
        logger.warning("IndexRun %s no longer exists; skipping.", run_id)
        return {"run_id": run_id, "status": "missing"}

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    run.error_message = None
    db.session.commit()

    result_key = f"{run.upload_key.rsplit('.', 1)[0]}_{run.index_type}.json"
    result_path = _result_folder() / result_key

    try:
        config = get_config(run.index_type)
        data = _load_dataframe(run.upload_key)
        result = compute(config, data)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        db.session.rollback()
        run = db.session.get(IndexRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        logger.exception("Index run %s failed", run_id)
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    try:
        result["uid"] = run.upload_key
        result_path.parent.mkdir(parents=True, exist_ok=True)
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, default=str)

        run.result_key = result_key
        run.result_metadata = {
            "meta": result.get("meta", {}),
            "index_name": result.get("index_name"),
            "sections": [{"key": s.get("key"), "title": s.get("title"), "kind": s.get("kind")} for s in result.get("sections", [])],
        }
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        run = db.session.get(IndexRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error_message = f"Could not persist result: {exc}"
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        logger.exception("Index run %s failed while saving results", run_id)
        return {"run_id": run_id, "status": "failed", "error": str(exc)}

    return {"run_id": run_id, "status": "succeeded", "result_key": result_key}