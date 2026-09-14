from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

_EPOCH = 1767225600000  # 2026-01-01T00:00:00.000Z, Unix milliseconds.


def reading(second: str, concentration: float) -> dict:
    return {
        "timestamp": f"2026-01-01T00:00:{second}Z",
        "concentration_ppm": concentration,
    }


def window_payload(**overrides):
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "window_start": "2026-01-01T00:00:00.250Z",
        "window_end": "2026-01-01T00:00:02.750Z",
        "readings": [
            reading("00.000", 0),
            reading("01.000", 2),
            reading("02.000", 2),
            reading("03.000", 0),
            reading("04.000", 0),
            reading("05.000", 2),
            reading("06.000", 2),
            reading("07.000", 0),
        ],
    }
    data.update(overrides)
    return data


def test_window_qualified_when_continuously_valid_inside_window():
    # The window [1250, 2750] clips the full-series interval [500, 2500]:
    # the virtual start endpoint sits on the 2 ppm plateau, so the interval
    # runs from the window edge to the interpolated crossing at 2500 ms.
    response = client.post(
        "/verify-window",
        json=window_payload(
            minimum_duration_seconds=1.25,
            window_start="2026-01-01T00:00:01.250Z",
            window_end="2026-01-01T00:00:02.750Z",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["warehouse_id"] == "B-07"
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 1250,
            "end_unix_ms": _EPOCH + 2500,
            "duration_ms": 1250,
        },
    ]
    assert body["longest_duration_ms"] == 1250
    assert body["qualified"] is True
    assert body["window_start_unix_ms"] == _EPOCH + 1250
    assert body["window_end_unix_ms"] == _EPOCH + 2750


def test_window_interpolated_cut_points_yield_definite_interval():
    # Both bounds fall between samples. The virtual endpoints interpolate to
    # 0.5 ppm, and the threshold crossings at 500 ms / 2500 ms lie strictly
    # inside the window, so the interval is fully determined by the cut.
    response = client.post("/verify-window", json=window_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 500,
            "end_unix_ms": _EPOCH + 2500,
            "duration_ms": 2000,
        },
    ]
    assert body["longest_duration_ms"] == 2000
    assert body["qualified"] is True
    assert body["window_start_unix_ms"] == _EPOCH + 250
    assert body["window_end_unix_ms"] == _EPOCH + 2750


def test_window_not_qualified_when_only_outside_window_is_valid():
    data = window_payload(
        window_start="2026-01-01T00:00:03.000Z",
        window_end="2026-01-01T00:00:05.000Z",
    )

    response = client.post("/verify-window", json=data)

    assert response.status_code == 200
    body = response.json()
    # Only the 500 ms tail of the second interval survives inside the
    # window; the 2000 ms first interval is entirely outside and ignored.
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 4500,
            "end_unix_ms": _EPOCH + 5000,
            "duration_ms": 500,
        },
    ]
    assert body["longest_duration_ms"] == 500
    assert body["qualified"] is False

    # The same series without a window qualifies, proving the window alone
    # excludes the out-of-window valid time from the decision.
    plain = {key: data[key] for key in data if not key.startswith("window_")}
    plain_response = client.post("/verify", json=plain)
    assert plain_response.status_code == 200
    assert plain_response.json()["longest_duration_ms"] == 2000
    assert plain_response.json()["qualified"] is True


def test_window_bounds_on_samples_reuse_them_without_shifting_intervals():
    response = client.post(
        "/verify-window",
        json=window_payload(
            window_start="2026-01-01T00:00:01.000Z",
            window_end="2026-01-01T00:00:02.000Z",
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 1000,
            "end_unix_ms": _EPOCH + 2000,
            "duration_ms": 1000,
        },
    ]
    assert body["longest_duration_ms"] == 1000
    assert body["qualified"] is False


def test_window_covering_full_span_matches_verify_response():
    data = window_payload(
        window_start="2026-01-01T00:00:00.000Z",
        window_end="2026-01-01T00:00:07.000Z",
    )

    window_response = client.post("/verify-window", json=data)
    plain = {key: data[key] for key in data if not key.startswith("window_")}
    verify_response = client.post("/verify", json=plain)

    assert window_response.status_code == 200
    assert verify_response.status_code == 200
    window_body = window_response.json()
    verify_body = verify_response.json()
    assert {key: window_body[key] for key in verify_body} == verify_body
    assert set(window_body) == {
        *verify_body,
        "window_start_unix_ms",
        "window_end_unix_ms",
    }
    assert window_body["window_start_unix_ms"] == _EPOCH
    assert window_body["window_end_unix_ms"] == _EPOCH + 7000


def test_window_start_before_first_reading_is_a_field_level_error():
    response = client.post(
        "/verify-window",
        json=window_payload(window_start="2025-12-31T23:59:59.999Z"),
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    field = body["error"]["fields"][0]
    assert field["location"] == ["body", "window_start"]
    assert field["code"] == "value_error.window_outside_span"
    assert field["context"] == {
        "window_start_unix_ms": _EPOCH - 1,
        "first_reading_unix_ms": _EPOCH,
        "last_reading_unix_ms": _EPOCH + 7000,
    }
    assert "qualified" not in body
    assert "valid_intervals" not in body


def test_window_end_after_last_reading_is_a_field_level_error():
    response = client.post(
        "/verify-window",
        json=window_payload(window_end="2026-01-01T00:00:07.001Z"),
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    field = body["error"]["fields"][0]
    assert field["location"] == ["body", "window_end"]
    assert field["code"] == "value_error.window_outside_span"
    assert "qualified" not in body


def test_inverted_window_is_a_field_level_error():
    response = client.post(
        "/verify-window",
        json=window_payload(
            window_start="2026-01-01T00:00:05.000Z",
            window_end="2026-01-01T00:00:01.000Z",
        ),
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    field = body["error"]["fields"][0]
    assert field["location"] == ["body", "window_end"]
    assert field["code"] == "value_error.window_not_ordered"
    assert field["context"] == {
        "window_start_unix_ms": _EPOCH + 5000,
        "window_end_unix_ms": _EPOCH + 1000,
    }
    assert "qualified" not in body


def test_zero_length_window_is_a_field_level_error():
    response = client.post(
        "/verify-window",
        json=window_payload(
            window_start="2026-01-01T00:00:01.000Z",
            window_end="2026-01-01T00:00:01.000Z",
        ),
    )

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "window_end"]
    assert field["code"] == "value_error.window_not_ordered"


def test_window_keeps_single_point_field_validations():
    data = window_payload()
    data["readings"][1]["concentration_ppm"] = -1

    response = client.post("/verify-window", json=data)

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "readings", 1, "concentration_ppm"]
    assert field["code"] == "value_error.negative"

    response = client.post(
        "/verify-window",
        json=window_payload(window_start="2026-01-01T00:00:00Z"),
    )

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "window_start"]
    assert field["code"] == "value_error.invalid_timestamp"
