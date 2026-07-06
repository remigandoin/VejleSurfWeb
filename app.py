# windbird_plot.py
import streamlit as st
import requests
import matplotlib.pyplot as plt
from datetime import datetime

STATION_ID = 1362

WIND_COLOR = "tab:blue"
GUST_COLOR = "tab:red"
TEMP_COLOR = "tab:orange"
ECMWF_COLOR = "tab:green"
ICON_COLOR = "tab:purple"
DMI_COLOR = "tab:brown"

def parse_time(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))

def get_station():
    url = f"https://api.openwindmap.org/v1/live-with-meta/{STATION_ID}"
    d = requests.get(url, timeout=20).json()["data"]
    return d["location"]["latitude"], d["location"]["longitude"], d["meta"]["name"]

def get_measurements():
    url = f"https://api.openwindmap.org/v1/archive/{STATION_ID}?start=last-day&stop=now"
    j = requests.get(url, timeout=30).json()

    legend = j["legend"]
    rows = j["data"]

    i_time = legend.index("time")
    i_avg = legend.index("wind_speed_avg")
    i_max = legend.index("wind_speed_max")

    return (
        [parse_time(row[i_time]) for row in rows],
        [row[i_avg] for row in rows],
        [row[i_max] for row in rows],
    )

def get_forecast(lat, lon, model_name, model_code):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m",
        "wind_speed_unit": "kmh",
        "forecast_days": 3,
        "timezone": "auto",
        "models": model_code,
    }

    j = requests.get(url, params=params, timeout=20).json()

    if "error" in j:
        print(model_name, j)
        return None

    h = j.get("hourly", {})
    if not h.get("time") or not h.get("wind_speed_10m"):
        print(model_name, "missing hourly wind data", j)
        return None

    return {
        "name": model_name,
        "time": [parse_time(t) for t in h["time"]],
        "temp": h.get("temperature_2m"),
        "wind": h.get("wind_speed_10m"),
        "gusts": h.get("wind_gusts_10m"),
        "first_hour": h["time"][0],
    }

lat, lon, name = get_station()
obs_time, obs_wind_avg, obs_wind_max = get_measurements()

ecmwf = get_forecast(lat, lon, "ECMWF", "ecmwf_ifs025")
icon = get_forecast(lat, lon, "ICON", "icon_seamless")
dmi = get_forecast(lat, lon, "DMI", "dmi_harmonie_arome_europe")

st.set_page_config(layout="wide")
st.title("Vejle Surf Forecast")

fig, ax1 = plt.subplots(figsize=(12, 6))

ax1.plot(obs_time, obs_wind_avg, color=WIND_COLOR, linewidth=2, label="Measured mean wind")
ax1.plot(obs_time, obs_wind_max, color=GUST_COLOR, linewidth=2, label="Measured gusts")

if ecmwf:
    ax1.plot(ecmwf["time"], ecmwf["wind"], color=ECMWF_COLOR, linestyle="--", linewidth=2, label="ECMWF mean wind")
    ax1.plot(ecmwf["time"], ecmwf["gusts"], color=ECMWF_COLOR, linestyle=":", linewidth=2, label="ECMWF gusts")

if icon:
    ax1.plot(icon["time"], icon["wind"], color=ICON_COLOR, linestyle="--", linewidth=2, label="ICON mean wind")
    ax1.plot(icon["time"], icon["gusts"], color=ICON_COLOR, linestyle=":", linewidth=2, label="ICON gusts")

if dmi:
    ax1.plot(dmi["time"], dmi["wind"], color=DMI_COLOR, linestyle="--", linewidth=2, label="DMI mean wind")
    ax1.plot(dmi["time"], dmi["gusts"], color=DMI_COLOR, linestyle=":", linewidth=2, label="DMI gusts")

ax1.set_ylabel("Wind speed / gusts (km/h)")
ax1.grid(True)

ax2 = ax1.twinx()

# if ecmwf and ecmwf["temp"]:
#     ax2.plot(ecmwf["time"], ecmwf["temp"], color=TEMP_COLOR, linestyle="-.", linewidth=2, label="ECMWF temperature")

# ax2.set_ylabel("Temperature (°C)")


lines = ax1.get_lines() + ax2.get_lines()
labels = [l.get_label() for l in lines]

fig.legend(
    lines,
    labels,
    loc="upper center",
    bbox_to_anchor=(0.4, 0.85),
    ncol=4,
    frameon=False,
    fontsize=9,
)

available = []
if ecmwf:
    available.append(f"ECMWF first hour: {ecmwf['first_hour']}")
if icon:
    available.append(f"ICON first hour: {icon['first_hour']}")
if dmi:
    available.append(f"DMI first hour: {dmi['first_hour']}")


fig.suptitle(
    f"{name} / Windbird {STATION_ID}: measurements + ECMWF/ICON/DMI forecasts\n"
    + " | ".join(available),
    fontsize=12,
    y=0.98,
)

plt.tight_layout(rect=[0, 0, 1, 0.86])
st.pyplot(fig)