import json
import re

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)

_EPOCH = 1767225600000  # 2026-01-01T00:00:00.000Z, Unix milliseconds.


def conservative_payload(**overrides):
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 0.5,
        "measurement_error_ppm": 0.5,
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
        ],
    }
    data.update(overrides)
    return data


def test_conservative_qualified_when_adjusted_interval_still_reaches_minimum():
    response = client.post("/verify-conservative", json=conservative_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["warehouse_id"] == "B-07"
    # Adjusted series is 0 -> 1.5 -> 1.5 -> 0; threshold 1 is crossed two
    # thirds of a millisecond segment in, rounding to 667 ms / 2333 ms.
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 667,
            "end_unix_ms": _EPOCH + 2333,
            "duration_ms": 1666,
        },
    ]
    assert body["longest_duration_ms"] == 1666
    assert body["longest_duration_ms"] >= 500
    assert body["qualified"] is True
    assert body["measurement_error_ppm"] == 0.5


def test_conservative_echoes_integral_bound_as_json_number():
    response = client.post(
        "/verify-conservative",
        json=conservative_payload(measurement_error_ppm=0),
    )

    assert response.status_code == 200
    # Parsed raw JSON keeps the value numeric and equal to the submitted bound.
    assert json.loads(response.text)["measurement_error_ppm"] == 0
    assert response.json()["measurement_error_ppm"] == 0


def test_conservative_not_qualified_when_deduction_makes_it_fail():
    # Without deduction the triangular ramp is above threshold for 2000 ms;
    # deducting 0.75 ppm leaves an 800 ms interval (crossings at 80% of each
    # ramp), below the 2000 ms minimum.
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "measurement_error_ppm": 0.75,
        "readings": [
            {
                "timestamp": "2026-01-01T00:00:00.000Z",
                "concentration_ppm": 0,
            },
            {
                "timestamp": "2026-01-01T00:00:02.000Z",
                "concentration_ppm": 2,
            },
            {
                "timestamp": "2026-01-01T00:00:04.000Z",
                "concentration_ppm": 0,
            },
        ],
    }

    response = client.post("/verify-conservative", json=data)

    assert response.status_code == 200
    body = response.json()
    assert body["valid_intervals"] == [
        {
            "start_unix_ms": _EPOCH + 1600,
            "end_unix_ms": _EPOCH + 2400,
            "duration_ms": 800,
        },
    ]
    assert body["longest_duration_ms"] == 800
    assert body["qualified"] is False
    assert body["measurement_error_ppm"] == 0.75


def test_conservative_clamps_deducted_concentrations_at_zero():
    # Every sample is below the 1 ppm error bound, so the adjusted series is
    # all zeros and no interval is produced.
    response = client.post(
        "/verify-conservative",
        json=conservative_payload(
            measurement_error_ppm=1,
            readings=[
                {
                    "timestamp": "2026-01-01T00:00:00.000Z",
                    "concentration_ppm": 0.2,
                },
                {
                    "timestamp": "2026-01-01T00:00:02.000Z",
                    "concentration_ppm": 0.4,
                },
            ],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid_intervals"] == []
    assert body["longest_duration_ms"] == 0
    assert body["qualified"] is False
    assert body["measurement_error_ppm"] == 1


def test_conservative_rejects_negative_bound_without_decision():
    response = client.post(
        "/verify-conservative",
        json=conservative_payload(measurement_error_ppm=-0.5),
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "validation_error"
    field = body["error"]["fields"][0]
    assert field["location"] == ["body", "measurement_error_ppm"]
    assert field["code"] == "value_error.negative"
    assert "qualified" not in body
    assert "valid_intervals" not in body


def test_conservative_rejects_non_finite_bound_without_decision():
    for token in ("Infinity", "-Infinity", "NaN"):
        raw = json.dumps(conservative_payload())
        raw = re.sub(r'"measurement_error_ppm": [^,}]+',
                     f'"measurement_error_ppm": {token}', raw, count=1)

        response = client.post(
            "/verify-conservative",
            content=raw,
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 422
        body = response.json()
        assert set(body) == {"error"}
        field = body["error"]["fields"][0]
        assert field["location"] == ["body", "measurement_error_ppm"]
        assert field["code"] == "value_error.not_finite"
        assert "qualified" not in body


def test_conservative_rejects_four_decimal_place_bound_without_decision():
    raw = json.dumps(conservative_payload())
    raw = raw.replace(
        '"measurement_error_ppm": 0.5,',
        '"measurement_error_ppm": 0.0001,',
    )
    assert "0.0001" in raw

    response = client.post(
        "/verify-conservative",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    field = body["error"]["fields"][0]
    assert field["location"] == ["body", "measurement_error_ppm"]
    assert field["code"] == "value_error.too_many_decimal_places"
    assert "qualified" not in body
    assert "valid_intervals" not in body


def test_conservative_invalid_bound_blocks_representation_even_when_readings_bad():
    # A 422 on the bound never leaks a decision, even with other bad input.
    data = conservative_payload(measurement_error_ppm=-1)
    data["readings"][0]["concentration_ppm"] = -3

    response = client.post("/verify-conservative", json=data)

    assert response.status_code == 422
    locations = {
        tuple(field["location"][1:])
        for field in response.json()["error"]["fields"]
    }
    assert ("measurement_error_ppm",) in locations
    assert ("readings", 0, "concentration_ppm") in locations
    assert "qualified" not in response.json()


def test_conservative_keeps_single_point_field_validations():
    data = conservative_payload()
    data["readings"][1]["timestamp"] = data["readings"][0]["timestamp"]

    response = client.post("/verify-conservative", json=data)

    assert response.status_code == 422
    field = response.json()["error"]["fields"][0]
    assert field["location"] == ["body", "readings"]
    assert field["code"] == "value_error.timestamps_not_strictly_increasing"


def test_zero_bound_verify_conservative_matches_verify_representative_body():
    data = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "readings": [
            {"timestamp": "2026-01-01T00:00:00.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:01.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:02.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:03.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:04.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:05.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:06.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:07.000Z", "concentration_ppm": 0},
        ],
    }

    verify_response = client.post("/verify", json=data)
    conservative_response = client.post(
        "/verify-conservative",
        json={**data, "measurement_error_ppm": 0},
    )

    assert verify_response.status_code == 200
    assert conservative_response.status_code == 200
    plain_body = verify_response.json()
    conservative_body = conservative_response.json()

    expected = {
        "warehouse_id": "B-07",
        "valid_intervals": [
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
        ],
        "longest_duration_ms": 2000,
        "qualified": True,
    }
    assert plain_body == expected
    # Every original field is byte-for-byte identical; the conservative
    # response only adds the echoed bound, so existing parsers stay valid.
    assert {key: conservative_body[key] for key in expected} == expected
    assert conservative_body["measurement_error_ppm"] == 0
    assert set(conservative_body) == {*expected, "measurement_error_ppm"}


def test_verify_and_verify_joint_representative_requests_unchanged():
    single = {
        "warehouse_id": "B-07",
        "threshold_ppm": 1,
        "minimum_duration_seconds": 2,
        "readings": [
            {"timestamp": "2026-01-01T00:00:00.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:01.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:02.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:03.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:04.000Z", "concentration_ppm": 0},
            {"timestamp": "2026-01-01T00:00:05.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:06.000Z", "concentration_ppm": 2},
            {"timestamp": "2026-01-01T00:00:07.000Z", "concentration_ppm": 0},
        ],
    }
    single_response = client.post("/verify", json=single)
    assert single_response.json() == {
        "warehouse_id": "B-07",
        "valid_intervals": [
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
        ],
        "longest_duration_ms": 2000,
        "qualified": True,
    }

    def reading(second, concentration):
        return {
            "timestamp": f"2026-01-01T00:00:{second}Z",
            "concentration_ppm": concentration,
        }

    joint = {
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
    joint_response = client.post("/verify-joint", json=joint)
    assert joint_response.json() == {
        "warehouse_id": "B-07",
        "point_ids": ["P-1", "P-2"],
        "common_valid_intervals": [
            {
                "start_unix_ms": 1767225600500,
                "end_unix_ms": 1767225602500,
                "duration_ms": 2000,
            }
        ],
        "longest_common_duration_ms": 2000,
        "qualified": True,
    }
