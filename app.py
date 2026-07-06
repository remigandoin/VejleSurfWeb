import math
import requests
import streamlit as st
import zoneinfo

from zoneinfo import ZoneInfo
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta, timezone

LOCAL_TZ = ZoneInfo("Europe/Copenhagen")

st.set_page_config(page_title="Windbird Forecast", layout="wide")
st_autorefresh(interval=15 * 60 * 1000, key="auto_refresh")

MODELS = [
    ("ECMWF", "ecmwf_ifs025", "#2ca02c"),
    ("ICON", "icon_seamless", "#9467bd"),
    ("DMI", "dmi_harmonie_arome_europe", "#8c564b"),
]

COMMON_WINDBIRDS = {
    "Vejle / Windbird 1362": 1362,
    "Custom Windbird ID": None,
}


def parse_time(t):
    return (
        datetime.fromisoformat(t.replace("Z", "+00:00"))
        .astimezone(LOCAL_TZ)
    )


def direction_text(deg):
    if deg is None:
        return "N/A"
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(deg / 45) % 8]


def latest_valid(values):
    if not values:
        return None
    for v in reversed(values):
        if v is not None:
            return v
    return None


def km_distance(lat1, lon1, lat2, lon2):
    r = 6371
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dmi_get(url, params=None):
    r = requests.get(url, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=300)
def get_station(station_id):
    url = f"https://api.openwindmap.org/v1/live-with-meta/{station_id}"
    j = requests.get(url, timeout=20).json()
    d = j["data"]

    return {
        "id": station_id,
        "name": d["meta"].get("name", f"Windbird {station_id}"),
        "lat": d["location"]["latitude"],
        "lon": d["location"]["longitude"],
    }


@st.cache_data(ttl=300)
def get_measurements(station_id):
    url = f"https://api.openwindmap.org/v1/archive/{station_id}?start=last-day&stop=now"
    j = requests.get(url, timeout=30).json()

    legend = j["legend"]
    rows = j["data"]

    i_time = legend.index("time")
    i_avg = legend.index("wind_speed_avg")
    i_max = legend.index("wind_speed_max")

    i_dir = None
    for name in ["wind_heading", "wind_direction", "wind_direction_avg", "wind_dir", "direction"]:
        if name in legend:
            i_dir = legend.index(name)
            break

    return {
        "time": [parse_time(r[i_time]) for r in rows],
        "wind": [r[i_avg] for r in rows],
        "gusts": [r[i_max] for r in rows],
        "direction": [r[i_dir] for r in rows] if i_dir is not None else None,
    }


@st.cache_data(ttl=300)
def get_forecast(lat, lon, model_name, model_code):
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "wind_speed_unit": "kmh",
        "forecast_hours": 72,
        "timezone": "auto",
        "models": model_code,
    }

    j = requests.get(url, params=params, timeout=30).json()

    if "error" in j:
        return None

    h = j.get("hourly", {})

    if not h.get("time"):
        return None

    return {
        "name": model_name,
        "time": [parse_time(t) for t in h["time"]],
        "wind": h.get("wind_speed_10m"),
        "gusts": h.get("wind_gusts_10m"),
        "direction": h.get("wind_direction_10m"),
        "temp": h.get("temperature_2m"),
        "first_hour": h["time"][0],
    }


def extract_station_type(props):
    for key in ["stationType", "station_type", "type", "stationClass", "stationOwner"]:
        value = props.get(key)
        if value:
            return str(value).strip().upper()
    return ""


@st.cache_data(ttl=3600)
def get_dmi_stations(collection, allowed_types=None):
    url = f"https://opendataapi.dmi.dk/v2/{collection}/collections/station/items"
    j = dmi_get(url, {"limit": 10000})

    stations = []

    for f in j.get("features", []):
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates")

        if not coords:
            continue

        station_type = extract_station_type(props)

        if allowed_types:
            if station_type not in allowed_types:
                continue

        stations.append({
            "id": props.get("stationId"),
            "name": props.get("name") or props.get("stationName") or props.get("stationId"),
            "lon": coords[0],
            "lat": coords[1],
            "type": station_type or "UNKNOWN",
        })

    return stations


@st.cache_data(ttl=300)
def get_dmi_observations(collection, station_id, parameter_id, hours=48):
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)

    start_s = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = (
        f"https://opendataapi.dmi.dk/v2/{collection}/collections/observation/items"
        f"?stationId={station_id}"
        f"&parameterId={parameter_id}"
        f"&datetime={start_s}/{end_s}"
        f"&limit=20000"
        f"&sortorder=observed,DESC"
    )

    print("DMI URL:", url)

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    j = r.json()

    times = []
    values = []

    for f in j.get("features", []):
        p = f.get("properties", {})

        if p.get("value") is None or not p.get("observed"):
            continue

        times.append(parse_time(p["observed"]))
        values.append(p["value"])

    # DESC gives newest first; reverse for plotting left-to-right
    times.reverse()
    values.reverse()

    return times, values


@st.cache_data(ttl=300)
def nearest_dmi_series(lat, lon, collection, parameter_id, hours=48, allowed_types=None):
    stations = get_dmi_stations(collection, allowed_types)

    stations = sorted(
        stations,
        key=lambda s: km_distance(lat, lon, s["lat"], s["lon"])
    )

    for s in stations[:50]:
        try:
            times, values = get_dmi_observations(collection, s["id"], parameter_id, hours)
            if values:
                s["distance_km"] = km_distance(lat, lon, s["lat"], s["lon"])
                return s, times, values
        except Exception:
            continue

    return None, [], []


def add_direction_arrows(fig, times, dirs, row_name, color, name, step):
    if not dirs:
        return

    x = []
    y = []
    angles = []
    hover = []

    for t, d in zip(times[::step], dirs[::step]):
        if d is None:
            continue

        x.append(t)
        y.append(row_name)
        angles.append(d)
        hover.append(f"{name}<br>{t}<br>{d:.0f}° / {direction_text(d)}")

    if not x:
        return

    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker=dict(
                symbol="arrow",
                size=20,
                color=color,
                angle=angles,
                line=dict(width=1, color=color),
            ),
            name=name,
            text=hover,
            hovertemplate="%{text}<extra></extra>",
        ),
        row=2,
        col=1,
    )


def make_wind_figure(obs, forecasts):
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.08,
        subplot_titles=("Wind speed and gusts", "Wind direction"),
    )

    fig.add_trace(go.Scatter(
        x=obs["time"],
        y=obs["wind"],
        name="Measured mean wind",
        line=dict(color="#1f77b4", width=2),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=obs["time"],
        y=obs["gusts"],
        name="Measured gusts",
        line=dict(color="#d62728", width=2),
    ), row=1, col=1)

    for fc, (_, _, color) in zip(forecasts, MODELS):
        if not fc:
            continue

        fig.add_trace(go.Scatter(
            x=fc["time"],
            y=fc["wind"],
            name=f"{fc['name']} mean wind",
            line=dict(color=color, width=2, dash="dash"),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=fc["time"],
            y=fc["gusts"],
            name=f"{fc['name']} gusts",
            line=dict(color=color, width=2, dash="dot"),
        ), row=1, col=1)

    if obs["direction"]:
        add_direction_arrows(fig, obs["time"], obs["direction"], "Measured", "black", "Measured direction", 6)

    for fc, (_, _, color) in zip(forecasts, MODELS):
        if fc and fc["direction"]:
            add_direction_arrows(fig, fc["time"], fc["direction"], fc["name"], color, f"{fc['name']} direction", 3)

    fig.update_yaxes(title_text="Wind / gusts (km/h)", row=1, col=1)

    fig.update_yaxes(
        title_text="Direction",
        categoryorder="array",
        categoryarray=["DMI", "ICON", "ECMWF", "Measured"],
        row=2,
        col=1,
    )

    fig.update_layout(
        height=720,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            y=1.14,
            x=0.5,
            xanchor="center",
        ),
        margin=dict(l=20, r=20, t=90, b=20),
    )

    return fig


def make_temperature_figure(forecasts, air_station, air_time, air_temp, sea_station, sea_time, sea_temp):
    fig = go.Figure()

    for fc, (_, _, color) in zip(forecasts, MODELS):
        if not fc or not fc["temp"]:
            continue

        fig.add_trace(go.Scatter(
            x=fc["time"],
            y=fc["temp"],
            name=f"{fc['name']} forecast air temp",
            line=dict(color=color, width=2, dash="dash"),
        ))

    if air_station and air_temp:
        fig.add_trace(go.Scatter(
            x=air_time,
            y=air_temp,
            name=f"Measured air temp - {air_station['name']} [{air_station.get('type', 'UNKNOWN')}]",
            line=dict(color="#ff7f0e", width=3),
        ))

    if sea_station and sea_temp:
        fig.add_trace(go.Scatter(
            x=sea_time,
            y=sea_temp,
            name=f"Measured sea temp - {sea_station['name']}",
            line=dict(color="#17becf", width=3),
        ))

    fig.update_layout(
        title="Air and sea temperature",
        height=440,
        hovermode="x unified",
        yaxis_title="Temperature (°C)",
        legend=dict(
            orientation="h",
            y=1.18,
            x=0.5,
            xanchor="center",
        ),
        margin=dict(l=20, r=20, t=80, b=20),
    )

    return fig


st.title("🏄 Windbird Forecast")

col_a, col_b, col_c = st.columns([2, 2, 1])

with col_a:
    chosen = st.selectbox("Station shortcut", list(COMMON_WINDBIRDS.keys()))

with col_b:
    default_id = COMMON_WINDBIRDS[chosen] or 1362
    station_id = st.number_input(
        "Windbird ID",
        min_value=1,
        max_value=999999,
        value=int(default_id),
        step=1,
    )

with col_c:
    st.write("")
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Loading latest data..."):
    station = get_station(int(station_id))
    obs = get_measurements(int(station_id))

    forecasts = [
        get_forecast(station["lat"], station["lon"], name, code)
        for name, code, color in MODELS
    ]

    air_station, air_time, air_temp = nearest_dmi_series(
        station["lat"],
        station["lon"],
        "metObs",
        "temp_dry",
        48,
        allowed_types={"SYNOP", "GIWS"},
    )

    sea_station, sea_time, sea_temp = nearest_dmi_series(
        station["lat"],
        station["lon"],
        "oceanObs",
        "tw",
        48,
        allowed_types=None,
    )

wind_now = latest_valid(obs["wind"])
gust_now = latest_valid(obs["gusts"])
dir_now = latest_valid(obs["direction"]) if obs["direction"] else None
air_now = latest_valid(air_temp)
sea_now = latest_valid(sea_temp)

st.subheader(f"{station['name']} / Windbird {station['id']}")

m1, m2, m3, m4, m5 = st.columns(5)

m1.metric("Mean wind", f"{wind_now:.0f} km/h" if wind_now is not None else "N/A")
m2.metric("Gusts", f"{gust_now:.0f} km/h" if gust_now is not None else "N/A")
m3.metric(
    "Direction",
    direction_text(dir_now) if dir_now is not None else "N/A",
    f"{dir_now:.0f}°" if dir_now is not None else None,
)
m4.metric("Air temp", f"{air_now:.1f} °C" if air_now is not None else "N/A")
m5.metric("Sea temp", f"{sea_now:.1f} °C" if sea_now is not None else "N/A")

forecast_labels = [f"{fc['name']}: {fc['first_hour']}" for fc in forecasts if fc]
st.caption("Forecast first hours: " + " | ".join(forecast_labels))

st.plotly_chart(make_wind_figure(obs, forecasts), use_container_width=True)

st.plotly_chart(
    make_temperature_figure(
        forecasts,
        air_station,
        air_time,
        air_temp,
        sea_station,
        sea_time,
        sea_temp,
    ),
    use_container_width=True,
)

if air_station:
    st.caption(
        f"Nearest DMI air temperature station: {air_station['name']} "
        f"[{air_station.get('type', 'UNKNOWN')}] "
        f"({air_station['distance_km']:.1f} km)"
    )
else:
    st.caption("No nearby DMI SYNOP/GIWS air temperature station found.")

if sea_station:
    st.caption(
        f"Nearest DMI sea temperature station: {sea_station['name']} "
        f"({sea_station['distance_km']:.1f} km)"
    )
else:
    st.caption("No nearby DMI sea temperature station found.")

st.caption("Auto-refreshes every 15 minutes.")