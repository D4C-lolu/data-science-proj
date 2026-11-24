import io
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from app.extensions import db
from app.indices.calculators import compute
from app.indices.configs import INDICES
from app.models import IndexRun


def _login(client):
    client.post(
        "/auth/signup",
        data={
            "email": "test@example.com",
            "username": "testuser",
            "password": "secure-password-1",
            "confirm_password": "secure-password-1",
        },
    )


def _bci_csv():
    """Return a minimal BCI-shaped CSV as bytes (non-singular correlations)."""
    cols = list(INDICES["BCI"].columns)
    rng = pd.RangeIndex(8)
    data = {}
    for i, c in enumerate(cols):
        data[c] = (rng * (i + 1) + rng ** 2 * 0.1 + (i % 3)).astype(float)
    data["Quarter"] = ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    df = pd.DataFrame(data)
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer.read()


def test_upload_requires_login(client):
    response = client.get("/indices/upload")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]

    response = client.post(
        "/indices/upload",
        data={"index_type": "BCI"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_upload_creates_run_and_redirects(client, app):
    _login(client)
    response = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(_bci_csv()), "bci.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    run_id = response.headers["Location"].rstrip("/").split("/")[-1]
    assert run_id.isdigit()

    with app.app_context():
        run = db.session.get(IndexRun, int(run_id))
        assert run is not None
        assert run.index_type == "BCI"
        assert run.user.username == "testuser"
        assert run.status == "succeeded"
        assert run.result_key is not None


def test_upload_rejects_invalid_extension(client):
    _login(client)
    response = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(b"not a csv"), "data.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/indices/upload" in response.headers["Location"]


def test_upload_missing_columns_fails_gracefully(client, app):
    _login(client)
    bad_csv = "Quarter,SomeOtherColumn\n2023Q1,1.0\n2023Q2,2.0\n"
    response = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(bad_csv.encode()), "bad.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    run_id = response.headers["Location"].rstrip("/").split("/")[-1]

    with app.app_context():
        run = db.session.get(IndexRun, int(run_id))
        assert run.status == "failed"
        assert run.error_message is not None
        assert "column" in run.error_message.lower() or "key" in run.error_message.lower()


def test_runs_fragment_htmx(client):
    _login(client)
    client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(_bci_csv()), "bci.csv"),
        },
        content_type="multipart/form-data",
    )
    response = client.get(
        "/indices/runs/fragment",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert b"BCI" in response.data
    assert b"Succeeded" in response.data


def test_run_detail_renders(client):
    _login(client)
    upload_resp = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(_bci_csv()), "bci.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    run_id = upload_resp.headers["Location"].rstrip("/").split("/")[-1]

    response = client.get(f"/indices/{run_id}")
    assert response.status_code == 200
    assert b"Business Confidence Index" in response.data


def test_run_status_json(client):
    _login(client)
    upload_resp = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(_bci_csv()), "bci.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    run_id = upload_resp.headers["Location"].rstrip("/").split("/")[-1]

    response = client.get(f"/indices/{run_id}/status")
    assert response.status_code == 200
    assert response.json["status"] == "succeeded"
    assert response.json["id"] == int(run_id)


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json"])
def test_download_formats(client, fmt):
    _login(client)
    upload_resp = client.post(
        "/indices/upload",
        data={
            "index_type": "BCI",
            "dataset": (io.BytesIO(_bci_csv()), "bci.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    run_id = upload_resp.headers["Location"].rstrip("/").split("/")[-1]

    response = client.get(f"/indices/{run_id}/download/{fmt}")
    assert response.status_code == 200
    assert response.content_length is not None
    if fmt == "xlsx":
        assert response.data[:2] == b"PK"


def test_template_download_requires_login(client):
    response = client.get("/indices/template/BCI?fmt=csv")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_upload_page_offers_template_links(client):
    _login(client)
    response = client.get("/indices/upload")
    assert response.status_code == 200
    assert b"/indices/template/BCI?fmt=csv" in response.data
    assert b"/indices/template/BCI?fmt=xlsx" in response.data
    assert b"Need a starting file?" in response.data


@pytest.mark.parametrize("code", list(INDICES))
def test_csv_template_headers(client, code):
    _login(client)
    config = INDICES[code]
    if config.kind == "household":
        expected = ["hh_id", *config.columns, "round", "w"]
    else:
        expected = [config.period_col, *config.columns, "REF"]

    response = client.get(f"/indices/template/{code}?fmt=csv")
    assert response.status_code == 200
    header = response.get_data(as_text=True).splitlines()[0].split(",")
    assert header == expected


def test_excel_template_headers(client):
    _login(client)
    response = client.get("/indices/template/LMCI?fmt=xlsx")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.data), read_only=True)
    sheet = workbook.active
    assert [cell.value for cell in sheet[1]] == ["Quarter", *INDICES["LMCI"].columns, "REF"]


def test_template_rejects_unknown_index_and_format(client):
    _login(client)
    assert client.get("/indices/template/NOPE").status_code == 404
    assert client.get("/indices/template/BCI?fmt=pdf").status_code == 404


def test_calculator_result_contract():
    config = INDICES["BCI"]
    cols = list(config.columns)
    rng = pd.RangeIndex(8)
    data = {c: (rng * (i + 1) + rng ** 2 * 0.1 + (i % 3)).astype(float) for i, c in enumerate(cols)}
    data["Quarter"] = ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    df = pd.DataFrame(data)
    result = compute(config, df)

    assert result["index_type"] == "BCI"
    assert result["kind"] == "quarterly"
    assert "meta" in result
    assert "sections" in result
    keys = {s["key"] for s in result["sections"]}
    assert {"indicators", "weights", "pillar_totals", "index_series", "decision_summary"} <= keys


def test_calculator_missing_columns_raises():
    config = INDICES["BCI"]
    df = pd.DataFrame({"Quarter": ["2023Q1", "2023Q2"], "wrong": [1.0, 2.0]})
    with pytest.raises(KeyError):
        compute(config, df)