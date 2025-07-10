import os
import time
import json
import boto3
import base64
import io
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from PIL import Image

load_dotenv()

bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("AWS_REGION"),
)

TEXT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
IMAGE_MODEL_ID = "amazon.titan-image-generator-v1"

def call_bedrock_text(prompt):
    native_request = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.5,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    }

    try:
        time.sleep(1)  # Rate limiting
        response = bedrock.invoke_model(
            modelId=TEXT_MODEL_ID,
            body=json.dumps(native_request),
            contentType="application/json",
            accept="application/json"
        )
        model_response = json.loads(response["body"].read())
        return model_response["content"][0]["text"]
    except ClientError as e:
        if e.response['Error']['Code'] == 'ThrottlingException':
            time.sleep(2)
            return call_bedrock_text(prompt)  # Retry
        return f"[ERROR] Claude call failed: {str(e)}"
    except Exception as e:
        return f"[ERROR] Unexpected error: {str(e)}"

def generate_itinerary(destination, days, budget, interests, weather_by_day=None):
    weather_note = ""
    if weather_by_day:
        weather_note += "## Weather Forecast:\n"
        for day, info in weather_by_day.items():
            weather_note += (
                f"- Day {day}: "
                f"🌅 {info.get('morning', {}).get('weather', 'N/A')} ({info.get('morning', {}).get('temp', 'N/A')}°C / "
                f"🌇 {info.get('afternoon', {}).get('weather', 'N/A')} ({info.get('afternoon', {}).get('temp', 'N/A')}°C / "
                f"🌃 {info.get('evening', {}).get('weather', 'N/A')} ({info.get('evening', {}).get('temp', 'N/A')}°C\n"
            )
        weather_note += "\n"

    prompt = (
        f"{weather_note}"
        f"Create a {days}-day travel itinerary for a trip to {destination} under ${budget} total, "
        f"focused on these interests: {', '.join(interests)}.\n\n"
        "Structure each day like this:\n"
        "## Day X\n"
        "- Each activity must start from a new line.\n"
        "- Include a short, vivid description with exact location and relevance.\n"
        "- Mention estimated cost in parentheses like '($10-15)' if applicable.\n\n"
        "Requirements:\n"
        "- Include 2–4 well-paced activities per day\n"
        "- Each activity must be weather-aware and culturally enriching\n"
        "- Add variety across the trip\n"
        "- Highlight free/low-cost options\n"
        "- Format clearly so each activity is easily readable on a new line\n"
    )
    return call_bedrock_text(prompt)

def generate_addons(destination):
    packing_prompt = (
        f"Create a comprehensive packing list for {destination} considering:\n"
        "- Different weather conditions\n"
        "- Cultural norms\n"
        "- Various demographic groups\n\n"
        "Return ONLY a JSON object with these categories:\n"
        "{\n"
        "\"Adults_Male\": [\"item1\", \"item2\"],\n"
        "\"Adults_Female\": [\"item1\", \"item2\"],\n"
        "\"Kids_Babies\": [\"item1\", \"item2\"],\n"
        "\"Essentials\": [\"item1\", \"item2\"],\n"
        "\"Electronics\": [\"item1\", \"item2\"],\n"
        "\"Toiletries\": [\"item1\", \"item2\"],\n"
        "\"Documents\": [\"item1\", \"item2\"],\n"
        "\"Optional\": [\"item1\", \"item2\"]\n}"
    )
    raw_packing = call_bedrock_text(packing_prompt)

    try:
        if "```json" in raw_packing:
            json_str = raw_packing.split("```json")[1].split("```")[0]
        elif "```" in raw_packing:
            json_str = raw_packing.split("```")[1]
        else:
            json_str = raw_packing

        packing = json.loads(json_str)
        if not isinstance(packing, dict):
            raise ValueError("Invalid packing list format")
    except Exception as e:
        #print(f"[ERROR] Packing list parse failed: {e}")
        packing = {
            "Clothing": [], "Essentials": [], "Electronics": [],
            "Toiletries": [], "Documents": [], "Optional": []
        }

    visa_prompt = (
        f"Provide detailed visa requirements for traveling to {destination} as a tourist. "
        "Include:\n"
        "- Visa types available\n"
        "- Application process\n"
        "- Required documents\n"
        "- Processing time\n"
        "- Costs\n"
        "- Any special requirements\n"
        "Format as clear bullet points"
    )
    visa = call_bedrock_text(visa_prompt)

    food_prompt = (
        f"List the top 5 must-try local foods in {destination}.\n"
        "Format each item EXACTLY like this example:\n"
        "1. Kebabs: Tender minced meat kebabs - $5-10 per plate. Best at: Tunday Kababi\n"
        "2. Biryani: Fragrant rice dish with meat - $8-15. Best at: Idris Biryani\n\n"
        "For each item include:\n"
        "- Numbered list (1-3)\n"
        "- Name before colon\n"
        "- Short description after colon\n"
        "- Price range after dash\n"
        "- Best places to try it after 'Best at:'\n"
        "Keep each item to one line only"
    )
    food = call_bedrock_text(food_prompt)

    return packing, visa, food

def generate_image(prompt, style_preset=None):
    enhanced_prompt = (
        f"High-quality professional: {prompt}. "
        "Ultra HD, realistic lighting, vibrant colors, "
        "perfect composition, no distortion or artifacts."
    )

    payload = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": enhanced_prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 512,
            "width": 512,
            "cfgScale": 8.5,
            "seed": int(time.time()) % 1000,
        }
    }

    try:
        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        result = json.loads(response["body"].read())
        image_data = result.get("images", [None])[0]

        if image_data is None:
            raise ValueError("No image data returned")

        if image_data.startswith("data:image"):
            image_data = image_data.split(",")[-1]

        img_bytes = base64.b64decode(image_data)
        Image.open(io.BytesIO(img_bytes))  # Validate image

        return image_data
    except Exception as e:
        #print(f"[ERROR] Image generation failed: {str(e)}")
        return None

def generate_image_variants(prompt, num_variants=3):
    """Generate multiple variants of the same prompt"""
    variants = []
    for i in range(num_variants):
        payload = {
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {"text": prompt},
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "height": 512,
                "width": 512,
                "cfgScale": 8.5,
                "seed": (int(time.time()) + i) % 1000,  # Different seed for each variant
            }
        }
        
        try:
            response = bedrock.invoke_model(
                modelId=IMAGE_MODEL_ID,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json"
            )
            result = json.loads(response["body"].read())
            image_data = result.get("images", [None])[0]
            if image_data:
                variants.append(image_data.split(",")[-1] if image_data.startswith("data:image") else image_data)
        except Exception as e:
            #print(f"[ERROR] Variant {i} failed: {str(e)}")
            pass
    
    return variants if variants else None

def edit_image_with_prompt(image_data, edit_prompt):
    """Edit an existing image based on text prompt
    
    Args:
        image_data: Can be either:
                   - base64 encoded string (with or without data URL prefix)
                   - raw bytes of the image
        edit_prompt: Text description of desired edits
    
    Returns:
        base64 encoded image string without data URL prefix, or None if failed
    """
    try:
        # Convert input to proper base64 string (without data URL prefix)
        if isinstance(image_data, bytes):
            base64_str = base64.b64encode(image_data).decode('utf-8')
        elif isinstance(image_data, str):
            if image_data.startswith('data:image'):
                base64_str = image_data.split(',')[1]
            else:
                # Assume it's already pure base64
                base64_str = image_data
        else:
            raise ValueError("Unsupported image data type")
        
        # Validate base64
        try:
            base64.b64decode(base64_str)
        except:
            raise ValueError("Invalid base64 image data")

        payload = {
            "taskType": "IMAGE_EDIT",
            "image": base64_str,
            "text": edit_prompt,
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "height": 512,
                "width": 512,
                "cfgScale": 8.5,
                "seed": int(time.time()) % 1000,
            }
        }

        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        
        result = json.loads(response["body"].read())
        edited_image = result.get("images", [None])[0]
        
        if not edited_image:
            raise ValueError("No image returned in response")
            
        # Return consistent format (base64 without prefix)
        return edited_image.split(",")[-1] if edited_image.startswith("data:image") else edited_image
        
    except Exception as e:
        #print(f"[ERROR] Image editing failed: {str(e)}")
        #import traceback
        #traceback.print_exc()
        return None

def transform_image_style(base64_image, style_prompt):
    """Transform an image to a different style"""
    try:
        payload = {
            "taskType": "IMAGE_VARIATION",
            "image": base64_image,
            "text": style_prompt,
            "imageGenerationConfig": {
                "numberOfImages": 1,
                "height": 512,
                "width": 512,
                "cfgScale": 8.5,
                "seed": int(time.time()) % 1000,
            }
        }

        response = bedrock.invoke_model(
            modelId=IMAGE_MODEL_ID,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        result = json.loads(response["body"].read())
        transformed_image = result.get("images", [None])[0]
        
        if transformed_image:
            return transformed_image.split(",")[-1] if transformed_image.startswith("data:image") else transformed_image
        return None
    except Exception as e:
        #print(f"[ERROR] Image transformation failed: {str(e)}")
        return None

def generate_day_to_night_image(base64_day_image):
    """Convert a day scene to night version"""
    prompt = (
        "Transform this daytime scene into nighttime. "
        "Add warm artificial lights, moonlight, and adjust colors for nighttime atmosphere. "
        "Maintain the same composition but with nighttime lighting."
    )
    return edit_image_with_prompt(base64_day_image, prompt)

def generate_illustrated_map(prompt):
    """Generate a stylized map from text description"""
    enhanced_prompt = (
        f"Tourist map illustration: {prompt}. "
        "Vintage travel poster style with clear landmarks, "
        "paths between locations, and decorative elements. "
        "Include a compass rose and subtle topographic details."
    )
    return generate_image(enhanced_prompt)