# hotel_utils.py

import http.client
import json
import urllib.parse
from dotenv import load_dotenv
import os

load_dotenv()

def get_hotels_with_ratings(city, min_rating=3.5, radius=3000, max_results=5):
    """
    Get hotels from a given city using HotelDiscoveryAPI without using coordinates.
    
    Args:
        city (str): City name (e.g., "Delhi", "Paris")
        min_rating (float): Minimum hotel rating to filter
        radius (int): Radius in meters (default: 3000)
        max_results (int): Number of hotels to return

    Returns:
        List[dict]: Hotel info with name, address, rating, etc.
    """
    conn = http.client.HTTPSConnection("hoteldiscoveryapi.p.rapidapi.com")

    headers = {
        'x-rapidapi-key': os.getenv("X_rapidapi_key"),  # Replace with your actual key
        'x-rapidapi-host': os.getenv("X_rapidapi_host")
    }

    encoded_city = urllib.parse.quote(city)
    url = f"/api/hotels/search?city={encoded_city}&radius={radius}&rating={min_rating}"

    try:
        conn.request("GET", url, headers=headers)
        res = conn.getresponse()
        data = res.read()
        hotels_data = json.loads(data)

        hotels = []
        for hotel in hotels_data.get("data", []):
            try:
                name = hotel.get("name", "N/A")
                address = hotel.get("vicinity", "N/A")
                rating = float(hotel.get("rating", 0))
                total_ratings = hotel.get("user_ratings_total", 0)
                lat = hotel.get("geometry", {}).get("location", {}).get("lat", "")
                lng = hotel.get("geometry", {}).get("location", {}).get("lng", "")

                hotels.append({
                    "name": name,
                    "address": address,
                    "rating": rating,
                    "user_ratings_total": total_ratings,
                    "latitude": lat,
                    "longitude": lng
                })
            except Exception:
                continue

        # Sort and return top N
        return sorted(hotels, key=lambda x: x["rating"], reverse=True)[:max_results]

    except Exception as e:
        #print(f"[Hotel API Error]: {e}")
        return []
