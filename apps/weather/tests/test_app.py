from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as weather_app


def test_root():
    client = weather_app.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.get_json() == {"service": "weather-app", "status": "ok"}


def test_healthz():
    client = weather_app.app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readyz():
    client = weather_app.app.test_client()
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}


def test_weather_success(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        if "geocoding-api" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "Tel Aviv",
                            "country": "Israel",
                            "latitude": 32.0853,
                            "longitude": 34.7818,
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "current": {
                    "temperature_2m": 24.1,
                    "relative_humidity_2m": 52,
                    "wind_speed_10m": 13.2,
                    "weather_code": 3,
                    "time": "2026-03-02T12:00",
                }
            }
        )

    monkeypatch.setattr(weather_app.requests, "get", fake_get)
    client = weather_app.app.test_client()
    response = client.get("/weather?city=Tel%20Aviv")

    assert response.status_code == 200
    body = response.get_json()
    assert body["city"] == "Tel Aviv"
    assert body["country"] == "Israel"
    assert body["temperature_c"] == 24.1


def test_weather_city_not_found(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    def fake_get(url, params, timeout):
        return FakeResponse()

    monkeypatch.setattr(weather_app.requests, "get", fake_get)
    client = weather_app.app.test_client()
    response = client.get("/weather?city=NoSuchCity")

    assert response.status_code == 404
    assert "city not found" in response.get_json()["error"]
