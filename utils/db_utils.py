from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError, PyMongoError
from hashlib import sha256
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from bson import Binary
import time
import base64
from typing import Dict, Any, Optional, Union
import traceback

load_dotenv()

# Constants
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
CACHE_EXPIRY_DAYS = 30  # Days after which cache is considered stale
RECENT_CACHE_DAYS = 7  # Days within which cache is considered fresh

class DatabaseConnection:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseConnection, cls).__new__(cls)
            cls._instance._initialize_connection()
        return cls._instance
    
    def _initialize_connection(self):
        self.client = None
        self.db = None
        self.connected = False
        self.last_connection_attempt = None
        self._connect()
    
    def _connect(self):
        """Establish database connection with retry logic"""
        MONGO_URI = os.getenv("MONGO_URI")
        if not MONGO_URI:
            raise ValueError("MongoDB connection string not found in environment variables")
        
        retries = 0
        while retries < MAX_RETRIES:
            try:
                self.client = MongoClient(
                    MONGO_URI,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=30000,
                    serverSelectionTimeoutMS=5000,
                    retryWrites=True,
                    retryReads=True
                )
                
                # Test the connection
                self.client.admin.command('ismaster')
                self.db = self.client["triptales_db"]
                self.connected = True
                self.last_connection_attempt = datetime.now()
                
                # Create indexes
                self._create_indexes()
                break
            except (ConnectionFailure, ConfigurationError) as e:
                retries += 1
                if retries == MAX_RETRIES:
                    self.connected = False
                    raise ConnectionError(f"Failed to connect to MongoDB after {MAX_RETRIES} attempts: {str(e)}")
                time.sleep(RETRY_DELAY)
    
    def _create_indexes(self):
        """Create necessary indexes for performance"""
        try:
            self.db.trips.create_index([("query_hash", 1)], unique=True)
            self.db.trips.create_index([("last_updated", 1)], expireAfterSeconds=CACHE_EXPIRY_DAYS*24*60*60)
            self.db.trips.create_index([("destination", "text")])
            self.db.generated_images.create_index([("prompt_hash", 1)], unique=True)
            self.db.generated_images.create_index([("last_used", 1)], expireAfterSeconds=CACHE_EXPIRY_DAYS*24*60*60)
        except PyMongoError as e:
            print(f"Warning: Failed to create indexes: {str(e)}")
    
    def get_collection(self, collection_name):
        """Get a collection with connection retry logic"""
        if not self.connected:
            # Only attempt reconnection if last attempt was more than 5 minutes ago
            if not self.last_connection_attempt or (datetime.now() - self.last_connection_attempt).total_seconds() > 300:
                self._connect()
            if not self.connected:
                raise ConnectionError("Database connection unavailable")
        return self.db[collection_name]
    
    def health_check(self):
        """Check if database is responsive"""
        try:
            self.client.admin.command('ping')
            return True
        except:
            return False

# Initialize database connection
try:
    db_connection = DatabaseConnection()
    trips_collection = db_connection.get_collection("trips")
    images_collection = db_connection.get_collection("generated_images")
except Exception as e:
    print(f"Critical database error: {e}")
    trips_collection = None
    images_collection = None

def make_query_hash(destination: str, days: int, budget: int, interests: list, start_date: str) -> str:
    """Create unique hash for query parameters"""
    try:
        query_dict = {
            "destination": destination.lower().strip(),
            "days": days,
            "budget": budget,
            "interests": sorted([i.lower().strip() for i in interests]),
            "start_date": str(start_date)
        }
        return sha256(json.dumps(query_dict, sort_keys=True).encode()).hexdigest()
    except Exception as e:
        print(f"Error generating query hash: {str(e)}")
        raise

def get_cached_trip(query_hash: str) -> Optional[Dict[str, Any]]:
    """Retrieve cached trip data including images with proper error handling"""
    if trips_collection is None:
        return None
        
    try:
        # Only return recent cache (within RECENT_CACHE_DAYS)
        min_date = datetime.now() - timedelta(days=RECENT_CACHE_DAYS)
        
        result = trips_collection.find_one({
            "query_hash": query_hash,
            "last_updated": {"$gte": min_date}
        })
        
        if not result:
            return None

        trip_data = result.get("trip_data", {})
        
        def convert_image_data(img_data: Union[bytes, Binary, str]) -> Optional[str]:
            """Convert stored image data to displayable format"""
            if img_data is None:
                return None
            try:
                if isinstance(img_data, (bytes, Binary)):
                    return base64.b64encode(img_data).decode('utf-8')
                elif isinstance(img_data, str):
                    if img_data.startswith('data:image'):
                        return img_data
                    # Validate it's proper base64
                    base64.b64decode(img_data)
                    return f"data:image/png;base64,{img_data}"
                return None
            except:
                return None
        
        # Handle location images
        if "location_images" in trip_data:
            converted_location_images = {}
            for day, activities in trip_data["location_images"].items():
                converted_activities = {}
                for activity, img_data in activities.items():
                    converted_img = convert_image_data(img_data)
                    if converted_img:
                        converted_activities[activity] = converted_img
                if converted_activities:
                    converted_location_images[day] = converted_activities
            trip_data["location_images"] = converted_location_images
        
        # Handle food images
        if "food_images" in trip_data:
            converted_food_images = {}
            for food, img_data in trip_data["food_images"].items():
                converted_img = convert_image_data(img_data)
                if converted_img:
                    converted_food_images[food] = converted_img
            trip_data["food_images"] = converted_food_images
        
        return trip_data
    except Exception as e:
        print(f"Database error while retrieving cached trip: {str(e)}")
        return None

def cache_trip(query_hash: str, trip_data: Dict[str, Any]) -> bool:
    """Store trip data including images in database with proper error handling"""
    if trips_collection is None:
        return False
        
    try:
        # Prepare image data for storage (convert base64 to binary)
        prepared_data = trip_data.copy()
        
        def prepare_image_data(img_data: Union[str, bytes]) -> Optional[Binary]:
            """Convert image data to storage format"""
            if img_data is None:
                return None
            try:
                if isinstance(img_data, str):
                    if img_data.startswith('data:image'):
                        return Binary(base64.b64decode(img_data.split(',')[1]))
                    return Binary(base64.b64decode(img_data))
                elif isinstance(img_data, bytes):
                    return Binary(img_data)
                return None
            except:
                return None
        
        # Handle location images
        if "location_images" in prepared_data:
            prepared_location_images = {}
            for day, activities in prepared_data["location_images"].items():
                prepared_activities = {}
                for activity, img_data in activities.items():
                    prepared_img = prepare_image_data(img_data)
                    if prepared_img:
                        prepared_activities[activity] = prepared_img
                if prepared_activities:
                    prepared_location_images[day] = prepared_activities
            prepared_data["location_images"] = prepared_location_images
        
        # Handle food images
        if "food_images" in prepared_data:
            prepared_food_images = {}
            for food, img_data in prepared_data["food_images"].items():
                prepared_img = prepare_image_data(img_data)
                if prepared_img:
                    prepared_food_images[food] = prepared_img
            prepared_data["food_images"] = prepared_food_images
        
        # Store in database with TTL
        result = trips_collection.update_one(
            {"query_hash": query_hash},
            {"$set": {
                "trip_data": prepared_data,
                "last_updated": datetime.now(),
                "destination": trip_data.get("destination", "").lower(),
                "days": trip_data.get("days", 0),
                "budget": trip_data.get("budget", 0),
                "interests": [i.lower() for i in trip_data.get("interests", [])],
                "expire_at": datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
            }},
            upsert=True
        )
        return result.acknowledged
    except Exception as e:
        print(f"Failed to cache trip: {str(e)}")
        return False

def get_cached_image(prompt: str) -> Optional[str]:
    """Retrieve cached generated image by prompt with proper error handling"""
    if images_collection is None:
        return None
        
    try:
        prompt_hash = sha256(prompt.encode()).hexdigest()
        min_date = datetime.now() - timedelta(days=RECENT_CACHE_DAYS)
        
        result = images_collection.find_one({
            "prompt_hash": prompt_hash,
            "last_used": {"$gte": min_date}
        })
        
        if not result:
            return None
        
        img_data = result.get("image_data")
        if not img_data:
            return None
        
        if isinstance(img_data, (bytes, Binary)):
            return base64.b64encode(img_data).decode('utf-8')
        return None
    except Exception as e:
        print(f"Database error while retrieving cached image: {str(e)}")
        return None

def cache_image(prompt: str, image_data: str) -> bool:
    """Store generated image in database with proper error handling"""
    if images_collection is None:
        return False
        
    try:
        if not image_data or not isinstance(image_data, str):
            return False
        
        # Extract base64 data if it's a data URI
        if image_data.startswith('data:image'):
            image_data = image_data.split(',')[1]
        
        prompt_hash = sha256(prompt.encode()).hexdigest()
        
        result = images_collection.update_one(
            {"prompt_hash": prompt_hash},
            {"$set": {
                "prompt": prompt,
                "image_data": Binary(base64.b64decode(image_data)),
                "last_used": datetime.now(),
                "expire_at": datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
            }},
            upsert=True
        )
        return result.acknowledged
    except Exception as e:
        print(f"Failed to cache image: {str(e)}")
        return False

def get_similar_trips(destination: str, interests: list) -> list:
    """Find similar trips for recommendation with proper error handling"""
    if trips_collection is None:
        return []
        
    try:
        # Find trips with same destination and at least one matching interest
        query = {
            "destination": destination.lower(),
            "interests": {"$in": [i.lower() for i in interests]}
        }
        
        results = trips_collection.find(query).sort("last_updated", -1).limit(5)
        
        similar_trips = []
        for result in results:
            trip_data = result.get("trip_data", {})
            similar_trips.append({
                "days": trip_data.get("days", 0),
                "interests": trip_data.get("interests", []),
                "summary": trip_data.get("itinerary_text", "")[:200] + "..." if "itinerary_text" in trip_data else ""
            })
        
        return similar_trips
    except Exception as e:
        print(f"Database error while finding similar trips: {str(e)}")
        return []

def clear_old_cache(days_old: int = 30) -> int:
    """Manually clear cache entries older than specified days"""
    if trips_collection is None or images_collection is None:
        return 0
        
    try:
        cutoff_date = datetime.now() - timedelta(days=days_old)
        
        # Clear old trips
        trips_result = trips_collection.delete_many({
            "last_updated": {"$lt": cutoff_date}
        })
        
        # Clear old images
        images_result = images_collection.delete_many({
            "last_used": {"$lt": cutoff_date}
        })
        
        return trips_result.deleted_count + images_result.deleted_count
    except Exception as e:
        print(f"Failed to clear old cache: {str(e)}")
        return 0
    

def test_db_connection():
    if db_connection.health_check():
        print("✅ Database connection working!")
    else:
        print("❌ Database connection failed")

#if __name__ == "__main__":
#    test_db_connection()