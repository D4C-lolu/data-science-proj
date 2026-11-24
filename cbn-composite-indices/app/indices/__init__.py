"""Blueprint for uploads, asynchronous runs, results, and exports."""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pandas as pd

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from app.extensions import db
from app.indices import exports
from app.indices.configs import INDICES, INDEX_ORDER, get_config
from app.models import IndexRun

indices_bp = Blueprint("indices", __name__, url_prefix="/indices")

ACTIVE_STATUSES = ("queued", "running")


def _result_folder() -> Path:
    return Path(current_app.config["RESULT_FOLDER"])


def _upload_folder() -> Path:
    return Path(current_app.config["UPLOAD_FOLDER"])


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]


def _load_result(run: IndexRun) -> dict | None:
    if not run.result_key:
        return None
    path = _result_folder() / run.result_key
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _template_columns(config):
    """Header row for an upload template, derived from the index config."""
    if config.kind == "household":
        return ["hh_id", *config.columns, "round", "w"]
    return [config.period_col, *config.columns, "REF"]


@indices_bp.get("/template/<code>")
@login_required
def download_template(code):
    """Download a header-only CSV or Excel upload template for one index."""
    config = INDICES.get(code.strip().upper())
    if config is None:
        abort(404)

    fmt = (request.args.get("fmt") or "csv").lower()
    frame = pd.DataFrame(columns=_template_columns(config))
    base = f"{config.code.lower()}_upload_template"

    if fmt in {"xlsx", "excel"}:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            frame.to_excel(writer, index=False, sheet_name="Template")
        return _send_bytes(
            buffer.getvalue(),
            f"{base}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if fmt == "csv":
        return _send_bytes(frame.to_csv(index=False).encode("utf-8"), f"{base}.csv", "text/csv")

    abort(404)


@indices_bp.get("/")
@login_required
def landing():
    catalogue = [
        {
            "code": code,
            "name": INDICES[code].name,
            "kind": INDICES[code].kind,
            "description": INDICES[code].description,
            "indicators": len(INDICES[code].columns),
            "pillars": len(INDICES[code].pillars),
        }
        for code in INDEX_ORDER
    ]
    recent = db.session.scalars(
        select(IndexRun)
        .filter_by(user_id=current_user.id)
        .order_by(IndexRun.created_at.desc())
        .limit(5)
    ).all()
    return render_template("indices/landing.html", catalogue=catalogue, recent=recent)


@indices_bp.get("/upload")
@login_required
def upload_form():
    return render_template(
        "indices/upload.html",
        indices=[INDICES[c] for c in INDEX_ORDER],
    )


@indices_bp.post("/upload")
@login_required
def upload_submit():
    index_type = (request.form.get("index_type") or "").strip().upper()
    if index_type not in INDICES:
        flash("Choose a valid index before uploading a file.", "info")
        return redirect(url_for("indices.upload_form"))

    file = request.files.get("dataset")
    if file is None or file.filename == "":
        flash("Attach a CSV or Excel file to continue.", "info")
        return redirect(url_for("indices.upload_form"))

    if not _allowed(file.filename):
        flash("Only CSV, XLSX, or XLS files are supported.", "info")
        return redirect(url_for("indices.upload_form"))

    extension = file.filename.rsplit(".", 1)[1].lower()
    upload_key = f"{uuid.uuid4().hex}.{extension}"
    _upload_folder().mkdir(parents=True, exist_ok=True)
    file.save(_upload_folder() / upload_key)

    run = IndexRun(
        user_id=current_user.id,
        index_type=index_type,
        status="queued",
        original_filename=file.filename[:255],
        upload_key=upload_key,
    )
    db.session.add(run)
    db.session.commit()

    from app.tasks import compute_indices

    compute_indices.delay(run.id)

    flash(f"{get_config(index_type).name} run queued.", "success")
    return redirect(url_for("indices.run_detail", run_id=run.id))


@indices_bp.get("/runs")
@login_required
def runs():
    return render_template("indices/runs.html")


@indices_bp.get("/runs/fragment")
@login_required
def runs_fragment():
    user_runs = db.session.scalars(
        select(IndexRun)
        .filter_by(user_id=current_user.id)
        .order_by(IndexRun.created_at.desc())
        .limit(50)
    ).all()
    has_active = any(r.status in ACTIVE_STATUSES for r in user_runs)
    response = render_template("indices/_runs_table.html", runs=user_runs)
    if has_active:
        return response, 200, {"HX-Trigger-After-Settle": "keep-polling"}
    return response, 200, {"HX-Trigger-After-Settle": "stop-polling"}


@indices_bp.get("/<int:run_id>")
@login_required
def run_detail(run_id):
    run = db.session.get(IndexRun, run_id)
    if run is None or run.user_id != current_user.id:
        abort(404)
    result = _load_result(run)
    return render_template("indices/detail.html", run=run, result=result, config=INDICES.get(run.index_type))


@indices_bp.get("/<int:run_id>/status")
@login_required
def run_status(run_id):
    run = db.session.get(IndexRun, run_id)
    if run is None or run.user_id != current_user.id:
        abort(404)
    return jsonify(
        {
            "id": run.id,
            "status": run.status,
            "error": run.error_message,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
    )


@indices_bp.get("/<int:run_id>/download/<fmt>")
@login_required
def run_download(run_id, fmt):
    run = db.session.get(IndexRun, run_id)
    if run is None or run.user_id != current_user.id:
        abort(404)
    result = _load_result(run)
    if result is None:
        abort(404)

    base = f"{run.index_type.lower()}_{run.id}"
    if fmt == "json":
        payload = exports.to_json(result).encode("utf-8")
        return _send_bytes(payload, f"{base}.json", "application/json")
    if fmt == "csv":
        payload = exports.to_csv(result).encode("utf-8")
        return _send_bytes(payload, f"{base}.csv", "text/csv")
    if fmt in {"xlsx", "excel"}:
        payload = exports.to_excel(result)
        return _send_bytes(payload, f"{base}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    abort(404)


def _send_bytes(payload: bytes, download_name: str, mimetype: str):
    return send_file(io.BytesIO(payload), download_name=download_name, as_attachment=True, mimetype=mimetype)