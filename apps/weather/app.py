import logging
import os
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request


def load_local_env():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_local_env()

app = Flask(__name__)

GEOCODING_API_URL = os.getenv("GEOCODING_API_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_API_URL = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
WEBCAM_API_URL = os.getenv("WEBCAM_API_URL", "https://api.windy.com/webcams/api/v3/webcams")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tel Aviv")
HTTP_TIMEOUT = float(os.getenv("WEATHER_HTTP_TIMEOUT_SECONDS", "12"))
CAMERA_HTTP_TIMEOUT = float(os.getenv("CAMERA_HTTP_TIMEOUT_SECONDS", "6"))
WEBCAM_SEARCH_RADIUS_KM = float(os.getenv("WEBCAM_SEARCH_RADIUS_KM", "30"))
WINDY_WEBCAMS_API_KEY = os.getenv("WINDY_WEBCAMS_API_KEY", "").strip()
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_STATUS = {"service": "weather-app", "status": "ok"}
CURRENT_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
]
HOURLY_FIELDS = [
    "temperature_2m",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
]
UPSTREAM_RETRIES = 1

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
app.logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


@app.get("/")
def root():
    return render_template("index.html", default_city=DEFAULT_CITY)


@app.get("/status")
def status():
    return jsonify(SERVICE_STATUS)


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@app.get("/readyz")
def readyz():
    return jsonify({"status": "ready"}), 200


class WeatherServiceError(Exception):
    def __init__(self, message, status_code, details=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


def request_upstream_json(url, *, params, failure_message, log_context):
    last_error = None

    for attempt in range(UPSTREAM_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            last_error = exc
            app.logger.warning(
                "%s timed out attempt=%s/%s context=%s error=%s",
                failure_message,
                attempt + 1,
                UPSTREAM_RETRIES + 1,
                log_context,
                exc,
            )
        except requests.RequestException as exc:
            app.logger.warning("%s context=%s error=%s", failure_message, log_context, exc)
            raise WeatherServiceError(failure_message, 502, str(exc)) from exc

    raise WeatherServiceError(failure_message, 502, str(last_error)) from last_error


def format_radius_km(value):
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def haversine_distance_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)
    origin_lat = radians(lat1)
    target_lat = radians(lat2)

    a = (
        sin(delta_lat / 2) ** 2
        + cos(origin_lat) * cos(target_lat) * sin(delta_lon / 2) ** 2
    )
    return 2 * earth_radius_km * asin(sqrt(a))


def geocode_city(city):
    geo_data = request_upstream_json(
        GEOCODING_API_URL,
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        failure_message="geocoding failed",
        log_context=f"city={city}",
    )

    results = geo_data.get("results") or []
    if not results:
        app.logger.info("city not found city=%s", city)
        raise WeatherServiceError(f"city not found: {city}", 404)

    place = results[0]
    return {
        "city": place.get("name"),
        "country": place.get("country"),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
    }


def fetch_weather_data(latitude, longitude, *, current_fields=None, hourly_fields=None):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": "auto",
    }
    if current_fields:
        params["current"] = ",".join(current_fields)
    if hourly_fields:
        params["hourly"] = ",".join(hourly_fields)
        params["forecast_days"] = 2

    return request_upstream_json(
        WEATHER_API_URL,
        params=params,
        failure_message="weather fetch failed",
        log_context=f"latitude={latitude} longitude={longitude}",
    )


def build_error_response(error):
    payload = {"error": error.message}
    if error.details:
        payload["details"] = error.details
    return jsonify(payload), error.status_code


def build_current_payload(place, wx_data):
    current = wx_data.get("current", {})
    return {
        "city": place["city"],
        "country": place["country"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "temperature_c": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
        "time": current.get("time"),
    }


def build_forecast_payload(place, wx_data):
    current_time = (wx_data.get("current") or {}).get("time")
    hourly = wx_data.get("hourly") or {}
    hourly_times = hourly.get("time") or []
    start_index = 0
    if current_time in hourly_times:
        start_index = hourly_times.index(current_time)
    end_index = start_index + 24

    return {
        "city": place["city"],
        "country": place["country"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": wx_data.get("timezone"),
        "hourly": {
            "time": hourly_times[start_index:end_index],
            "temperature_c": (hourly.get("temperature_2m") or [])[start_index:end_index],
            "humidity": (hourly.get("relative_humidity_2m") or [])[start_index:end_index],
            "wind_kmh": (hourly.get("wind_speed_10m") or [])[start_index:end_index],
            "weather_code": (hourly.get("weather_code") or [])[start_index:end_index],
        },
    }


def camera_disabled_payload():
    return {
        "status": "disabled",
        "message": "Live city cameras are not configured for this deployment.",
    }


def camera_unavailable_payload(place, message):
    return {
        "status": "unavailable",
        "city": place["city"],
        "country": place["country"],
        "message": message,
        "attribution_text": "Webcams provided by windy.com",
        "attribution_url": "https://www.windy.com/",
    }


def extract_webcam_list(payload):
    if isinstance(payload.get("webcams"), list):
        return payload["webcams"]
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("webcams"), list):
        return result["webcams"]
    return []


def pick_webcam_player_url(webcam):
    player = webcam.get("player")
    if isinstance(player, str) and player:
        return player
    if isinstance(player, dict):
        for key in ("day", "lifetime", "live", "default"):
            value = player.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def pick_webcam_detail_url(webcam):
    urls = webcam.get("urls")
    if isinstance(urls, str) and urls:
        return urls
    if isinstance(urls, dict):
        for key in ("detail", "web", "current", "edit"):
            value = urls.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def build_camera_payload(place, webcam):
    location = webcam.get("location") or {}
    webcam_lat = location.get("latitude") or location.get("lat")
    webcam_lon = location.get("longitude") or location.get("lng") or location.get("lon")
    distance_km = None
    if webcam_lat is not None and webcam_lon is not None:
        distance_km = round(
            haversine_distance_km(
                place["latitude"],
                place["longitude"],
                float(webcam_lat),
                float(webcam_lon),
            ),
            1,
        )

    return {
        "status": "available",
        "city": place["city"],
        "country": place["country"],
        "title": webcam.get("title") or webcam.get("name") or "Live city camera",
        "provider": "Windy Webcams",
        "distance_km": distance_km,
        "camera_id": webcam.get("webcamId"),
        "player_url": pick_webcam_player_url(webcam),
        "detail_url": pick_webcam_detail_url(webcam),
        "source_url": (webcam.get("urls") or {}).get("provider")
        if isinstance(webcam.get("urls"), dict)
        else None,
        "attribution_text": "Webcams provided by windy.com",
        "attribution_url": "https://www.windy.com/",
    }


def fetch_city_camera(place):
    if not WINDY_WEBCAMS_API_KEY:
        return camera_disabled_payload()

    headers = {"x-windy-api-key": WINDY_WEBCAMS_API_KEY}
    params = {
        "nearby": (
            f'{place["latitude"]},{place["longitude"]},'
            f'{format_radius_km(WEBCAM_SEARCH_RADIUS_KM)}'
        ),
        "include": "location,player,urls",
        "lang": "en",
        "limit": 10,
    }

    try:
        response = requests.get(
            WEBCAM_API_URL,
            params=params,
            headers=headers,
            timeout=CAMERA_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        webcams = extract_webcam_list(response.json())
    except requests.RequestException as exc:
        response_text = ""
        if getattr(exc, "response", None) is not None and exc.response is not None:
            response_text = exc.response.text[:300]
        app.logger.warning(
            "city camera unavailable city=%s params=%s error=%s response=%s",
            place["city"],
            params,
            exc,
            response_text or "<no response body>",
        )
        return camera_unavailable_payload(
            place,
            "No live public camera found near this city right now.",
        )

    scored_webcams = []
    for webcam in webcams:
        player_url = pick_webcam_player_url(webcam)
        if not player_url:
            continue
        location = webcam.get("location") or {}
        webcam_lat = location.get("latitude") or location.get("lat")
        webcam_lon = location.get("longitude") or location.get("lng") or location.get("lon")
        if webcam_lat is None or webcam_lon is None:
            continue
        scored_webcams.append(
            (
                haversine_distance_km(
                    place["latitude"],
                    place["longitude"],
                    float(webcam_lat),
                    float(webcam_lon),
                ),
                webcam,
            )
        )

    if not scored_webcams:
        return camera_unavailable_payload(
            place,
            "No live public camera found near this city right now.",
        )

    scored_webcams.sort(key=lambda item: item[0])
    cameras = [build_camera_payload(place, webcam) for _, webcam in scored_webcams[:6]]
    primary_camera = cameras[0]
    return {
        **primary_camera,
        "status": "available",
        "camera_count": len(cameras),
        "cameras": cameras,
    }


@app.get("/weather")
def weather():
    city = request.args.get("city", DEFAULT_CITY)

    try:
        place = geocode_city(city)
        wx_data = fetch_weather_data(
            place["latitude"],
            place["longitude"],
            current_fields=CURRENT_FIELDS,
        )
    except WeatherServiceError as error:
        return build_error_response(error)

    payload = build_current_payload(place, wx_data)
    app.logger.info(
        "weather request served city=%s country=%s temperature_c=%s",
        payload["city"],
        payload["country"],
        payload["temperature_c"],
    )
    return jsonify(payload)


@app.get("/forecast")
def forecast():
    city = request.args.get("city", DEFAULT_CITY)

    try:
        place = geocode_city(city)
        wx_data = fetch_weather_data(
            place["latitude"],
            place["longitude"],
            current_fields=["temperature_2m"],
            hourly_fields=HOURLY_FIELDS,
        )
    except WeatherServiceError as error:
        return build_error_response(error)

    payload = build_forecast_payload(place, wx_data)
    app.logger.info(
        "forecast request served city=%s country=%s points=%s",
        payload["city"],
        payload["country"],
        len(payload["hourly"]["time"]),
    )
    return jsonify(payload)


@app.get("/dashboard-data")
def dashboard_data():
    city = request.args.get("city", DEFAULT_CITY)

    try:
        place = geocode_city(city)
        wx_data = fetch_weather_data(
            place["latitude"],
            place["longitude"],
            current_fields=CURRENT_FIELDS,
            hourly_fields=HOURLY_FIELDS,
        )
    except WeatherServiceError as error:
        return build_error_response(error)

    payload = {
        "current": build_current_payload(place, wx_data),
        "forecast": build_forecast_payload(place, wx_data),
    }
    app.logger.info(
        "dashboard data served city=%s country=%s points=%s",
        payload["current"]["city"],
        payload["current"]["country"],
        len(payload["forecast"]["hourly"]["time"]),
    )
    return jsonify(payload)


@app.get("/city-camera")
def city_camera():
    city = request.args.get("city", DEFAULT_CITY)

    try:
        place = geocode_city(city)
    except WeatherServiceError as error:
        return build_error_response(error)

    payload = fetch_city_camera(place)
    app.logger.info(
        "city camera lookup served city=%s status=%s",
        place["city"],
        payload["status"],
    )
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
