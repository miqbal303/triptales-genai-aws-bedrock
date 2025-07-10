import streamlit as st
from datetime import date, timedelta
from utils.genai_utils import generate_itinerary, generate_addons, generate_image, generate_image_variants, edit_image_with_prompt, transform_image_style
from utils.hotel_utils import get_hotels_with_ratings
from utils.map_utils import generate_full_day_route_map, parse_itinerary_by_day_with_geo
from utils.weather_utils import fetch_weather_forecast
from utils.db_utils import make_query_hash, get_cached_trip, cache_trip
from utils.pdf_export import export_to_pdf
import tempfile
import os
import base64
import time
import re
from PIL import Image
import io

st.set_page_config(page_title="TripTales AI Planner", layout="wide")
st.title("🧳 TripTales: AI Travel Planner")

# Constants
IMAGE_GENERATION_DELAY = 3  # seconds between image generation calls
MAX_IMAGE_RETRIES = 3
IMAGE_STYLES = {
    "Photorealistic": "professional photography, ultra-realistic, 8K resolution",
    "Watercolor": "watercolor painting, soft edges, pastel tones",
    "Anime": "Studio Ghibli-style, vibrant colors, whimsical",
    "Vintage": "1950s travel poster, muted colors, retro typography",
    "Pencil Sketch": "detailed pencil sketch with shading",
    "Cyberpunk": "neon lights, futuristic, cyberpunk 2077 style"
}

def calculate_rooms_required(adults, children, infants):
    """Calculate rooms needed based on common hotel rules:
    - Max 2 adults per room
    - Up to 2 children can share with adults per room
    - Max 4 total occupants per room (excluding infants)
    - Max 2 infants per room (infants don't count towards occupancy)
    """
    rooms = 0

    # Allocate adults: max 2 per room
    full_adult_rooms = adults // 2
    remaining_adults = adults % 2
    rooms += full_adult_rooms

    # If 1 adult remains, assign a room and try to add up to 2 children
    if remaining_adults:
        rooms += 1
        children = max(0, children - 2)

    # Allocate remaining children: 2 per room
    child_only_rooms = (children + 1) // 2  # ceil(children / 2)
    rooms += child_only_rooms

    # Infants: max 2 per room (not counted in occupancy)
    max_infants_allowed = rooms * 2
    if infants > max_infants_allowed:
        extra_infant_rooms = (infants - max_infants_allowed + 1) // 2  # ceil
        rooms += extra_infant_rooms

    return rooms




# Initialize session state
if 'adults' not in st.session_state:
    st.session_state.adults = 2
if 'children' not in st.session_state:
    st.session_state.children = 0
if 'infants' not in st.session_state:
    st.session_state.infants = 0
if 'rooms_required' not in st.session_state:
    st.session_state.rooms_required = 1
if 'itinerary_text' not in st.session_state:
    st.session_state.itinerary_text = ""
if 'packing_list' not in st.session_state:
    st.session_state.packing_list = {}
if 'visa_info' not in st.session_state:
    st.session_state.visa_info = ""
if 'food_list' not in st.session_state:
    st.session_state.food_list = ""
if 'hotels' not in st.session_state:
    st.session_state.hotels = []
if 'geo_parsed_itinerary' not in st.session_state:
    st.session_state.geo_parsed_itinerary = {}
if 'weather_forecast' not in st.session_state:
    st.session_state.weather_forecast = {}
if 'food_images' not in st.session_state:
    st.session_state.food_images = {}
if 'location_images' not in st.session_state:
    st.session_state.location_images = {}
if 'last_image_gen_time' not in st.session_state:
    st.session_state.last_image_gen_time = 0
if 'selected_image_style' not in st.session_state:
    st.session_state.selected_image_style = "Photorealistic"
if 'image_variants' not in st.session_state:
    st.session_state.image_variants = {}
if 'edited_images' not in st.session_state:
    st.session_state.edited_images = {}

# Sidebar Inputs
with st.sidebar:
    st.header("👨‍👩‍👧‍👦 Travelers")
    st.session_state.adults = st.number_input("Adults (13+ years)", min_value=1, max_value=10, value=st.session_state.adults)
    st.session_state.children = st.number_input("Children (2-12 years)", min_value=0, max_value=10, value=st.session_state.children)
    st.session_state.infants = st.number_input("Infants (0-2 years)", min_value=0, max_value=5, value=st.session_state.infants)
    st.session_state.rooms_required = calculate_rooms_required(
        st.session_state.adults, 
        st.session_state.children, 
        st.session_state.infants
    )
    st.markdown(f"**Rooms Required:** {st.session_state.rooms_required}")
    
    st.header("✈️ Trip Details")
    destination = st.text_input("📍 Destination", "")
    days = st.slider("📅 Trip Duration (Days)", 1, 14, 3)
    budget = st.number_input("💰 Budget (USD)", min_value=100, max_value=10000, value=1000)
    start_date = st.date_input("🗓️ Trip Start Date", min_value=date.today())
    interests = st.multiselect("🎯 Interests", 
                             ["Culture", "Food", "Nature", "Shopping", "Adventure", "History", "Relaxation"])
    
    st.header("🎨 Image Generation")
    st.session_state.selected_image_style = st.selectbox(
        "Image Style",
        list(IMAGE_STYLES.keys()),
        index=list(IMAGE_STYLES.keys()).index(st.session_state.selected_image_style))
    
    st.header("🏨 Accommodation Preferences")
    min_rating = st.slider("⭐ Minimum Hotel Rating", 1.0, 5.0, 4.0, 0.1)
    search_radius_km = st.slider("📍 Search Radius from Center (km)", 1, 50, 5)

# Helper Functions
def sanitize_key(key):
    """Create safe keys for session state storage"""
    return re.sub(r'[^a-zA-Z0-9]', '_', str(key))[:100]

def validate_image_data(img_data):
    """Ensure image data is properly formatted for display"""
    if not img_data:
        return None
    
    # If it's already a data URL, return as-is
    if isinstance(img_data, str) and img_data.startswith('data:image'):
        return img_data
    
    # If it's bytes, convert to base64 data URL
    if isinstance(img_data, bytes):
        try:
            return f"data:image/png;base64,{base64.b64encode(img_data).decode('utf-8')}"
        except:
            return None
    
    # If it's base64 string without prefix, add the prefix
    if isinstance(img_data, str):
        try:
            # Validate it's proper base64
            base64.b64decode(img_data)
            return f"data:image/png;base64,{img_data}"
        except:
            return None
    
    return None

def display_image_with_editor(image_data, key_suffix, context="activity"):
    """Display a single image with edit options"""
    if not image_data:
        return None
    
    # Create a container for the editor
    with st.container():
        img_col, edit_col = st.columns([3, 1])
        
        with img_col:
            try:
                # Display the current image (edited or original)
                current_img = validate_image_data(
                    st.session_state.edited_images.get(key_suffix, image_data)
                )
                if current_img:
                    st.image(current_img, use_container_width=True)
            except Exception as e:
                st.warning(f"Couldn't display image: {str(e)}")
                return None
        
        with edit_col:
            st.markdown("### 🖌️ Edit Options")
            edit_option = st.radio(
                f"Edit {context}:",
                ["None", "Enhance", "Custom Prompt"],
                key=f"edit_type_{key_suffix}"
            )
            
            if edit_option == "Enhance":
                enhancement = st.select_slider(
                    "Brightness:",
                    options=["Darker", "Original", "Brighter"],
                    value="Original",
                    key=f"enhance_{key_suffix}"
                )
                
                if st.button("Apply", key=f"apply_enhance_{key_suffix}"):
                    with st.spinner("Applying enhancement..."):
                        try:
                            # Convert to PIL Image
                            img_bytes = base64.b64decode(
                                image_data.split(",")[-1] if "," in image_data else image_data
                            )
                            img = Image.open(io.BytesIO(img_bytes))
                            
                            # Apply enhancement
                            from PIL import ImageEnhance
                            enhancer = ImageEnhance.Brightness(img)
                            factor = 0.7 if enhancement == "Darker" else 1.3
                            enhanced_img = enhancer.enhance(factor)
                            
                            # Convert back to bytes
                            buffered = io.BytesIO()
                            enhanced_img.save(buffered, format="PNG")
                            edited_img = buffered.getvalue()
                            
                            # Store as base64 string
                            st.session_state.edited_images[key_suffix] = (
                                f"data:image/png;base64,{base64.b64encode(edited_img).decode('utf-8')}"
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"Enhancement failed: {e}")
            
            elif edit_option == "Custom Prompt":
                edit_prompt = st.text_input(
                    "Describe changes:",
                    placeholder="e.g., 'add more trees', 'make it sunset'",
                    key=f"prompt_{key_suffix}"
                )
                
                if st.button("Apply Edit", key=f"apply_prompt_{key_suffix}") and edit_prompt:
                    with st.spinner("Applying your edits..."):
                        try:
                            # Ensure we have bytes for the API call
                            img_bytes = base64.b64decode(
                                image_data.split(",")[-1] if "," in image_data else image_data
                            )
                            edited_img = edit_image_with_prompt(img_bytes, edit_prompt)
                            if edited_img:
                                # Store as base64 string
                                st.session_state.edited_images[key_suffix] = (
                                    f"data:image/png;base64,{base64.b64encode(edited_img).decode('utf-8')}"
                                    if not isinstance(edited_img, str)
                                    else edited_img
                                )
                                st.rerun()
                        except Exception as e:
                            st.error(f"Edit failed: {e}")
    
    # Return the current image (edited or original)
    return st.session_state.edited_images.get(key_suffix, image_data)




def extract_activity_prompts_from_text(day_text, destination):
    """Extract activity prompts from itinerary text for image generation."""
    prompts = []
    lines = day_text.strip().split("\n")
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines or headers
        if not line or line.startswith("##") or line.lower().startswith("day "):
            continue
        
        if line.startswith("-"):
            try:
                # Remove leading dash and extra whitespace
                content = line.lstrip("-").strip()
                
                # Split on first colon only
                if ":" in content:
                    activity, description = content.split(":", 1)
                    activity = activity.strip()
                    description = description.strip().split(".")[0]  # only first sentence
                else:
                    activity = content
                    description = ""

                # Clean up activity name
                activity = re.sub(r"\[.*?\]|\d+\.\s*", "", activity).strip()

                # Build prompt
                prompt = (
                    f"{activity} in {destination}, {description.lower()} "
                    f"{IMAGE_STYLES[st.session_state.selected_image_style]}"
                )
                prompts.append((line, prompt))
            except Exception as e:
                #print(f"[Prompt Skipped] {line} → {e}")
                pass
                
    return prompts


def generate_location_images(destination, itinerary_text, days):
    """Generate images for activities in the itinerary."""
    location_images = {}
    
    for day_num in range(1, days + 1):
        day_key = f"Day {day_num}"
        pattern = rf"## {day_key}\n(.*?)(?=\n## Day {day_num + 1}|$)"
        match = re.search(pattern, itinerary_text, re.DOTALL)
        if not match:
            continue

        day_text = match.group(1).strip()
        location_images[day_key] = {}
        prompts = extract_activity_prompts_from_text(day_text, destination)

        for activity_line, prompt in prompts[:3]:  # Limit to 3 images per day
            current_time = time.time()
            time_since_last = current_time - st.session_state.last_image_gen_time
            if time_since_last < IMAGE_GENERATION_DELAY:
                time.sleep(IMAGE_GENERATION_DELAY - time_since_last)
            
            image_data = None
            for retry in range(MAX_IMAGE_RETRIES):
                try:
                    variants = generate_image_variants(prompt, num_variants=3)
                    if variants:
                        # Store variants with proper validation
                        st.session_state.image_variants[activity_line] = [
                            validate_image_data(v) for v in variants
                        ]
                        image_data = validate_image_data(variants[0])
                        if image_data:
                            location_images[day_key][activity_line] = image_data
                            break
                except Exception as e:
                    if retry == MAX_IMAGE_RETRIES - 1:
                        st.warning(f"Failed to generate image for: {activity_line} - {str(e)}")
                    time.sleep(1)
            
            st.session_state.last_image_gen_time = time.time()
                
    return location_images

def clean_itinerary_text(text):
    """Remove cost summary from the end of the itinerary text."""
    text = re.sub(r"\n*The total estimated cost for this.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\n*Total estimated cost:.*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\n*Overall cost estimate:.*$", "", text, flags=re.DOTALL)
    return text.strip()

def show_image_editor(original_image, prompt, key_suffix):
    """Show UI for editing an existing image"""
    with st.expander("🖌️ Edit This Image", expanded=False):
        edit_prompt = st.text_input(f"Describe your changes (e.g., 'add more trees', 'make it sunset')", 
                                   key=f"edit_{key_suffix}")
        
        if st.button("Apply Edits", key=f"apply_edit_{key_suffix}"):
            with st.spinner("Applying your edits..."):
                try:
                    edited_img = edit_image_with_prompt(original_image, edit_prompt)
                    if edited_img:
                        st.session_state.edited_images[key_suffix] = edited_img
                        st.success("Edit applied successfully!")
                        display_image_with_editor(edited_img)
                except Exception as e:
                    st.error(f"Failed to edit image: {str(e)}")

# Generate Trip Plan
if st.button("🚀 Generate Trip Plan", use_container_width=True):
    query_hash = make_query_hash(destination, days, budget, interests, start_date)
    cached_trip = get_cached_trip(query_hash)
    
    if cached_trip:
        st.session_state.update(cached_trip)
        st.success("✨ Loaded from cache!")
    else:
        with st.spinner("Building your perfect itinerary..."):
            # Weather Forecast
            try:
                st.session_state.weather_forecast = fetch_weather_forecast(destination, str(start_date), days)
            except Exception as e:
                st.warning(f"Weather fetch failed: {e}")
                st.session_state.weather_forecast = {}

            # Itinerary Generation
            try:
                itinerary = generate_itinerary(
                    destination, days, budget, interests, st.session_state.weather_forecast
                )
                st.session_state.itinerary_text = clean_itinerary_text(itinerary)
            except Exception as e:
                st.error(f"Itinerary generation failed: {e}")

            # Additional Info
            try:
                (st.session_state.packing_list, 
                 st.session_state.visa_info, 
                 st.session_state.food_list) = generate_addons(destination)
                
                # Generate food images
                if st.session_state.food_list:
                    food_items = [line.strip() for line in st.session_state.food_list.split('\n') 
                                if line.strip() and (line[0].isdigit() or line.startswith("-"))]
                    st.session_state.food_images = {}
                    for food in food_items[:5]:
                        try:
                            current_time = time.time()
                            time_since_last = current_time - st.session_state.last_image_gen_time
                            if time_since_last < IMAGE_GENERATION_DELAY:
                                time.sleep(IMAGE_GENERATION_DELAY - time_since_last)
                            
                            food_name = food.split(":")[0] if ":" in food else food.split("-")[0]
                            prompt = f"{food_name.strip()} from {destination}, {IMAGE_STYLES[st.session_state.selected_image_style]}"
                            
                            for retry in range(MAX_IMAGE_RETRIES):
                                img_data = generate_image(prompt)
                                validated = validate_image_data(img_data)
                                if validated:
                                    st.session_state.food_images[food] = validated
                                    break
                                time.sleep(1)
                                
                            st.session_state.last_image_gen_time = time.time()
                        except Exception as e:
                            st.warning(f"Food image skipped for {food}: {str(e)}")
            except Exception as e:
                st.warning(f"Addons fetch failed: {e}")

            # Hotels
            try:
                st.session_state.hotels = get_hotels_with_ratings(
                    city=destination,
                    min_rating=min_rating,
                    radius=search_radius_km * 1000,
                    max_results=5
                )
            except Exception as e:
                st.warning(f"Hotel fetch failed: {e}")
                st.session_state.hotels = []

            # Generate location images
            try:
                st.session_state.location_images = generate_location_images(
                    destination, 
                    st.session_state.itinerary_text,
                    days
                )
            except Exception as e:
                st.warning(f"Location image generation failed: {e}")
                st.session_state.location_images = {}

            # Geo Parsing
            try:
                if st.session_state.hotels:
                    hotel_coords = (st.session_state.hotels[0]['latitude'], st.session_state.hotels[0]['longitude'])
                    st.session_state.geo_parsed_itinerary = parse_itinerary_by_day_with_geo(
                        st.session_state.itinerary_text, destination, hotel_coords
                    )
            except Exception as e:
                st.warning(f"Geo parsing failed: {e}")
                st.session_state.geo_parsed_itinerary = {}

            # Cache trip
            trip_data = {
                k: v for k, v in st.session_state.items()
                if k in ['adults', 'children', 'infants', 'itinerary_text', 'packing_list',
                        'visa_info', 'food_list', 'hotels', 'geo_parsed_itinerary',
                        'weather_forecast', 'food_images', 'location_images',
                        'last_image_gen_time', 'selected_image_style', 'image_variants']
            }
            cache_trip(query_hash, trip_data)

# Display Results
if st.session_state.itinerary_text:
    # Weather Report
    if st.session_state.weather_forecast:
        st.header("🌦️ Weather Forecast")
        cols = st.columns(days)
        for day, info in st.session_state.weather_forecast.items():
            day_num = int(day)
            forecast_date = start_date + timedelta(days=day_num-1)
            weekday = forecast_date.strftime("%A")
            date_str = forecast_date.strftime("%b %d")
            
            with cols[day_num-1]:
                st.metric(f"Day {day} - {weekday} {date_str}", 
                         f"{info.get('morning', {}).get('weather', 'N/A')}",
                         f"🌡️ {info.get('morning', {}).get('temp', 'N/A')}°C")
                st.caption(f"☀️ Morning: {info.get('morning', {}).get('weather', 'N/A')}")
                st.caption(f"🌤️ Afternoon: {info.get('afternoon', {}).get('weather', 'N/A')}")
                st.caption(f"🌙 Evening: {info.get('evening', {}).get('weather', 'N/A')}")

    # Hotels
    st.header("🏨 Recommended Hotels")
    if st.session_state.hotels:
        hotel_names = [h['name'] for h in st.session_state.hotels]
        selected_hotel = st.selectbox("Choose your hotel", hotel_names, index=0)
        selected_hotel = next(h for h in st.session_state.hotels if h['name'] == selected_hotel)

        with st.expander(f"⭐ {selected_hotel['rating']} - {selected_hotel['name']}", expanded=True):
            st.markdown(f"📍 Address: {selected_hotel['address']}")
            st.markdown(f"👥 Reviews: {selected_hotel['user_ratings_total']}")
            st.markdown(f"🛏️ Room Types Available: {selected_hotel.get('room_types', 'Double, Twin, Family')}")
            st.markdown(f"\n[🗺️ View on Map](https://www.google.com/maps/search/?api=1&query={selected_hotel['latitude']},{selected_hotel['longitude']})")

    # Itinerary with Enhanced Image Features
    st.header("📅 Daily Itinerary")
    itinerary_tabs = st.tabs([f"Day {i+1}" for i in range(days)])
    
    for i, tab in enumerate(itinerary_tabs):
        day_num = i + 1
        day_key = f"Day {day_num}"
        with tab:
            pattern = rf"## {day_key}\n(.*?)(?=\n## Day {day_num + 1}|$)"
            match = re.search(pattern, st.session_state.itinerary_text, re.DOTALL)
            if match:
                day_content = match.group(1).strip()
                st.markdown(f"### 📍 {day_key}")
                
                lines = day_content.split("\n")
                for line in lines:
                    if line.strip():
                        col1, col2 = st.columns([3, 2])
                        with col1:
                            st.markdown(f"**{line.strip()}**")
                        with col2:
                            if (day_key in st.session_state.location_images and 
                                line.strip() in st.session_state.location_images[day_key]):
                                activity_key = sanitize_key(f"{day_key}_{line.strip()}")
                                current_img = st.session_state.location_images[day_key][line.strip()]

                                # Use the improved display function
                                edited_img = display_image_with_editor(
                                    current_img, 
                                    activity_key,
                                    context="activity"
                                )

                                # Update the image if it was edited
                                if edited_img != current_img:
                                    st.session_state.location_images[day_key][line.strip()] = edited_img
                                    st.rerun()

                                    # Show image editor
                                    show_image_editor(current_img, line.strip(), f"{day_key}_{line.strip()}")

    # Packing List
    st.header("🧳 Smart Packing List")
    if st.session_state.packing_list:
        with st.expander("👕 Clothing", expanded=False):
            cloth_cols = st.columns(3)
            with cloth_cols[0]:
                if "Adults_Male" in st.session_state.packing_list:
                    st.markdown("**Adults (Male)**")
                    for item in st.session_state.packing_list["Adults_Male"]:
                        st.markdown(f"- {item}")
            with cloth_cols[1]:
                if "Adults_Female" in st.session_state.packing_list:
                    st.markdown("**Adults (Female)**")
                    for item in st.session_state.packing_list["Adults_Female"]:
                        st.markdown(f"- {item}")
            with cloth_cols[2]:
                if "Kids_Babies" in st.session_state.packing_list:
                    st.markdown("**Kids & Babies**")
                    for item in st.session_state.packing_list["Kids_Babies"]:
                        st.markdown(f"- {item}")
        
        for cat, items in st.session_state.packing_list.items():
            if cat not in ["Adults_Male", "Adults_Female", "Kids_Babies"]:
                with st.expander(f"📦 {cat}", expanded=False):
                    for item in items:
                        st.markdown(f"- {item}")

    # Food Recommendations with Enhanced Images
    st.header("🍽️ Must-Try Local Foods")
    if st.session_state.food_list:
        food_items = [line.strip() for line in st.session_state.food_list.split('\n') if line.strip()]

        # Use a grid layout instead of columns for better control
        for idx, food in enumerate(food_items[:5]):
            if idx % 2 == 0:
                cols = st.columns([3, 2])  # Create new row for every 2 items

            with cols[0] if idx % 2 == 0 else cols[1]:
                st.markdown(f"**{food.split(':')[0] if ':' in food else food}**")

                if food in st.session_state.food_images and st.session_state.food_images[food]:
                    food_key = sanitize_key(f"food_{food}")

                    # Create a container for the image and editor
                    with st.container():
                        img_col, edit_col = st.columns([3, 2])

                        with img_col:
                            try:
                                current_img = validate_image_data(st.session_state.food_images[food])
                                if current_img:
                                    st.image(current_img, use_container_width=True)
                            except Exception as e:
                                st.warning(f"Couldn't display image: {str(e)}")

                        with edit_col:
                            st.markdown("### 🖌️ Edit Options")
                            edit_option = st.radio(
                                "Edit type:",
                                ["None", "Enhance", "Custom"],
                                key=f"food_edit_type_{food_key}"
                            )

                            if edit_option == "Enhance":
                                enhancement = st.select_slider(
                                    "Brightness:",
                                    options=["Darker", "Original", "Brighter"],
                                    value="Original",
                                    key=f"food_enhance_{food_key}"
                                )

                                if st.button("Apply", key=f"food_apply_{food_key}"):
                                    with st.spinner("Enhancing..."):
                                        try:
                                            img_bytes = base64.b64decode(
                                                st.session_state.food_images[food].split(",")[-1] 
                                                if "," in st.session_state.food_images[food] 
                                                else st.session_state.food_images[food]
                                            )
                                            img = Image.open(io.BytesIO(img_bytes))

                                            from PIL import ImageEnhance
                                            enhancer = ImageEnhance.Brightness(img)
                                            factor = 0.7 if enhancement == "Darker" else 1.3
                                            enhanced_img = enhancer.enhance(factor)

                                            buffered = io.BytesIO()
                                            enhanced_img.save(buffered, format="PNG")
                                            edited_img = f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
                                            st.session_state.food_images[food] = edited_img
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Failed: {str(e)}")

                            elif edit_option == "Custom":
                                edit_prompt = st.text_input(
                                    "Edit prompt:",
                                    key=f"food_prompt_{food_key}"
                                )

                                if st.button("Apply Edit", key=f"food_apply_custom_{food_key}"):
                                    with st.spinner("Editing..."):
                                        try:
                                            img_bytes = base64.b64decode(
                                                st.session_state.food_images[food].split(",")[-1] 
                                                if "," in st.session_state.food_images[food] 
                                                else st.session_state.food_images[food]
                                            )
                                            edited_img = edit_image_with_prompt(img_bytes, edit_prompt)
                                            if edited_img:
                                                st.session_state.food_images[food] = (
                                                    f"data:image/png;base64,{base64.b64encode(edited_img).decode('utf-8')}"
                                                    if not isinstance(edited_img, str)
                                                    else edited_img
                                                )
                                                st.rerun()
                                        except Exception as e:
                                            st.error(f"Edit failed: {str(e)}")

    # Visa Info
    st.header("🛂 Visa & Travel Requirements")
    st.markdown(st.session_state.visa_info)

    # PDF Export
    st.header("📤 Export Your Trip Plan")
    if st.button("💾 Download as PDF", use_container_width=True):
        with st.spinner("Generating PDF..."):
            img_paths = []
            
            # Save food images
            for food, img_data in st.session_state.food_images.items():
                try:
                    if img_data:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                            img_bytes = base64.b64decode(img_data.split(",")[-1] if "," in img_data else base64.b64decode(img_data))
                            tmp.write(img_bytes)
                            img_paths.append(tmp.name)
                except Exception as e:
                    st.warning(f"Failed to process food image: {str(e)}")
            
            # Save location images
            for day, activities in st.session_state.location_images.items():
                for activity, img_data in activities.items():
                    try:
                        if img_data:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                                img_bytes = base64.b64decode(img_data.split(",")[-1] if "," in img_data else base64.b64decode(img_data))
                                tmp.write(img_bytes)
                                img_paths.append(tmp.name)
                    except Exception as e:
                        st.warning(f"Failed to process location image: {str(e)}")
            
            # Generate PDF
            try:
                pdf_path = export_to_pdf(
                    dest=destination,
                    itinerary=st.session_state.itinerary_text,
                    packing="\n".join([f"{cat}:\n" + "\n".join(items) for cat, items in st.session_state.packing_list.items()]),
                    visa=st.session_state.visa_info,
                    food=st.session_state.food_list,
                    img_paths=img_paths
                )
                
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                
                st.download_button(
                    label="⬇️ Click to Download PDF",
                    data=pdf_bytes,
                    file_name=f"{destination}_trip_plan.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"Failed to generate PDF: {str(e)}")
            finally:
                for path in img_paths:
                    try:
                        os.unlink(path)
                    except:
                        pass
