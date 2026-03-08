import logging
import os

import requests
from flask import Flask, jsonify, request
                                                                                                                                             
app = Flask(__name__)

GEOCODING_API_URL = os.getenv("GEOCODING_API_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_API_URL = os.getenv("WEATHER_API_URL", "https://api.open-meteo.com/v1/forecast")
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Tel Aviv")
HTTP_TIMEOUT = float(os.getenv("WEATHER_HTTP_TIMEOUT_SECONDS", "8"))
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
app.logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


@app.get("/")
def root():
    return jsonify({"service": "weather-app", "status": "ok"})


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


@app.get("/readyz")
def readyz():
    return jsonify({"status": "ready"}), 200


@app.get("/weather")
def weather():
    city = request.args.get("city", DEFAULT_CITY)

    try:
        geo = requests.get(
            GEOCODING_API_URL,
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=HTTP_TIMEOUT,
        )
        geo.raise_for_status()
        geo_data = geo.json()
    except requests.RequestException as exc:
        app.logger.warning("geocoding failed for city=%s error=%s", city, exc)
        return jsonify({"error": "geocoding failed", "details": str(exc)}), 502

    results = geo_data.get("results") or []
    if not results:
        app.logger.info("city not found city=%s", city)
        return jsonify({"error": f"city not found: {city}"}), 404

    place = results[0]
    lat = place["latitude"]
    lon = place["longitude"]

    try:
        wx = requests.get(
            WEATHER_API_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=HTTP_TIMEOUT,
        )
        wx.raise_for_status()
        wx_data = wx.json()
    except requests.RequestException as exc:
        app.logger.warning("weather fetch failed city=%s error=%s", city, exc)
        return jsonify({"error": "weather fetch failed", "details": str(exc)}), 502

    current = wx_data.get("current", {})
    payload = {
        "city": place.get("name"),
        "country": place.get("country"),
        "latitude": lat,
        "longitude": lon,
        "temperature_c": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
        "time": current.get("time"),
    }
    app.logger.info(
        "weather request served city=%s country=%s temperature_c=%s",
        payload["city"],
        payload["country"],
        payload["temperature_c"],
    )
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
