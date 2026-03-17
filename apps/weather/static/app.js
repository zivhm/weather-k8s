const SVG_NS = "http://www.w3.org/2000/svg";

const refs = {
  body: document.body,
  form: document.getElementById("search-form"),
  input: document.getElementById("city-input"),
  button: document.getElementById("search-button"),
  hint: document.getElementById("search-hint"),
  heroCity: document.getElementById("hero-city"),
  heroSummary: document.getElementById("hero-summary"),
  heroTemperature: document.getElementById("hero-temperature"),
  heroIcon: document.getElementById("hero-icon"),
  heroUpdated: document.getElementById("hero-updated"),
  metricTemperature: document.getElementById("metric-temperature"),
  metricHumidity: document.getElementById("metric-humidity"),
  metricWind: document.getElementById("metric-wind"),
  metricTime: document.getElementById("metric-time"),
  chart: document.getElementById("trend-chart"),
  chartLegend: document.getElementById("chart-legend"),
  cameraPanel: document.getElementById("camera-panel"),
  hourlyRail: document.getElementById("hourly-rail"),
  feedbackPanel: document.getElementById("feedback-panel"),
  feedbackMessage: document.getElementById("feedback-message"),
};

let activeCameraPayload = null;

const weatherCodeLabels = [
  { codes: [0], label: "Clear" },
  { codes: [1], label: "Mostly clear" },
  { codes: [2], label: "Partly cloudy" },
  { codes: [3], label: "Overcast" },
  { codes: [45, 48], label: "Misty" },
  { codes: [51, 53, 55, 56, 57], label: "Drizzle" },
  { codes: [61, 63, 65, 66, 67, 80, 81, 82], label: "Rain" },
  { codes: [71, 73, 75, 77, 85, 86], label: "Snow" },
  { codes: [95, 96, 99], label: "Thunder" },
];

function weatherLabel(code) {
  const match = weatherCodeLabels.find((entry) => entry.codes.includes(code));
  return match ? match.label : "Conditions";
}

function weatherTheme(code) {
  if (code === 0 || code === 1) {
    return "clear";
  }
  if (code === 2 || code === 3) {
    return "cloud";
  }
  if (code === 45 || code === 48) {
    return "mist";
  }
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) {
    return "rain";
  }
  if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) {
    return "snow";
  }
  if (code >= 95 && code <= 99) {
    return "storm";
  }
  return "cloud";
}

function weatherSky(timeValue) {
  if (!timeValue) {
    return "day";
  }

  const date = new Date(timeValue);
  if (Number.isNaN(date.getTime())) {
    return "day";
  }

  return date.getHours() < 6 || date.getHours() >= 18 ? "night" : "day";
}

function applyWeatherTheme(weather) {
  refs.body.dataset.theme = weatherTheme(weather.weather_code);
  refs.body.dataset.sky = weatherSky(weather.time);
}

function formatTemperature(value) {
  return typeof value === "number" ? `${Math.round(value)}°C` : "--";
}

function formatPercent(value) {
  return typeof value === "number" ? `${Math.round(value)}%` : "--";
}

function formatWind(value) {
  return typeof value === "number" ? `${Math.round(value)} km/h` : "--";
}

function formatTime(value, options) {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en", options).format(date);
}

function setFeedback(message, state) {
  refs.feedbackMessage.textContent = message;
  refs.feedbackPanel.classList.remove("loading", "error");
  if (state) {
    refs.feedbackPanel.classList.add(state);
  }
}

function setLoadingState(isLoading, city) {
  refs.button.disabled = isLoading;
  refs.button.textContent = isLoading ? "Exploring..." : "Explore";
  refs.input.setAttribute("aria-busy", String(isLoading));
  if (isLoading) {
    setFeedback(`Loading the latest view for ${city}...`, "loading");
  }
}

function fetchJson(url) {
  return fetch(url, {
    headers: {
      Accept: "application/json",
    },
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || "Request failed");
    }
    return payload;
  });
}

function updateCurrentWeather(weather) {
  applyWeatherTheme(weather);
  const summary = `${weatherLabel(weather.weather_code)} in ${weather.city}, ${weather.country}`;
  refs.heroCity.textContent = `${weather.city}, ${weather.country}`;
  refs.heroSummary.textContent = summary;
  refs.heroTemperature.textContent = formatTemperature(weather.temperature_c);
  refs.heroIcon.textContent = weatherLabel(weather.weather_code);
  refs.heroUpdated.textContent = `Updated ${formatTime(weather.time, {
    hour: "numeric",
    minute: "2-digit",
    weekday: "short",
  })}`;

  refs.metricTemperature.textContent = formatTemperature(weather.temperature_c);
  refs.metricHumidity.textContent = formatPercent(weather.humidity);
  refs.metricWind.textContent = formatWind(weather.wind_kmh);
  refs.metricTime.textContent = formatTime(weather.time, {
    hour: "numeric",
    minute: "2-digit",
    weekday: "short",
  });
}

function clearNode(node) {
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function renderChart(hourly) {
  clearNode(refs.chart);
  const times = hourly.time || [];
  const temperatures = hourly.temperature_c || [];
  const themeStyles = getComputedStyle(refs.body);
  const chartLine = themeStyles.getPropertyValue("--chart-line").trim() || "#bb5b34";
  const chartFill =
    themeStyles.getPropertyValue("--chart-fill").trim() || "rgba(187, 91, 52, 0.16)";
  const chartDot = themeStyles.getPropertyValue("--chart-dot").trim() || "#6f2e1c";
  const chartAxis = themeStyles.getPropertyValue("--chart-axis").trim() || "#6d6258";
  const chartText = themeStyles.getPropertyValue("--chart-text").trim() || "#1e1a17";

  if (!times.length || !temperatures.length) {
    refs.chartLegend.textContent = "Trend data is unavailable right now.";
    return;
  }

  const width = 720;
  const height = 260;
  const padding = { top: 18, right: 22, bottom: 34, left: 18 };
  const min = Math.min(...temperatures);
  const max = Math.max(...temperatures);
  const range = Math.max(max - min, 1);

  const points = temperatures.map((value, index) => {
    const x =
      padding.left +
      (index / Math.max(temperatures.length - 1, 1)) * (width - padding.left - padding.right);
    const normalized = (value - min) / range;
    const y = height - padding.bottom - normalized * (height - padding.top - padding.bottom);
    return { x, y, value, time: times[index] };
  });

  const area = document.createElementNS(SVG_NS, "path");
  const line = document.createElementNS(SVG_NS, "path");
  const baselineY = height - padding.bottom;
  const start = points[0];
  const end = points[points.length - 1];
  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const areaPath = `${linePath} L ${end.x} ${baselineY} L ${start.x} ${baselineY} Z`;

  area.setAttribute("d", areaPath);
  area.setAttribute("fill", chartFill);
  line.setAttribute("d", linePath);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", chartLine);
  line.setAttribute("stroke-width", "4");
  line.setAttribute("stroke-linejoin", "round");
  line.setAttribute("stroke-linecap", "round");

  refs.chart.append(area, line);

  points.forEach((point, index) => {
    if (index % 4 !== 0 && index !== points.length - 1) {
      return;
    }

    const dot = document.createElementNS(SVG_NS, "circle");
    const label = document.createElementNS(SVG_NS, "text");
    const tempLabel = document.createElementNS(SVG_NS, "text");

    dot.setAttribute("cx", point.x);
    dot.setAttribute("cy", point.y);
    dot.setAttribute("r", "5");
    dot.setAttribute("fill", chartDot);

    label.setAttribute("x", point.x);
    label.setAttribute("y", String(height - 8));
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("font-size", "12");
    label.setAttribute("fill", chartAxis);
    label.textContent = formatTime(point.time, { hour: "numeric" });

    tempLabel.setAttribute("x", point.x);
    tempLabel.setAttribute("y", String(point.y - 12));
    tempLabel.setAttribute("text-anchor", "middle");
    tempLabel.setAttribute("font-size", "12");
    tempLabel.setAttribute("fill", chartText);
    tempLabel.textContent = `${Math.round(point.value)}°`;

    refs.chart.append(dot, label, tempLabel);
  });

  refs.chartLegend.innerHTML = "";
  [
    `Low ${Math.round(min)}°C`,
    `High ${Math.round(max)}°C`,
    `24 hourly points`,
  ].forEach((text) => {
    const chip = document.createElement("span");
    chip.textContent = text;
    refs.chartLegend.appendChild(chip);
  });
}

function renderHourlyRail(hourly) {
  clearNode(refs.hourlyRail);
  const times = hourly.time || [];

  if (!times.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Hourly details are unavailable right now.";
    refs.hourlyRail.appendChild(empty);
    return;
  }

  times.forEach((time, index) => {
    const card = document.createElement("article");
    const timeLabel = document.createElement("span");
    const temp = document.createElement("strong");
    const label = document.createElement("span");
    const meta = document.createElement("p");

    card.className = "hourly-card";
    timeLabel.className = "hourly-time";
    temp.className = "hourly-temp";
    label.className = "hourly-label";
    meta.className = "hourly-meta";

    timeLabel.textContent = formatTime(time, {
      hour: "numeric",
      weekday: index === 0 ? "short" : undefined,
    });
    temp.textContent = formatTemperature(hourly.temperature_c[index]);
    label.textContent = weatherLabel(hourly.weather_code[index]);
    meta.textContent = `${formatPercent(hourly.humidity[index])} humidity | ${formatWind(
      hourly.wind_kmh[index],
    )}`;

    card.append(timeLabel, temp, label, meta);
    refs.hourlyRail.appendChild(card);
  });
}

function renderCameraState(payload) {
  clearNode(refs.cameraPanel);

  if (payload.status === "available") {
    const shell = document.createElement("div");
    const frameWrap = document.createElement("div");
    const frame = document.createElement("iframe");
    const meta = document.createElement("aside");
    const title = document.createElement("h4");
    const selectorWrap = document.createElement("div");
    const selectorLabel = document.createElement("label");
    const selector = document.createElement("select");
    const copy = document.createElement("p");
    const link = document.createElement("a");
    const attribution = document.createElement("p");
    const selectedCamera = payload.cameras && payload.cameras.length ? payload.cameras[0] : payload;

    shell.className = "camera-shell";
    frameWrap.className = "camera-frame-wrap";
    frame.className = "camera-frame";
    meta.className = "camera-meta";
    selectorWrap.className = "camera-selector";
    copy.className = "camera-copy";
    link.className = "camera-link";
    attribution.className = "camera-attribution";

    activeCameraPayload = payload;

    frame.src = selectedCamera.player_url;
    frame.title = selectedCamera.title;
    frame.loading = "lazy";
    frame.referrerPolicy = "strict-origin-when-cross-origin";
    frame.allow = "fullscreen";

    title.textContent = selectedCamera.title;
    copy.textContent = selectedCamera.distance_km
      ? `${selectedCamera.provider} camera about ${selectedCamera.distance_km} km from ${selectedCamera.city}.`
      : `${selectedCamera.provider} camera near ${selectedCamera.city}.`;
    link.href = selectedCamera.detail_url || selectedCamera.player_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "Open full camera";
    attribution.innerHTML = `${selectedCamera.attribution_text} <a href="${selectedCamera.attribution_url}" target="_blank" rel="noreferrer">Source</a>`;

    if (payload.cameras && payload.cameras.length > 1) {
      selectorLabel.htmlFor = "camera-select";
      selectorLabel.textContent = "Switch camera";
      selector.id = "camera-select";
      payload.cameras.forEach((camera, index) => {
        const option = document.createElement("option");
        const distance = camera.distance_km ? ` - ${camera.distance_km} km` : "";
        option.value = String(index);
        option.textContent = `${camera.title}${distance}`;
        selector.appendChild(option);
      });
      selector.addEventListener("change", (event) => {
        const camera = activeCameraPayload.cameras[Number(event.target.value)];
        frame.src = camera.player_url;
        frame.title = camera.title;
        title.textContent = camera.title;
        copy.textContent = camera.distance_km
          ? `${camera.provider} camera about ${camera.distance_km} km from ${camera.city}.`
          : `${camera.provider} camera near ${camera.city}.`;
        link.href = camera.detail_url || camera.player_url;
        attribution.innerHTML = `${camera.attribution_text} <a href="${camera.attribution_url}" target="_blank" rel="noreferrer">Source</a>`;
      });
      selectorWrap.append(selectorLabel, selector);
    }

    frameWrap.appendChild(frame);
    meta.append(title);
    if (selectorWrap.childNodes.length) {
      meta.appendChild(selectorWrap);
    }
    meta.append(copy, link, attribution);
    shell.append(frameWrap, meta);
    refs.cameraPanel.appendChild(shell);
    return;
  }

  const fallback = document.createElement("div");
  const message = document.createElement("p");
  fallback.className = "camera-fallback";
  message.textContent =
    payload.message || "No live public camera found near this city right now.";
  fallback.appendChild(message);
  refs.cameraPanel.appendChild(fallback);
}

async function loadCityCamera(city) {
  renderCameraState({
    status: "loading",
    message: "Looking for a public live camera near this city.",
  });

  try {
    const payload = await fetchJson(`/city-camera?city=${encodeURIComponent(city)}`);
    renderCameraState(payload);
  } catch (_error) {
    renderCameraState({
      status: "unavailable",
      message: "No live public camera found near this city right now.",
    });
  }
}

async function loadCity(city) {
  setLoadingState(true, city);
  refs.hint.textContent = `Curating a fresh city brief for ${city}.`;

  try {
    const payload = await fetchJson(`/dashboard-data?city=${encodeURIComponent(city)}`);
    const weather = payload.current;
    const forecast = payload.forecast;

    updateCurrentWeather(weather);
    renderChart(forecast.hourly);
    renderHourlyRail(forecast.hourly);
    void loadCityCamera(forecast.city);
    refs.hint.textContent = `Showing ${forecast.city}, ${forecast.country}.`;
    setFeedback(
      `Forecast loaded for ${forecast.city}. Scroll the timeline to explore the next 24 hours.`,
      "",
    );
  } catch (error) {
    setFeedback(error.message, "error");
    refs.hint.textContent = "Try another city name or check the service again in a moment.";
    renderCameraState({
      status: "unavailable",
      message: "City camera will appear after the weather data loads successfully.",
    });
  } finally {
    setLoadingState(false, city);
  }
}

refs.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const city = refs.input.value.trim();
  if (!city) {
    setFeedback("Enter a city name to load its forecast.", "error");
    refs.input.focus();
    return;
  }

  loadCity(city);
});

loadCity(refs.body.dataset.defaultCity || "Tel Aviv");
