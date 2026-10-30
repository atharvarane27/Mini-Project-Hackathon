"""P00 application health and request-context tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


def test_health_endpoint_and_request_id() -> None:
    app = create_app(
        Settings(
            app_name="AuditForge Test",
            environment="test",
            log_level="WARNING",
            database_url=None,
            database_pool_size=5,
            database_max_overflow=5,
            database_pool_timeout=30,
            database_pool_recycle=1800,
        )
    )
    response = TestClient(app).get(
        "/api/v1/health", headers={"X-Request-ID": "health-request"}
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "health-request"
    assert response.json()["data"] == {
        "status": "ok",
        "service": "AuditForge Test",
        "environment": "test",
        "database_configured": False,
        "database_connected": False,
    }


def test_composed_application_exposes_every_phase_api() -> None:
    app = create_app(
        Settings("AuditForge Test", "test", "WARNING", None, 5, 5, 30, 1800)
    )
    routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    required = {
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/ingestion/jobs"),
        ("GET", "/api/v1/transactions"),
        ("GET", "/api/v1/duplicates"),
        ("POST", "/api/v1/reconciliation/runs"),
        ("POST", "/api/v1/detectors/circular/runs"),
        ("POST", "/api/v1/detectors/splitting/runs"),
        ("POST", "/api/v1/rules/validate"),
        ("GET", "/api/v1/cases"),
        ("POST", "/api/v1/workflows/validate"),
        ("GET", "/api/v1/activity"),
        ("GET", "/api/v1/metrics"),
    }
    assert required <= routes


def test_composed_runtime_login_metrics_and_reconciliation_are_reachable() -> None:
    app = create_app(
        Settings("AuditForge Test", "test", "WARNING", None, 5, 5, 30, 1800)
    )
    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    assert login.status_code == 200
    assert "ADMIN" in login.json()["data"]["roles"]
    assert client.get("/api/v1/metrics").status_code == 200
    reconciliation = client.post(
        "/api/v1/reconciliation/runs",
        json={
            "left_source_id": "internal",
            "right_source_id": "clearing",
            "start_at": "2026-10-29T00:00:00Z",
            "end_at": "2026-10-30T00:00:00Z",
            "cutoff_at": "2026-10-29T12:00:00Z",
            "policy_version": 1,
            "snapshot_checkpoint": "empty-runtime-check",
        },
    )
    assert reconciliation.status_code == 202
    assert reconciliation.json()["data"]["result_count"] == 0


def test_upload_flows_into_transactions_reconciliation_and_detectors() -> None:
    app = create_app(
        Settings("AuditForge Test", "test", "WARNING", None, 5, 5, 30, 1800)
    )
    client = TestClient(app)
    header = (
        "external_id,transaction_reference,sender_account_id,receiver_account_id,"
        "amount,currency,occurred_at,revision,direction\n"
    )
    internal = header + "".join(
        (
            "I1,T1,A,B,25000.00,INR,2026-10-29T10:00:00Z,1,DEBIT\n",
            "I2,C1,X,Y,2000.00,INR,2026-10-29T10:10:00Z,1,DEBIT\n",
            "I3,C2,Y,Z,1900.00,INR,2026-10-29T10:20:00Z,1,DEBIT\n",
            "I4,C3,Z,X,1800.00,INR,2026-10-29T10:30:00Z,1,DEBIT\n",
            "I5,S1,S,R1,40000.00,INR,2026-10-29T11:00:00Z,1,DEBIT\n",
            "I6,S2,S,R2,35000.00,INR,2026-10-29T11:10:00Z,1,DEBIT\n",
            "I7,S3,S,R3,30000.00,INR,2026-10-29T11:20:00Z,1,DEBIT\n",
        )
    )
    clearing = header + (
        "C1,T1,A,B,24500.00,INR,2026-10-29T10:00:00Z,1,DEBIT\n"
    )
    for source, payload in (("internal", internal), ("clearing", clearing)):
        response = client.post(
            "/api/v1/ingestion/jobs",
            data={"source_system": source},
            files={"file": (f"{source}.csv", payload, "text/csv")},
            headers={"Idempotency-Key": f"upload-{source}"},
        )
        assert response.status_code == 202

    transactions = client.get("/api/v1/transactions?limit=100").json()["data"]
    assert len(transactions) == 8

    run_payload = {
        "start_at": "2026-10-29T00:00:00Z",
        "end_at": "2026-10-30T00:00:00Z",
        "policy_version": 1,
        "snapshot_checkpoint": "connected-1",
    }
    reconciliation = client.post(
        "/api/v1/reconciliation/runs",
        json={
            **run_payload,
            "left_source_id": "internal",
            "right_source_id": "clearing",
            "cutoff_at": "2026-10-29T23:59:00Z",
        },
    ).json()["data"]
    assert reconciliation["classification_counts"]["AMOUNT_MISMATCH"] == 1
    circular = client.post(
        "/api/v1/detectors/circular/runs", json=run_payload
    )
    assert circular.status_code == 202
    assert circular.json()["data"]["finding_count"] == 1
    splitting = client.post(
        "/api/v1/detectors/splitting/runs", json=run_payload
    )
    assert splitting.status_code == 202
    assert splitting.json()["data"]["finding_count"] == 1
    findings = client.get("/api/v1/findings?limit=100").json()["data"]
    assert {item["type"] for item in findings} == {
        "CIRCULAR_FLOW", "SPLITTING_PATTERN"
    }
    created = client.post(
        "/api/v1/cases",
        json={"finding_ids": [findings[0]["finding_id"]], "priority": 90},
        headers={"X-Actor-ID": "demo-admin"},
    )
    assert created.status_code == 201
    case = created.json()["data"]
    claimed = client.post(
        f"/api/v1/cases/{case['case_id']}/claim",
        json={"expected_version": case["row_version"], "worker_id": "demo-admin"},
    )
    assert claimed.status_code == 200
    login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password"},
    ).json()["data"]
    activity = client.get(
        "/api/v1/activity",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert activity.status_code == 200
    assert [item["action"] for item in activity.json()["data"]] == [
        "CASE_CREATED", "CASE_CLAIMED"
    ]


def test_user_facing_csv_fixtures_are_accepted_with_expected_quarantine() -> None:
    app = create_app(
        Settings("AuditForge Test", "test", "WARNING", None, 5, 5, 30, 1800)
    )
    client = TestClient(app)
    expectations = {
        "test_all_features.csv": (17, 0),
        "test_duplicates.csv": (5, 0),
        "test_reconciliation_internal.csv": (4, 0),
        "test_reconciliation_counterpart.csv": (4, 0),
        "test_circular.csv": (4, 0),
        "test_splitting.csv": (4, 0),
        "test_malformed.csv": (1, 5),
    }
    for index, (filename, (accepted, rejected)) in enumerate(expectations.items()):
        with (FIXTURES / filename).open("rb") as fixture:
            response = client.post(
                "/api/v1/ingestion/jobs",
                data={"source_system": f"fixture-{index}"},
                files={"file": (filename, fixture, "text/csv")},
                headers={"Idempotency-Key": f"fixture-{index}"},
            )
        assert response.status_code == 202
        assert response.json()["data"]["accepted_count"] == accepted
        assert response.json()["data"]["rejected_count"] == rejected


def test_one_upload_fixture_drives_all_financial_features() -> None:
    app = create_app(
        Settings("AuditForge Test", "test", "WARNING", None, 5, 5, 30, 1800)
    )
    client = TestClient(app)
    with (FIXTURES / "test_all_features.csv").open("rb") as fixture:
        upload = client.post(
            "/api/v1/ingestion/jobs",
            data={"source_system": "mixed-demo"},
            files={"file": ("test_all_features.csv", fixture, "text/csv")},
            headers={"Idempotency-Key": "all-features-once"},
        )
    assert upload.status_code == 202
    assert upload.json()["data"]["accepted_count"] == 17
    assert client.get("/api/v1/duplicates").json()["data"]

    period = {
        "start_at": "2026-10-29T00:00:00Z",
        "end_at": "2026-10-30T00:00:00Z",
        "policy_version": 1,
        "snapshot_checkpoint": "all-features-checkpoint",
    }
    reconciliation = client.post(
        "/api/v1/reconciliation/runs",
        json={
            **period,
            "left_source_id": "internal",
            "right_source_id": "clearing",
            "cutoff_at": period["end_at"],
        },
    ).json()["data"]
    counts = reconciliation["classification_counts"]
    assert counts["MATCHED"] == 1
    assert counts["AMOUNT_MISMATCH"] == 1
    assert counts["FIELD_MISMATCH"] == 1

    circular = client.post(
        "/api/v1/detectors/circular/runs", json=period
    ).json()["data"]
    splitting = client.post(
        "/api/v1/detectors/splitting/runs", json=period
    ).json()["data"]
    assert circular["finding_count"] == 1
    assert splitting["finding_count"] == 1
    assert len(client.get("/api/v1/findings").json()["data"]) == 2
