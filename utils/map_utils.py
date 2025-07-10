import streamlit as st
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from streamlit_folium import st_folium
import folium
import openrouteservice
from openrouteservice import convert

# Initialize services
geolocator = Nominatim(user_agent="triptales-app", timeout=10)

# ORS API Key
ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjlhNWJjMjFhNmExOTQzZjhiZjdhNDg2ZGI1NjIxNjNjIiwiaCI6Im11cm11cjY0In0="

ors_client = openrouteservice.Client(key=ORS_API_KEY)

@st.cache_data(show_spinner=False)
def geocode_place_within_radius(place_query, center_coords, max_km=50):
    try:
        loc = geolocator.geocode(place_query)
        if loc:
            distance_km = geodesic(center_coords, (loc.latitude, loc.longitude)).km
            if distance_km <= max_km:
                return loc
    except Exception as e:
        st.warning(f"⚠️ Failed to geocode '{place_query}': {e}")
    return None

@st.cache_data(show_spinner=False)
def parse_itinerary_by_day_with_geo(itinerary_text, destination, hotel_coords):
    days = itinerary_text.split("Day ")
    parsed = {}
    for chunk in days[1:]:
        try:
            day_num = chunk.split("\n", 1)[0].strip()
            content = chunk.split("\n", 1)[1].strip() if "\n" in chunk else chunk.strip()
            lines = [line for line in content.split("\n") if any(keyword in line.lower() for keyword in ["morning", "afternoon", "evening"])]

            locations = []
            for line in lines:
                place_name = line.split(":")[-1].split(",")[0].split("-")[0].strip()
                full_query = f"{place_name}, {destination}"
                loc = geocode_place_within_radius(full_query, hotel_coords, max_km=50)
                if loc:
                    locations.append({
                        "name": place_name,
                        "coords": (loc.latitude, loc.longitude),
                        "original": line,
                        "time_of_day": "morning" if "morning" in line.lower() else 
                                      "afternoon" if "afternoon" in line.lower() else 
                                      "evening"
                    })
            parsed[f"Day {day_num}"] = locations
        except Exception as e:
            st.warning(f"⚠️ Failed to parse Day {day_num}: {e}")
    return parsed

def get_ors_route(start, end, profile="driving-car"):
    try:
        coords = ((start[1], start[0]), (end[1], end[0]))
        route = ors_client.directions(coords, profile=profile)
        geometry = route['routes'][0]['geometry']
        decoded = convert.decode_polyline(geometry)
        line_coords = [(pt[1], pt[0]) for pt in decoded['coordinates']]
        summary = route['routes'][0]['summary']
        return line_coords, round(summary['duration'] / 60, 1), round(summary['distance'] / 1000, 2)
    except Exception as e:
        #print(f"[ORS ERROR] {e}")
        return None, None, None

def generate_full_day_route_map(selected_hotel, day_places, travel_mode, show_return=True, map_height=700, route_color='blue'):
    if not day_places:
        st.warning("No places to display for this time period")
        return
    
    center_coords = (selected_hotel['latitude'], selected_hotel['longitude'])
    m = folium.Map(location=center_coords, zoom_start=13, control_scale=True)

    # Add hotel marker
    folium.Marker(
        location=center_coords,
        popup="Your Hotel",
        icon=folium.Icon(color='green', icon='home')
    ).add_to(m)

    coords_list = [center_coords]
    
    # Add activity markers with time-specific icons
    for loc in day_places:
        coords = loc.get("coords")
        name = loc.get("name")
        time_of_day = loc.get("time_of_day", "")
        
        if coords:
            coords_list.append(coords)
            icon_color = {
                "morning": "blue",
                "afternoon": "orange",
                "evening": "purple"
            }.get(time_of_day, "red")
            
            folium.Marker(
                location=coords,
                popup=f"{time_of_day.capitalize()}: {name}",
                icon=folium.Icon(color=icon_color, icon="info-sign")
            ).add_to(m)

    if show_return:
        coords_list.append(center_coords)

    # Add routes with time-specific colors
    for i in range(len(coords_list) - 1):
        start, end = coords_list[i], coords_list[i + 1]
        route, duration, distance = get_ors_route(start, end, profile=travel_mode)
        if route:
            folium.PolyLine(
                route,
                color=route_color,
                weight=4,
                opacity=0.7,
                tooltip=f"{distance} km, {duration} min"
            ).add_to(m)

    # Ensure map bounds include all markers
    if len(coords_list) > 1:
        m.fit_bounds([coords_list[0], coords_list[-1]])
    
    # Display the map
    st_folium(m, width=1400, height=map_height, returned_objects=[])