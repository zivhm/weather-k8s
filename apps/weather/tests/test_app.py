from pathlib import Path
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as weather_app


def build_forecast_payload():
    start = datetime.fromisoformat("2026-03-02T00:00")
    times = [(start + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M") for hour in range(0, 48)]
    return {
        "current": {
            "temperature_2m": 24.1,
            "time": "2026-03-02T12:00",
        },
        "timezone": "Asia/Jerusalem",
        "hourly": {
            "time": times,
            "temperature_2m": [18.0 + hour * 0.5 for hour in range(0, 48)],
            "relative_humidity_2m": [55 + (hour % 6) for hour in range(0, 48)],
            "wind_speed_10m": [8.0 + hour * 0.4 for hour in range(0, 48)],
            "weather_code": [1 if hour < 24 else 3 for hour in range(0, 48)],
        },
    }


def fake_get_factory(*, no_city=False, fail_geocode=False, fail_weather=False):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        assert timeout == weather_app.HTTP_TIMEOUT

        if "geocoding-api" in url:
            if fail_geocode:
                raise weather_app.requests.RequestException("geocoder down")
            if no_city:
                return FakeResponse({"results": []})
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

        if fail_weather:
            raise weather_app.requests.RequestException("weather upstream down")

        if "hourly" in params:
            return FakeResponse(build_forecast_payload())

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

    return fake_get


def fake_get_with_timeout_retry():
    attempts = {"geocode": 0, "weather": 0}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params, timeout):
        assert timeout == weather_app.HTTP_TIMEOUT

        if "geocoding-api" in url:
            attempts["geocode"] += 1
            if attempts["geocode"] == 1:
                raise weather_app.requests.Timeout("temporary geocoder timeout")
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "Berlin",
                            "country": "Germany",
                            "latitude": 52.52,
                            "longitude": 13.405,
                        }
                    ]
                }
            )

        attempts["weather"] += 1
        if attempts["weather"] == 1:
            raise weather_app.requests.Timeout("temporary weather timeout")

        return FakeResponse(build_forecast_payload())

    return fake_get


def fake_webcam_get_factory(*, no_camera=False, webcam_error=False):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, params=None, timeout=None, headers=None):
        if "geocoding-api" in url:
            assert timeout == weather_app.HTTP_TIMEOUT
            return FakeResponse(
                {
                    "results": [
                        {
                            "name": "Vienna",
                            "country": "Austria",
                            "latitude": 48.20849,
                            "longitude": 16.37208,
                        }
                    ]
                }
            )

        if "windy.com" in url:
            assert timeout == weather_app.CAMERA_HTTP_TIMEOUT
            assert headers == {"x-windy-api-key": "test-camera-key"}
            if webcam_error:
                raise weather_app.requests.RequestException("camera upstream down")
            if no_camera:
                return FakeResponse({"webcams": []})
            return FakeResponse(
                {
                    "webcams": [
                        {
                            "title": "Vienna Square Cam",
                            "location": {
                                "latitude": 48.2091,
                                "longitude": 16.3716,
                            },
                            "player": {"live": "https://player.example/live"},
                            "urls": {"detail": "https://detail.example/cam"},
                        },
                        {
                            "title": "Vienna River Cam",
                            "webcamId": 42,
                            "location": {
                                "latitude": 48.215,
                                "longitude": 16.39,
                            },
                            "player": {"day": "https://player.example/day"},
                            "urls": {"detail": "https://detail.example/day"},
                        }
                    ]
                }
            )

        return FakeResponse(build_forecast_payload())

    return fake_get


def test_root():
    client = weather_app.app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type.startswith("text/html")
    assert b"Weather Atlas" in response.data
    assert weather_app.DEFAULT_CITY.encode() in response.data


def test_status():
    client = weather_app.app.test_client()
    response = client.get("/status")
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
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory())
    client = weather_app.app.test_client()
    response = client.get("/weather?city=Tel%20Aviv")

    assert response.status_code == 200
    body = response.get_json()
    assert body["city"] == "Tel Aviv"
    assert body["country"] == "Israel"
    assert body["temperature_c"] == 24.1


def test_weather_city_not_found(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory(no_city=True))
    client = weather_app.app.test_client()
    response = client.get("/weather?city=NoSuchCity")

    assert response.status_code == 404
    assert "city not found" in response.get_json()["error"]


def test_forecast_success(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory())
    client = weather_app.app.test_client()
    response = client.get("/forecast?city=Tel%20Aviv")

    assert response.status_code == 200
    body = response.get_json()
    assert body["city"] == "Tel Aviv"
    assert body["country"] == "Israel"
    assert body["timezone"] == "Asia/Jerusalem"
    assert len(body["hourly"]["time"]) == 24
    assert body["hourly"]["time"][0] == "2026-03-02T12:00"
    assert len(body["hourly"]["temperature_c"]) == 24
    assert len(body["hourly"]["humidity"]) == 24
    assert len(body["hourly"]["wind_kmh"]) == 24
    assert len(body["hourly"]["weather_code"]) == 24


def test_forecast_city_not_found(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory(no_city=True))
    client = weather_app.app.test_client()
    response = client.get("/forecast?city=NoSuchCity")

    assert response.status_code == 404
    assert "city not found" in response.get_json()["error"]


def test_forecast_upstream_failure(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory(fail_weather=True))
    client = weather_app.app.test_client()
    response = client.get("/forecast?city=Tel%20Aviv")

    assert response.status_code == 502
    body = response.get_json()
    assert body["error"] == "weather fetch failed"
    assert "weather upstream down" in body["details"]


def test_dashboard_data_success(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory())
    client = weather_app.app.test_client()
    response = client.get("/dashboard-data?city=Tel%20Aviv")

    assert response.status_code == 200
    body = response.get_json()
    assert body["current"]["city"] == "Tel Aviv"
    assert body["forecast"]["city"] == "Tel Aviv"
    assert len(body["forecast"]["hourly"]["time"]) == 24


def test_dashboard_data_retries_timeout(monkeypatch):
    monkeypatch.setattr(weather_app.requests, "get", fake_get_with_timeout_retry())
    client = weather_app.app.test_client()
    response = client.get("/dashboard-data?city=Berlin")

    assert response.status_code == 200
    body = response.get_json()
    assert body["current"]["city"] == "Berlin"
    assert body["forecast"]["city"] == "Berlin"
    assert len(body["forecast"]["hourly"]["time"]) == 24


def test_city_camera_disabled(monkeypatch):
    monkeypatch.setattr(weather_app, "WINDY_WEBCAMS_API_KEY", "")
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory())
    client = weather_app.app.test_client()
    response = client.get("/city-camera?city=Tel%20Aviv")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "disabled"


def test_city_camera_available(monkeypatch):
    monkeypatch.setattr(weather_app, "WINDY_WEBCAMS_API_KEY", "test-camera-key")
    monkeypatch.setattr(weather_app.requests, "get", fake_webcam_get_factory())
    client = weather_app.app.test_client()
    response = client.get("/city-camera?city=Vienna")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "available"
    assert body["city"] == "Vienna"
    assert body["provider"] == "Windy Webcams"
    assert body["player_url"] == "https://player.example/live"
    assert body["detail_url"] == "https://detail.example/cam"
    assert body["camera_count"] == 2
    assert len(body["cameras"]) == 2


def test_city_camera_unavailable_when_no_camera(monkeypatch):
    monkeypatch.setattr(weather_app, "WINDY_WEBCAMS_API_KEY", "test-camera-key")
    monkeypatch.setattr(weather_app.requests, "get", fake_webcam_get_factory(no_camera=True))
    client = weather_app.app.test_client()
    response = client.get("/city-camera?city=Vienna")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "unavailable"
    assert "No live public camera found" in body["message"]


def test_city_camera_unavailable_on_provider_error(monkeypatch):
    monkeypatch.setattr(weather_app, "WINDY_WEBCAMS_API_KEY", "test-camera-key")
    monkeypatch.setattr(weather_app.requests, "get", fake_webcam_get_factory(webcam_error=True))
    client = weather_app.app.test_client()
    response = client.get("/city-camera?city=Vienna")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "unavailable"
    assert "No live public camera found" in body["message"]


def test_city_camera_city_not_found(monkeypatch):
    monkeypatch.setattr(weather_app, "WINDY_WEBCAMS_API_KEY", "test-camera-key")
    monkeypatch.setattr(weather_app.requests, "get", fake_get_factory(no_city=True))
    client = weather_app.app.test_client()
    response = client.get("/city-camera?city=NoSuchCity")

    assert response.status_code == 404
    assert "city not found" in response.get_json()["error"]
