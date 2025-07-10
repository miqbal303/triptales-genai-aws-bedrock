import requests
import datetime
import time
import streamlit as st


weathercode_map = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail"
}



def fetch_weather_forecast(destination, start_date, num_days=3):
    """Fetch hourly weather and structure into morning/afternoon/evening blocks."""
    try:
        geo_url = "https://nominatim.openstreetmap.org/search"
        geo_params = {"q": destination, "format": "json", "limit": 1}
        geo_res = requests.get(geo_url, params=geo_params, headers={"User-Agent": "TripTales/1.0"}, timeout=10)
        geo_res.raise_for_status()
        geo_data = geo_res.json()
        if not geo_data:
            st.warning("⚠️ Location not found for weather data.")
            return {}
    except Exception as e:
        st.warning(f"⚠️ Weather location lookup failed: {e}")
        return {}

    lat, lon = geo_data[0]['lat'], geo_data[0]['lon']

    try:
        forecast_url = "https://api.open-meteo.com/v1/forecast"
        end_date = (datetime.datetime.strptime(start_date, "%Y-%m-%d") + datetime.timedelta(days=num_days - 1)).strftime("%Y-%m-%d")
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": "temperature_2m,weathercode",
            "timezone": "auto",
            "start_date": start_date,
            "end_date": end_date
        }
        weather_res = requests.get(forecast_url, params=params, timeout=10)
        weather_res.raise_for_status()
        weather_data = weather_res.json()

        hourly_temps = weather_data["hourly"]["temperature_2m"]
        hourly_codes = weather_data["hourly"]["weathercode"]
        hourly_times = weather_data["hourly"]["time"]

        # Structure into time slots
        weather_by_day = {}
        for i, timestamp in enumerate(hourly_times):
            dt = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M")
            day_index = (dt.date() - datetime.datetime.strptime(start_date, "%Y-%m-%d").date()).days + 1
            if not (1 <= day_index <= num_days):
                continue

            hour = dt.hour
            if 6 <= hour < 12:
                slot = "morning"
            elif 12 <= hour < 17:
                slot = "afternoon"
            elif 17 <= hour < 22:
                slot = "evening"
            else:
                continue  # skip night times

            day_str = str(day_index)
            if day_str not in weather_by_day:
                weather_by_day[day_str] = {}

            if slot not in weather_by_day[day_str]:
                weather_by_day[day_str][slot] = {
                    "weather": weathercode_map.get(hourly_codes[i], "Unknown"),
                    "temp": hourly_temps[i]
                }

        return weather_by_day

    except Exception as e:
        st.warning(f"⚠️ Weather API failed: {e}")
        return {}


## Test block to run independently
#if __name__ == "__main__":
#    forecast = fetch_weather_forecast("Mumbai", "2025-07-04", num_days=2)
#    print("Hourly Forecast:")
#    for day, blocks in forecast.items():
#        print(f"Day {day}:")
#        for slot, info in blocks.items():
#            print(f"  {slot.title()}: {info['weather']} ({info['temp']}°C)")
