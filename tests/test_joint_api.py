from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def reading(second: str, concentration: float) -> dict:
    return {
        "timestamp": f"2026-01-01T00:00:{second}Z",
        "concentration_ppm": concentration,
    }


def joint_payload(**overrides):
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "points": [
            {
                "point_id": "P-1",
                "readings": [
                    reading("00.000", 0),
                    reading("01.000", 2),
                    reading("02.000", 2),
                    reading("03.000", 0),
                ],
            },
            {
                "point_id": "P-2",
                "readings": [
                    reading("00.000", 0),
                    reading("00.500", 2),
                    reading("02.500", 2),
                    reading("03.000", 0),
                ],
            },
        ],
    }
    data.update(overrides)
    return data


def test_verify_joint_qualified_when_common_interval_reaches_minimum():
    response = client.post("/verify-joint", json=joint_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["warehouse_id"] == "B-07"
    assert body["point_ids"] == ["P-1", "P-2"]
    assert body["common_valid_intervals"] == [
        {
            "start_unix_ms": 1767225600500,
            "end_unix_ms": 1767225602500,
            "duration_ms": 2000,
        }
    ]
    assert body["longest_common_duration_ms"] == 2000
    assert body["qualified"] is True


def test_verify_joint_not_qualified_when_common_duration_falls_short():
    # Each point alone stays above the threshold for 2250 ms (>= 2000 ms),
    # but their overlap lasts only 1500 ms.
    points = [
        {
            "point_id": "P-1",
            "readings": [
                reading("00.000", 2),
                reading("01.500", 2),
                reading("03.000", 0),
            ],
        },
        {
            "point_id": "P-2",
            "readings": [
                reading("00.000", 0),
                reading("01.500", 2),
                reading("03.000", 2),
            ],
        },
    ]

    for point in points:
        solo = client.post(
            "/verify",
            json={
                "warehouse_id": "B-07",
                "threshold_ppm": 1,
                "minimum_duration_seconds": 2,
                "readings": point["readings"],
            },
        )
        assert solo.status_code == 200
        assert solo.json()["qualified"] is True

    response = client.post("/verify-joint", json=joint_payload(points=points))

    assert response.status_code == 200
    body = response.json()
    assert body["common_valid_intervals"] == [
        {
            "start_unix_ms": 1767225600750,
            "end_unix_ms": 1767225602250,
            "duration_ms": 1500,
        }
    ]
    assert body["longest_common_duration_ms"] == 1500
    assert body["qualified"] is False


def test_verify_joint_rejects_duplicate_point_ids_with_field_location():
    data = joint_payload()
    data["points"][1]["point_id"] = "P-1"

    response = client.post("/verify-joint", json=data)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["fields"][0]["location"] == ["body", "points", 1, "point_id"]
    assert body["error"]["fields"][0]["code"] == "value_error.duplicate_point_id"
    assert "qualified" not in body


def test_verify_joint_rejects_mismatched_series_bounds_with_field_locations():
    last_mismatch = joint_payload()
    last_mismatch["points"][1]["readings"][3] = reading("04.000", 0)

    response = client.post("/verify-joint", json=last_mismatch)

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "points", 1, "readings", 3, "timestamp"]
    assert field["code"] == "value_error.series_time_bounds_mismatch"

    first_mismatch = joint_payload()
    first_mismatch["points"][1]["readings"][0] = reading("00.250", 0)

    response = client.post("/verify-joint", json=first_mismatch)

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "points", 1, "readings", 0, "timestamp"]
    assert field["code"] == "value_error.series_time_bounds_mismatch"


def test_verify_joint_reading_errors_land_on_point_and_reading_field():
    data = joint_payload()
    data["points"][1]["readings"][0]["concentration_ppm"] = -1

    response = client.post("/verify-joint", json=data)

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    field = body["error"]["fields"][0]
    assert field["location"] == [
        "body",
        "points",
        1,
        "readings",
        0,
        "concentration_ppm",
    ]
    assert field["code"] == "value_error.negative"
    assert "qualified" not in body


def test_verify_joint_requires_two_to_ten_points():
    one_point = joint_payload()
    one_point["points"] = one_point["points"][:1]

    response = client.post("/verify-joint", json=one_point)

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "points"]
    assert field["code"] == "too_short"


def test_verify_single_point_endpoint_still_answers_representative_success():
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
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

    response = client.post("/verify", json=data)

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
