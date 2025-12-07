import os
import requests
from typing import Optional, Dict, Any
from math import radians, sin, cos, atan2, sqrt
from dotenv import load_dotenv
from google.adk.agents import Agent

load_dotenv()

API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not API_KEY:
    raise RuntimeError("Set GOOGLE_MAPS_API_KEY in .env")

# -------------------------------
# UTILS
# -------------------------------

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))

def get_location_from_ip():
    try:
        # ipinfo often blocked; use ip-api.com (no key needed, 45 req/min)
        r = requests.get("http://ip-api.com/json/", timeout=8)
        data = r.json()
        if data["status"] == "success":
            return {
                "city": data.get("city", "Unknown"),
                "country": data.get("countryCode", ""),
                "lat": data["lat"],
                "lng": data["lon"]
            }
    except Exception as e:
        print("IP detection failed:", e)
    return None

def geocode_city(city: str):
    """Convert city name to lat/lng using Google Geocoding API"""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": city, "key": API_KEY}
    r = requests.get(url, params=params, timeout=10).json()
    if r.get("status") == "OK":
        loc = r["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]
    return None, None

# -------------------------------
# MAIN TOOL (FIXED SCHEMA)
# -------------------------------

def find_doctors(
    specialty: Optional[str] = None,
    city: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_km: int = 20
) -> Dict[str, Any]:
    """
    Find nearby doctors using Google Places API.

    Args:
        specialty: Type of doctor (cardiologist, dentist, neurologist)
        city: City name (Delhi, London, Bangalore)
        lat: Latitude
        lng: Longitude
        radius_km: Search radius in kilometers

    Returns:
        A list of nearby doctors with distance, rating and open status.
    """

    print("✅ find_doctors called with:", specialty, city, lat, lng, radius_km)

    # ✅ Resolve location properly
    if city and not (lat and lng):
        print(f"Geocoding city: {city}")
        lat, lng = geocode_city(city)
        print(f"→ Geocoding result: lat={lat}, lng={lng}")

    if not (lat and lng):
        print("Trying IP location detection...")
        ip = get_location_from_ip()
        if ip:
            lat, lng = ip["lat"], ip["lng"]
            detected_city = f"{ip['city']}, {ip['country']}"
            print(f"→ IP detected: {detected_city} ({lat}, {lng})")
        else:
            print("IP detection also failed!")
            return {"error": "Unable to detect your location. Please provide a city name."}
    else:
        detected_city = city or "your area"

    keyword = specialty.strip() if specialty else "doctor"

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": min(radius_km * 1000, 50000),
        "keyword": keyword,
        "key": API_KEY
    }

    # try:
    resp = requests.get(url, params=params, timeout=15).json()

    if resp.get("status") == "REQUEST_DENIED":
        return {"error": "Google Places API not enabled or billing inactive."}
    if resp.get("status") == "OVER_QUERY_LIMIT":
        return {"error": "API quota exceeded."}

    places = resp.get("results", [])[:12]
    
    print("✅ Places found:", len(places))

    if not places:
        return {"error": f"No doctors found within {radius_km} km of {detected_city}."}

    results = []
    for p in places:
        loc = p["geometry"]["location"]
        distance = round(haversine_km(lat, lng, loc["lat"], loc["lng"]), 1)

        results.append({
            "name": p.get("name", "Unknown"),
            "address": p.get("vicinity", "No address"),
            "rating": p.get("rating", "No rating"),
            "reviews": p.get("user_ratings_total", 0),
            "distance_km": distance,
            "open_now": p.get("opening_hours", {}).get("open_now")
        })

    lines = []
    for i, d in enumerate(results, 1):
        lines.append(
            f"{i}. {d['name']} • {d['rating']} {d['reviews']} • {d['distance_km']} • {d['open_now']}"
        )

    formatted = "\n".join(lines)

    return f"""
    Here are the top {specialty or 'doctors'} near {detected_city}:

    {formatted}

    Do you want directions, phone number, or another specialty?
    """

    # except Exception as e:
    #     print("❌ Error in find_doctors:", e)
    #     return "❌ Service error: message"

# -------------------------------
# AGENT (FIXED PROMPT)
# -------------------------------

root_agent = Agent(
    name="DoctorFinder",
    model="gemini-2.5-flash",
    description="Finds nearby doctors using Google Maps",
    instruction="""
You extract structured data and call the tool.

User intent mapping:
- "cardiologist near me" → specialty="cardiologist"
- "dentist in Bangalore" → specialty="dentist", city="Bangalore"
- "doctors within 5 km" → radius_km=5

Rules:
- Always extract specialty, city, and radius before calling.
- Never call with empty arguments.
- If city is missing, allow auto IP detection.
- Return results exactly as provided by the tool.
""",
    tools=[find_doctors],
)
