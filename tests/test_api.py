from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def payload(**overrides):
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "readings": [
            {
                "timestamp": "2026-01-01T00:00:00.000Z",
                "concentration_ppm": 0,
            },
            {
                "timestamp": "2026-01-01T00:00:01.000Z",
                "concentration_ppm": 2,
            },
            {
                "timestamp": "2026-01-01T00:00:02.000Z",
                "concentration_ppm": 2,
            },
            {
                "timestamp": "2026-01-01T00:00:03.000Z",
                "concentration_ppm": 0,
            },
            {
                "timestamp": "2026-01-01T00:00:04.000Z",
                "concentration_ppm": 0,
            },
            {
                "timestamp": "2026-01-01T00:00:05.000Z",
                "concentration_ppm": 2,
            },
            {
                "timestamp": "2026-01-01T00:00:06.000Z",
                "concentration_ppm": 2,
            },
            {
                "timestamp": "2026-01-01T00:00:07.000Z",
                "concentration_ppm": 0,
            },
        ],
    }
    data.update(overrides)
    return data


def test_verify_success_uses_longest_single_interval_only():
    response = client.post("/verify", json=payload())

    assert response.status_code == 200
    body = response.json()
    assert body["warehouse_id"] == "B-07"
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": 1767225600500,
            "end_unix_ms": 1767225602500,
            "duration_ms": 2000,
        },
        {
            "start_unix_ms": 1767225604500,
            "end_unix_ms": 1767225606500,
            "duration_ms": 2000,
        },
    ]
    assert body["longest_duration_ms"] == 2000
    assert body["qualified"] is True


def test_verify_rejects_when_separate_intervals_each_are_too_short():
    data = payload(minimum_duration_seconds=2.5)

    response = client.post("/verify", json=data)

    assert response.status_code == 200
    body = response.json()
    assert body["longest_duration_ms"] == 2000
    assert body["qualified"] is False


def test_verify_validation_error_is_field_level_and_produces_no_decision():
    data = payload()
    data["readings"][1]["concentration_ppm"] = -1

    response = client.post("/verify", json=data)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"][0]["location"] == [
        "body",
        "readings",
        1,
        "concentration_ppm",
    ]
    assert "qualified" not in body


def test_verify_rejects_malformed_body_with_field_locations():
    response = client.post(
        "/verify",
        json=payload(
            minimum_duration_seconds=0,
            threshold_ppm=-2,
            extra_field=True,
        ),
    )

    assert response.status_code == 422
    locations = {
        tuple(field["location"][1:])
        for field in response.json()["error"]["fields"]
    }
    assert ("minimum_duration_seconds",) in locations
    assert ("threshold_ppm",) in locations
    assert ("extra_field",) in locations


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
