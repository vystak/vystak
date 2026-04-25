import json
from urllib.request import urlopen


def get_weather(city: str) -> str:
    """Get current weather for a city using wttr.in."""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        with urlopen(url) as response:
            data = json.loads(response.read())
            current = data["current_condition"][0]
            temp_c = current["temp_C"]
            desc = current["weatherDesc"][0]["value"]
            humidity = current["humidity"]
            wind = current["windspeedKmph"]
            return f"{city}: {desc}, {temp_c}°C, humidity {humidity}%, wind {wind} km/h"
    except Exception as e:
        return f"Could not get weather for {city}: {e}"
