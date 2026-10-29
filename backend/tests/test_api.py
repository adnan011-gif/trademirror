"""Integration tests for TradeMirror API endpoints, limits, and static serving."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.api.routes import SAMPLE_CATALOGUE, reset_rate_limiter
from app.api.schemas import AnalysisResponse, SampleItemResponse
from app.config import settings
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_rate_limit_state() -> None:
    """Reset rate limiter state before each test execution."""
    reset_rate_limiter()


def test_health_check(client: TestClient) -> None:
    """Verify GET /api/health returns 200 and status ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers
    assert response.headers["Cache-Control"] == "no-store"


def test_samples_catalogue(client: TestClient) -> None:
    """Verify GET /api/samples returns whitelist catalogue matching schema."""
    response = client.get("/api/samples")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == len(SAMPLE_CATALOGUE)

    names = [item["name"] for item in data]
    expected_names = [
        "clean",
        "mixed",
        "messy",
        "single_holding_losers",
        "single_revenge_trading",
        "single_overtrading",
        "single_oversizing",
        "single_averaging_down",
    ]
    assert names == expected_names

    for item in data:
        validated = SampleItemResponse.model_validate(item)
        assert validated.name in expected_names
        assert len(validated.label) > 0
        assert len(validated.description) > 0


def test_whitelisted_samples_analysis(client: TestClient) -> None:
    """Verify all whitelisted sample datasets return 200 and conform to schema."""
    for item in SAMPLE_CATALOGUE:
        name = item["name"]
        response = client.get(f"/api/sample/{name}")
        assert response.status_code == 200, f"Sample '{name}' failed with {response.status_code}"
        payload = response.json()

        # Schema validation
        validated = AnalysisResponse.model_validate(payload)
        assert validated.dataset.source == name
        assert validated.narrative.source in ("template", "llm")
        assert validated.verification.passed is True

        if name == "clean":
            assert validated.material is False
            assert len(validated.habits) == 0
            assert validated.summary == "No behavioral habit cleared the evidence bar this month."

        if name == "mixed":
            assert validated.material is True
            assert len(validated.habits) == 3
            habit_keys = [h.key for h in validated.habits]
            assert habit_keys == ["holding_losers", "revenge_trading", "overtrading"]
            for habit in validated.habits:
                assert len(habit.evidence_trades) > 0
                assert len(habit.evidence_trades) <= 25
                # Verify sorted by gross_pnl ascending (largest loss first)
                pnls = [t.gross_pnl for t in habit.evidence_trades]
                assert pnls == sorted(pnls)


def test_unknown_sample_and_path_traversal(client: TestClient) -> None:
    """Verify unknown samples and path traversal variants return 404 JSON."""
    traversal_paths = [
        "unknown_sample",
        "../clean",
        "..%2fclean",
        "%2e%2e%2fclean",
        "clean/..",
        "..",
        "%2e%2e",
        "..%2f..%2fetc%2fpasswd",
        r"..\..\etc\passwd",
        r"clean\test",
    ]
    for path in traversal_paths:
        response = client.get(f"/api/sample/{path}")
        assert response.status_code == 404, f"Expected 404 for '{path}', got {response.status_code}"
        body = response.json()
        assert "detail" in body
        assert "request_id" in body



def test_upload_matches_sample_endpoint(client: TestClient) -> None:
    """Verify upload of committed CSVs matches results from sample endpoint."""
    test_datasets = ["clean", "single_overtrading", "single_oversizing", "mixed"]

    for name in test_datasets:
        filename = f"{name}.csv"
        file_path = Path(settings.SAMPLES_DIR) / filename
        content = file_path.read_bytes()

        # POST /api/analyze
        response = client.post(
            "/api/analyze",
            files={"file": (filename, content, "text/csv")},
        )
        assert response.status_code == 200, f"Upload analysis failed for {name}: {response.text}"
        upload_data = response.json()

        # GET /api/sample/{name}
        sample_response = client.get(f"/api/sample/{name}")
        assert sample_response.status_code == 200
        sample_data = sample_response.json()

        # Verify equivalent habit diagnostics
        assert upload_data["material"] == sample_data["material"]
        assert len(upload_data["habits"]) == len(sample_data["habits"])

        for u_habit, s_habit in zip(upload_data["habits"], sample_data["habits"], strict=True):
            assert u_habit["key"] == s_habit["key"]
            assert u_habit["attributed_cost_inr"] == s_habit["attributed_cost_inr"]
            assert u_habit["estimated_cost_inr"] == s_habit["estimated_cost_inr"]
            assert len(u_habit["evidence_trades"]) == len(s_habit["evidence_trades"])


def test_upload_validations_and_rejections(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify upload edge cases: oversize, row limits, schema errors, binary, empty."""
    # 1. Oversize file -> 413
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    large_payload = b"header\n" + (b"row_content_data_padding\n" * 50000)
    res_oversize = client.post(
        "/api/analyze",
        files={"file": ("test.csv", large_payload, "text/csv")},
    )
    assert res_oversize.status_code == 413
    assert "maximum upload size" in res_oversize.json()["detail"]

    # 2. Too many rows -> 422
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 5)
    monkeypatch.setattr(settings, "MAX_ROWS", 10)
    canonical_header = (
        "order_id,timestamp,symbol,instrument_type,strike,expiry,"
        "side,quantity,lot_size,price,status"
    )
    lines = [canonical_header]
    for i in range(15):
        lines.append(f"O{i},2024-10-01T09:15:00,NIFTY,FUT,0,2024-10-31,BUY,50,50,25000.0,COMPLETE")
    too_many_rows_csv = "\n".join(lines).encode("utf-8")


    res_rows = client.post(
        "/api/analyze",
        files={"file": ("test.csv", too_many_rows_csv, "text/csv")},
    )
    assert res_rows.status_code == 422
    assert "exceeds the limit of 10 rows" in res_rows.json()["detail"]

    # Restore MAX_ROWS
    monkeypatch.setattr(settings, "MAX_ROWS", 20000)

    # 3. Wrong columns -> 422 with column names
    wrong_columns_csv = b"col1,col2,col3\n1,2,3\n"
    res_wrong_cols = client.post(
        "/api/analyze",
        files={"file": ("test.csv", wrong_columns_csv, "text/csv")},
    )
    assert res_wrong_cols.status_code == 422
    detail = res_wrong_cols.json()["detail"]
    assert "missing required columns" in detail
    assert "order_id" in detail


    # 4. Empty file -> 422
    res_empty = client.post(
        "/api/analyze",
        files={"file": ("empty.csv", b"   \n", "text/csv")},
    )
    assert res_empty.status_code == 422
    assert "empty" in res_empty.json()["detail"]

    # 5. Binary garbage -> 422
    res_binary = client.post(
        "/api/analyze",
        files={"file": ("binary.csv", b"\x00\x01\x02\x03\xff\xfe", "text/csv")},
    )
    assert res_binary.status_code == 422
    assert "Binary" in res_binary.json()["detail"]

    # 6. Invalid non-CSV extension / content-type -> 422
    res_ext = client.post(
        "/api/analyze",
        files={"file": ("data.json", b'{"key": "value"}', "application/json")},
    )
    assert res_ext.status_code == 422
    assert "Only CSV files" in res_ext.json()["detail"]

    # 7. No file field supplied -> 422
    res_no_file = client.post("/api/analyze")
    assert res_no_file.status_code == 422
    assert "request_id" in res_no_file.json()


def test_response_contains_no_internal_leaks(client: TestClient) -> None:
    """Verify that the API response never leaks ground-truth paths or tracebacks."""
    response = client.get("/api/sample/mixed")
    assert response.status_code == 200
    raw_text = response.text

    assert "ground_truth" not in raw_text
    assert "data/" not in raw_text
    assert "Traceback" not in raw_text
    assert "/Users/" not in raw_text
    assert "/home/" not in raw_text
    assert "\\Users\\" not in raw_text


def test_request_id_middleware(client: TestClient) -> None:
    """Verify request ID is generated, echoed, and included in response headers."""
    # Generated ID
    res1 = client.get("/api/health")
    assert "X-Request-ID" in res1.headers
    generated_id = res1.headers["X-Request-ID"]
    assert len(generated_id) > 0

    # Echoed ID
    custom_id = "test-request-id-98765"
    res2 = client.get("/api/health", headers={"X-Request-ID": custom_id})
    assert res2.headers["X-Request-ID"] == custom_id

    # Included in error body
    res3 = client.get("/api/sample/nonexistent", headers={"X-Request-ID": custom_id})
    assert res3.status_code == 404
    assert res3.headers["X-Request-ID"] == custom_id
    assert res3.json()["request_id"] == custom_id


def test_rate_limiting(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that requests exceeding rate limit receive a 429 JSON response with Retry-After."""
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_MINUTE", 3)


    # 3 allowed requests
    for _ in range(3):
        res = client.get("/api/sample/clean")
        assert res.status_code == 200

    # 4th request must be rate limited
    res_blocked = client.get("/api/sample/clean")
    assert res_blocked.status_code == 429
    assert "Retry-After" in res_blocked.headers
    assert int(res_blocked.headers["Retry-After"]) >= 1
    assert "Rate limit exceeded" in res_blocked.json()["detail"]


def test_pipeline_exception_handling(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pipeline unexpected exceptions yield 500 without leaking stack traces."""

    def _failing_pipeline(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Unexpected internal crash at line 999: /secret/path/fail.py")

    monkeypatch.setattr("app.api.routes.run_pipeline", _failing_pipeline)

    res = client.get("/api/sample/clean")
    assert res.status_code == 500
    body = res.json()
    assert body["detail"] == "An internal server error occurred."
    assert "request_id" in body
    assert "Unexpected internal crash" not in res.text
    assert "Traceback" not in res.text
    assert "/secret/path" not in res.text


def test_static_serving_single_service(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify single-service static serving, assets cache control, and SPA fallback."""
    # Case 1: Temporary dist directory present
    tmp_dist = tmp_path / "frontend_dist"
    tmp_dist.mkdir()
    index_file = tmp_dist / "index.html"
    index_file.write_text("<!DOCTYPE html><html><body><h1>TradeMirror App</h1></body></html>")

    assets_dir = tmp_dist / "assets"
    assets_dir.mkdir()
    app_js = assets_dir / "app.1234abcd.js"
    app_js.write_text("console.log('trademirror bundle');")

    monkeypatch.setattr(settings, "FRONTEND_DIST", tmp_dist)

    # Root serves index.html
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "TradeMirror App" in res_root.text

    # SPA route fallback serves index.html
    res_spa = client.get("/dashboard/analysis/results")
    assert res_spa.status_code == 200
    assert "TradeMirror App" in res_spa.text

    # Static hashed asset served with long-lived immutable cache control
    res_asset = client.get("/assets/app.1234abcd.js")
    assert res_asset.status_code == 200
    assert "trademirror bundle" in res_asset.text
    assert res_asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    # Unknown /api path returns JSON 404, NEVER index.html!
    res_api_nope = client.get("/api/nope")
    assert res_api_nope.status_code == 404
    assert res_api_nope.headers["Content-Type"].startswith("application/json")
    assert res_api_nope.json()["detail"] == "Not Found"

    # Case 2: Frontend dist does not exist
    monkeypatch.setattr(settings, "FRONTEND_DIST", tmp_path / "nonexistent_dist")
    res_no_dist = client.get("/")
    assert res_no_dist.status_code == 200
    assert res_no_dist.json() == {"message": "TradeMirror API is running. Frontend dist not found."}
