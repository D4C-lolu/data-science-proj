import requests
import time
import uuid
from pathlib import Path

BASE = "http://web:8000"
DATASETS = Path("/reference")

SAMPLES = {
    "BCI": "bci_simulated_dataset.csv",
    "CCI": "cci_simulated_dataset.csv",
    "HFCI": "hfci_simulated_dataset.csv",
    "IPI": "ipi_simulated_dataset.csv",
    "LMCI": "lmci_simulated_dataset.csv",
}


def csrf(resp):
    import re
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.text)
    return m.group(1) if m else None


def signup(s):
    unique = uuid.uuid4().hex[:10]
    form = s.get(f"{BASE}/auth/signup")
    r = s.post(
        f"{BASE}/auth/signup",
        data={
            "csrf_token": csrf(form),
            "email": f"qa_{unique}@example.com",
            "username": f"qa_{unique}",
            "password": "qa-password-12345",
            "confirm_password": "qa-password-12345",
        },
        allow_redirects=False,
    )
    assert r.status_code in (200, 302), f"signup failed: {r.status_code}\n{r.text[:300]}"


def upload_and_wait(s, code):
    form = s.get(f"{BASE}/indices/upload")
    with open(DATASETS / SAMPLES[code], "rb") as handle:
        r = s.post(
            f"{BASE}/indices/upload",
            data={"csrf_token": csrf(form), "index_type": code},
            files={"dataset": (SAMPLES[code], handle, "text/csv")},
            allow_redirects=False,
        )
    assert r.status_code in (301, 302), f"{code} upload failed: {r.status_code}\n{r.text[:300]}"
    run_id = r.headers.get("Location", "").rstrip("/").split("/")[-1]
    assert run_id.isdigit(), f"{code}: bad location {r.headers.get('Location')!r}"

    for _ in range(40):
        status = s.get(f"{BASE}/indices/{run_id}/status").json().get("status")
        if status in ("succeeded", "failed"):
            break
        time.sleep(2)
    assert status == "succeeded", f"{code}: final status {status}"

    detail = s.get(f"{BASE}/indices/{run_id}")
    assert detail.status_code == 200, f"{code}: detail page {detail.status_code}"

    for fmt in ("csv", "xlsx", "json"):
        dl = s.get(f"{BASE}/indices/{run_id}/download/{fmt}")
        assert dl.status_code == 200, f"{code}: download {fmt} {dl.status_code}"

    print(f"  {code}: OK (run {run_id})")


def main():
    s = requests.Session()
    signup(s)
    print("Smoke test: uploading all 5 indices")
    for code in SAMPLES:
        upload_and_wait(s, code)
    print("All indices processed successfully.")


if __name__ == "__main__":
    main()