from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from django.core.cache import cache

from routing.checkpoints import Checkpoint, Point

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
TIME_FORMAT = "%Y-%m-%dT%H:%M"
REQUEST_TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 2
CHUNK_SIZE = 25
MAX_PARALLEL_REQUESTS = 4
GRID_DEGREES = 0.1
FORECAST_HORIZON_DAYS = 15
ONE_HOUR = timedelta(hours=1)
WEATHER_CACHE_SECONDS = 30 * 60  # forecasts are updated about every hour


@dataclass(frozen=True)
class WeatherReading:
    windMph: float
    gustMph: float | None
    rainInHr: float
    snowInHr: float
    forecastHour: datetime


@dataclass(frozen=True)
class HourlySeries:
    times: list[datetime]
    wind: list[float | None]
    gust: list[float | None]
    rain: list[float | None]
    snow: list[float | None]


class WeatherError(RuntimeError):
    pass


def gridKey(point: Point) -> Point:
    lat = round(round(point[0] / GRID_DEGREES) * GRID_DEGREES, 4)
    lon = round(round(point[1] / GRID_DEGREES) * GRID_DEGREES, 4)
    return lat, lon


def floorHour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def ceilHour(moment: datetime) -> datetime:
    floor = floorHour(moment)
    return floor if floor == moment else floor + ONE_HOUR


def nearestHour(moment: datetime) -> datetime:
    floor = floorHour(moment)
    return floor + ONE_HOUR if moment - floor >= ONE_HOUR / 2 else floor


def readError(response: httpx.Response) -> WeatherError:
    try:
        reason = response.json().get("reason", "")
    except ValueError:
        reason = response.text[:200]
    return WeatherError(f"Open-Meteo error {response.status_code}: {reason}")


def parseSeries(location: dict) -> HourlySeries:
    hourly = location["hourly"]

    times = []
    for text in hourly["time"]:
        times.append(datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC))

    # rain and showers are both liquid rain, Open-Meteo just splits them by type
    rain = []
    for i in range(len(times)):
        rainValue, showersValue = hourly["rain"][i], hourly["showers"][i]
        if rainValue is None or showersValue is None:
            rain.append(None)
        else:
            rain.append(rainValue + showersValue)

    return HourlySeries(
        times=times,
        wind=list(hourly["wind_speed_10m"]),
        gust=list(hourly["wind_gusts_10m"]),
        rain=rain,
        snow=list(hourly["snowfall"]),
    )


def requestChunk(points: list[Point], startHour: datetime, endHour: datetime) -> list[HourlySeries]:
    lats, lons = [], []
    for lat, lon in points:
        lats.append(f"{lat:.4f}")
        lons.append(f"{lon:.4f}")

    params = {
        "latitude": ",".join(lats),
        "longitude": ",".join(lons),
        "hourly": HOURLY_FIELDS,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "GMT",
        "start_hour": startHour.strftime(TIME_FORMAT),
        "end_hour": endHour.strftime(TIME_FORMAT),
    }

    lastError = WeatherError("Open-Meteo request was not attempted")
    for _ in range(MAX_ATTEMPTS):
        try:
            response = httpx.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.TransportError as error:
            lastError = WeatherError(f"Open-Meteo request failed: {error!r}")
            continue

        if response.status_code >= 500:
            lastError = readError(response)
            continue
        if response.status_code != 200:
            raise readError(response)

        data = response.json()
        if isinstance(data, dict):
            data = [data]  # a single location comes back as an object, not a list
        if len(data) != len(points):
            raise WeatherError(f"Open-Meteo returned {len(data)} locations for {len(points)}")

        series = []
        for location in data:
            series.append(parseSeries(location))
        return series

    raise lastError


def fetchHourly(
    points: list[Point], startHour: datetime, endHour: datetime
) -> dict[Point, HourlySeries]:
    uniqueKeys = []
    seen = set()
    for point in points:
        key = gridKey(point)
        if key not in seen:
            seen.add(key)
            uniqueKeys.append(key)

    seriesByKey: dict[Point, HourlySeries] = {}
    missingKeys = []
    for key in uniqueKeys:
        series = cachedSeries(key, startHour, endHour)
        if series is None:
            missingKeys.append(key)
        else:
            seriesByKey[key] = series

    chunks = []
    for i in range(0, len(missingKeys), CHUNK_SIZE):
        chunks.append(missingKeys[i : i + CHUNK_SIZE])
    if not chunks:
        return seriesByKey

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
        futures = []
        for chunk in chunks:
            futures.append(pool.submit(requestChunk, chunk, startHour, endHour))

        for c in range(len(chunks)):
            results = futures[c].result()
            for i in range(len(chunks[c])):
                seriesByKey[chunks[c][i]] = results[i]
                storeSeries(chunks[c][i], results[i])

    return seriesByKey


def cellCacheKey(key: Point) -> str:
    return f"meteo:{key[0]}:{key[1]}"


def cachedSeries(key: Point, startHour: datetime, endHour: datetime) -> HourlySeries | None:
    hours = cache.get(cellCacheKey(key))
    if hours is None:
        return None

    times: list[datetime] = []
    wind: list[float | None] = []
    gust: list[float | None] = []
    rain: list[float | None] = []
    snow: list[float | None] = []
    hour = startHour
    while hour <= endHour:
        values = hours.get(hour.strftime(TIME_FORMAT))
        if values is None:
            return None  # any missing hour means the cell has to be fetched again
        times.append(hour)
        wind.append(values[0])
        gust.append(values[1])
        rain.append(values[2])
        snow.append(values[3])
        hour += ONE_HOUR

    return HourlySeries(times=times, wind=wind, gust=gust, rain=rain, snow=snow)


def storeSeries(key: Point, series: HourlySeries) -> None:
    hours = cache.get(cellCacheKey(key)) or {}
    for i in range(len(series.times)):
        hourText = series.times[i].strftime(TIME_FORMAT)
        hours[hourText] = (series.wind[i], series.gust[i], series.rain[i], series.snow[i])
    cache.set(cellCacheKey(key), hours, WEATHER_CACHE_SECONDS)


def hourIndex(series: HourlySeries, hour: datetime) -> int | None:
    if not series.times:
        return None
    index = int((hour - series.times[0]) / ONE_HOUR)
    if index < 0 or index >= len(series.times) or series.times[index] != hour:
        return None
    return index


def pickReading(series: HourlySeries, eta: datetime) -> WeatherReading | None:
    # wind is the value at the hour, rain and snow are totals for the hour before
    windHour = nearestHour(eta)
    precipHour = ceilHour(eta)

    windIndex = hourIndex(series, windHour)
    precipIndex = hourIndex(series, precipHour)
    if windIndex is None or precipIndex is None:
        return None

    wind = series.wind[windIndex]
    rain = series.rain[precipIndex]
    snow = series.snow[precipIndex]
    if wind is None or rain is None or snow is None:
        return None

    return WeatherReading(
        windMph=wind,
        gustMph=series.gust[windIndex],
        rainInHr=rain,
        snowInHr=snow,
        forecastHour=windHour,
    )


def weatherForCheckpoints(
    checkpoints: list[Checkpoint], now: datetime | None = None
) -> list[WeatherReading | None]:
    if not checkpoints:
        return []

    horizonEnd = floorHour(now or datetime.now(UTC)) + timedelta(days=FORECAST_HORIZON_DAYS)

    points = []
    etas = []
    for checkpoint in checkpoints:
        if checkpoint.eta <= horizonEnd:
            points.append((checkpoint.lat, checkpoint.lon))
            etas.append(checkpoint.eta)

    seriesByKey: dict[Point, HourlySeries] = {}
    if points:
        startHour = floorHour(min(etas))
        endHour = min(ceilHour(max(etas)), horizonEnd)
        seriesByKey = fetchHourly(points, startHour, endHour)

    readings: list[WeatherReading | None] = []
    for checkpoint in checkpoints:
        series = seriesByKey.get(gridKey((checkpoint.lat, checkpoint.lon)))
        if series is None:
            readings.append(None)
        else:
            readings.append(pickReading(series, checkpoint.eta))

    return readings
