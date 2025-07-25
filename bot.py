# Simplified Location Bot - Store Check-ins
# Last updated: 2024-01-25 - Simplified for essential info only
import discord
from discord.ext import commands, tasks
import os
import math
import asyncio
import json
from flask import Flask, request, jsonify, render_template_string
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import threading
import time
import sys
import requests
import googlemaps
from datetime import datetime, timedelta, timezone
import sqlite3
from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import uuid
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
from collections import defaultdict
import asyncio


# Enhanced Flask app with rate limiting
app = Flask(__name__)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://",
    app=app
)

# Enhanced bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Add rate limit handling
bot.http.rate_limit_delay = 1.0  # Add 1 second delay between requests

# Google Maps client
gmaps = None

# Enhanced database configuration
DATABASE_PATH = 'enhanced_location_bot.db'
CACHE_ENABLED = os.getenv('REDIS_URL') is not None

# Flask Configuration
FLASK_HOST = '0.0.0.0'
FLASK_PORT = int(os.getenv('PORT', 8080))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# Enhanced logging setup
def setup_enhanced_logging():
    """Setup comprehensive logging system"""
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        'location_bot.log', 
        maxBytes=50*1024*1024,  # 50MB
        backupCount=10
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Setup logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_enhanced_logging()

def safe_print(msg):
    """Enhanced safe printing with logging"""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    formatted_msg = f"[BOT] {timestamp} {msg}"
    try:
        print(formatted_msg)
        sys.stdout.flush()
        logger.info(msg)
    except Exception as e:
        logger.error(f"Logging error: {e}")

def handle_error(error, context="Unknown"):
    """Enhanced error handling with unique IDs"""
    error_id = str(uuid.uuid4())[:8]
    error_msg = f"[{error_id}] {context}: {str(error)}"
    
    logger.error(error_msg, exc_info=True)
    safe_print(f"❌ Error {error_id}: {context}")
    
    return error_id

# Enhanced caching system
class EnhancedLocationCache:
    """Cache with fallback to in-memory"""
    
    def __init__(self, default_ttl=1800):
        self.default_ttl = default_ttl
        self.memory_cache = {}
        self.redis_client = None
        
        if CACHE_ENABLED:
            try:
                import redis
                redis_url = os.getenv('REDIS_URL')
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                safe_print("✅ Redis cache connected")
            except Exception as e:
                safe_print(f"⚠️ Redis connection failed, using memory cache: {e}")
    
    def _get_cache_key(self, lat: float, lng: float, radius: int, category: str = None) -> str:
        rounded_lat = round(lat, 3)
        rounded_lng = round(lng, 3)
        base_key = f"stores_v2:{rounded_lat}:{rounded_lng}:{radius}"  # Added v2 to force cache refresh
        return f"{base_key}:{category}" if category else base_key
    
    def get(self, lat: float, lng: float, radius: int, category: str = None) -> Optional[List[Dict]]:
        key = self._get_cache_key(lat, lng, radius, category)
        
        try:
            if self.redis_client:
                cached_data = self.redis_client.get(key)
                if cached_data:
                    safe_print(f"📋 Redis cache HIT for {key}")
                    return pickle.loads(cached_data)
            else:
                # Fallback to memory cache
                if key in self.memory_cache:
                    data, expiry = self.memory_cache[key]
                    if datetime.now() < expiry:
                        safe_print(f"📋 Memory cache HIT for {key}")
                        return data
                    else:
                        del self.memory_cache[key]
        except Exception as e:
            handle_error(e, "Cache get operation")
        
        return None
    
    def set(self, lat: float, lng: float, radius: int, data: List[Dict], category: str = None, ttl: Optional[int] = None) -> None:
        key = self._get_cache_key(lat, lng, radius, category)
        cache_ttl = ttl or self.default_ttl
        
        try:
            if self.redis_client:
                self.redis_client.setex(key, cache_ttl, pickle.dumps(data))
                safe_print(f"💾 Cached {len(data)} items to Redis: {key}")
            else:
                # Fallback to memory cache
                expiry = datetime.now() + timedelta(seconds=cache_ttl)
                self.memory_cache[key] = (data, expiry)
                safe_print(f"💾 Cached {len(data)} items to memory: {key}")
        except Exception as e:
            handle_error(e, "Cache set operation")
    
    def clear_expired(self) -> None:
        """Clean up expired memory cache entries"""
        if not self.redis_client and self.memory_cache:
            now = datetime.now()
            expired_keys = [k for k, (_, expiry) in self.memory_cache.items() if now >= expiry]
            for key in expired_keys:
                del self.memory_cache[key]
            if expired_keys:
                safe_print(f"🧹 Cleared {len(expired_keys)} expired cache entries")

# Global cache instance
store_cache = EnhancedLocationCache()

# Enhanced database connection pool
class DatabasePool:
    def __init__(self, database_path, pool_size=10):
        self.database_path = database_path
        self.pool_size = pool_size
        self.connections = []
        self.lock = threading.Lock()
        self._init_pool()
    
    def _init_pool(self):
        for _ in range(self.pool_size):
            conn = sqlite3.connect(
                self.database_path, 
                check_same_thread=False,
                timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=10000')
            self.connections.append(conn)
    
    @contextmanager
    def get_connection(self):
        with self.lock:
            if self.connections:
                conn = self.connections.pop()
            else:
                conn = sqlite3.connect(
                    self.database_path,
                    check_same_thread=False,
                    timeout=30.0
                )
                conn.row_factory = sqlite3.Row
        
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            handle_error(e, "Database operation")
            raise
        finally:
            with self.lock:
                if len(self.connections) < self.pool_size:
                    self.connections.append(conn)
                else:
                    conn.close()

db_pool = DatabasePool(DATABASE_PATH)

def init_enhanced_database():
    """Initialize enhanced database schema"""
    with db_pool.get_connection() as conn:
        # Enhanced user locations table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                guild_id TEXT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                accuracy REAL,
                store_name TEXT,
                store_address TEXT,
                store_place_id TEXT,
                store_category TEXT,
                distance REAL,
                weather_data TEXT,
                visit_duration INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_real_time BOOLEAN DEFAULT FALSE,
                session_id TEXT
            )
        ''')
        
        # Create indexes
        conn.execute('CREATE INDEX IF NOT EXISTS idx_user_timestamp ON user_locations(user_id, timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_location ON user_locations(lat, lng)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_store_category ON user_locations(store_category)')
        
        # Enhanced user permissions
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                server_id TEXT,
                permissions TEXT,
                granted_by TEXT,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User favorites
        conn.execute('''
            CREATE TABLE IF NOT EXISTS favorite_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                address TEXT,
                category TEXT,
                notes TEXT,
                visit_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for favorites
        conn.execute('CREATE INDEX IF NOT EXISTS idx_user_favorites ON favorite_locations(user_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_category ON favorite_locations(category)')
        
        # Analytics table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS usage_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                guild_id TEXT,
                action TEXT NOT NULL,
                data TEXT,
                ip_address TEXT,
                user_agent TEXT,
                session_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for analytics
        conn.execute('CREATE INDEX IF NOT EXISTS idx_action_timestamp ON usage_analytics(action, timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_user_analytics ON usage_analytics(user_id, timestamp)')
        
        # Location sharing sessions
        conn.execute('''
            CREATE TABLE IF NOT EXISTS location_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                channel_id TEXT NOT NULL,
                guild_id TEXT,
                created_by TEXT NOT NULL,
                session_name TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                max_participants INTEGER DEFAULT 10,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        
        # Last location cache table for quick check-ins
        conn.execute('''
            CREATE TABLE IF NOT EXISTS last_locations (
                user_id TEXT PRIMARY KEY,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy REAL,
                last_updated TEXT DEFAULT (datetime('now')),
                store_preference TEXT DEFAULT 'all',
                FOREIGN KEY (user_id) REFERENCES user_permissions(user_id)
            )
        ''')
        
        # Create index for last locations
        conn.execute('CREATE INDEX IF NOT EXISTS idx_last_location_user ON last_locations(user_id)')
        
        # Session participants
        conn.execute('''
            CREATE TABLE IF NOT EXISTS session_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_location_update TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                UNIQUE(session_id, user_id)
            )
        ''')
        
        # Create indexes for sessions
        conn.execute('CREATE INDEX IF NOT EXISTS idx_session_channel ON location_sessions(channel_id, is_active)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_session_participants ON session_participants(session_id, is_active)')

# Comprehensive store database
@dataclass
class StoreConfig:
    query: str
    chain: str
    icon: str
    category: str
    priority: int
    search_terms: List[str] = None

def get_comprehensive_store_database():
    """Focused store database - only Target, Walmart, BJ's, and Best Buy for fast check-ins"""
    return [
        # Primary stores (Priority 1) - Exactly what you want
        StoreConfig("Target", "Target", "🎯", "Department", 1, ["Target", "Target Store", "Target Corporation", "Target Superstore", "Target retail", "Target department store", "471 Salem St", "Salem St Target", "Medford Target"]),
        StoreConfig("Walmart", "Walmart", "🏪", "Superstore", 1, ["Walmart", "Walmart Supercenter"]),
        StoreConfig("BJ's Wholesale Club", "BJs", "🛒", "Wholesale", 1, ["BJ's", "BJs", "BJ's Wholesale"]),
        StoreConfig("Best Buy", "Best Buy", "🔌", "Electronics", 1, ["Best Buy", "BestBuy"]),
    ]

def get_quick_stores():
    """Get the 4 primary stores for quick check-ins"""
    return [
        {"name": "Target", "icon": "🎯", "keywords": ["target", "bullseye"]},
        {"name": "Walmart", "icon": "🏪", "keywords": ["walmart", "wal-mart"]},
        {"name": "BJ's Wholesale Club", "icon": "🛒", "keywords": ["bjs", "bj's", "wholesale"]},
        {"name": "Best Buy", "icon": "🔌", "keywords": ["best buy", "bestbuy", "electronics"]}
    ]

def initialize_google_maps():
    """Enhanced Google Maps initialization"""
    global gmaps
    
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - real-time search disabled")
        return False
    
    # Initialize weather API key
    global WEATHER_API_KEY
    WEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
    
    try:
        gmaps = googlemaps.Client(key=api_key)
        
        # Test the API key with a simple request
        test_result = gmaps.geocode("Boston, MA", region="us")
        if test_result:
            safe_print("✅ Google Maps API initialized successfully")
            
            # Test Places API
            try:
                places_result = gmaps.places_nearby(
                    location=(42.3601, -71.0589),
                    radius=1000,
                    keyword="store"
                )
                safe_print("✅ Google Places API verified")
                return True
            except Exception as places_error:
                safe_print(f"⚠️ Google Places API issue: {places_error}")
                return True  # Geocoding works, continue anyway
        else:
            safe_print("❌ Google Maps API key validation failed")
            return False
            
    except Exception as e:
        safe_print(f"❌ Google Maps API initialization failed: {e}")
        gmaps = None
        return False

def search_stores_parallel(store_configs, location, radius_meters, max_stores_per_type):
    """Search for stores using parallel processing with ThreadPoolExecutor"""
    if not gmaps:
        return []
    
    def search_single_store(store_config):
        """Search for a single store type"""
        try:
            search_terms = store_config.search_terms or [store_config.query]
            found_places = []
            
            for search_term in search_terms:
                try:
                    places_result = gmaps.places_nearby(
                        location=location,
                        radius=radius_meters,
                        keyword=search_term,
                        type='establishment'
                    )
                    found_places = places_result.get('results', [])
                    if found_places:
                        break
                except Exception as e:
                    safe_print(f"❌ Search term '{search_term}' failed: {e}")
                    continue
            
            return store_config, found_places[:max_stores_per_type]
        except Exception as e:
            safe_print(f"❌ Store search failed for {store_config.chain}: {e}")
            return store_config, []
    
    # Use ThreadPoolExecutor for parallel processing
    all_stores = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all store searches
        future_to_config = {
            executor.submit(search_single_store, config): config 
            for config in store_configs
        }
        
        # Process results as they complete
        for future in as_completed(future_to_config):
            try:
                store_config, places = future.result()
                if places:
                    safe_print(f"🔍 {store_config.chain}: found {len(places)} places")
                else:
                    continue
                    
                # Process places for this store type
                for place in places:
                    try:
                        place_lat = place['geometry']['location']['lat']
                        place_lng = place['geometry']['location']['lng']
                        distance = calculate_distance(location[0], location[1], place_lat, place_lng)
                        
                        # Skip if too far
                        max_distance_miles = radius_meters / 1609.34
                        if distance > max_distance_miles:
                            continue
                        
                        # Get place details with better address handling
                        place_details = {}
                        try:
                            place_details = gmaps.place(
                                place_id=place['place_id'],
                                fields=['name', 'formatted_address', 'formatted_phone_number', 'rating', 'user_ratings_total', 'opening_hours', 'website', 'price_level']
                            )['result']
                        except Exception as e:
                            safe_print(f"⚠️ Could not get details for {place.get('name', 'Unknown')}: {e}")
                            # Use basic place data as fallback
                            place_details = {
                                'name': place.get('name'),
                                'formatted_address': place.get('vicinity', 'Address not available')
                            }
                        
                        # Construct address (reduced logging)
                        constructed_address = construct_address_from_place(place, place_details)
                        safe_print(f"📍 {place.get('name', 'Unknown')}: {constructed_address}")
                        
                        store_data = {
                            'name': place.get('name', store_config.chain),
                            'address': constructed_address,
                            'lat': place_lat,
                            'lng': place_lng,
                            'distance': distance,
                            'chain': store_config.chain,
                            'category': store_config.category,
                            'icon': store_config.icon,
                            'priority': store_config.priority,
                            'place_id': place['place_id'],
                            'phone': place_details.get('formatted_phone_number'),
                            'rating': place_details.get('rating'),
                            'rating_count': place_details.get('user_ratings_total'),
                            'website': place_details.get('website'),
                            'price_level': place_details.get('price_level'),
                            'is_open': place_details.get('opening_hours', {}).get('open_now', False),
                            'quality_score': calculate_quality_score(place_details, distance),
                            'verified': 'google_places'
                        }
                        
                        all_stores.append(store_data)
                        
                    except Exception as e:
                        safe_print(f"❌ Error processing place: {e}")
                        continue
                        
            except Exception as e:
                safe_print(f"❌ Parallel search error: {e}")
                continue
    
    return all_stores

# Replace the existing search function with optimized version
def search_nearby_stores_enhanced(lat: float, lng: float, radius_meters: int = 12800, 
                                 category: str = None, max_stores_per_type: int = 3) -> List[Dict]:
    """Enhanced store search with parallel processing and caching"""
    
    # Special case: Add Medford Target if user is in Medford area
    medford_target = None
    if 42.40 <= lat <= 42.45 and -71.15 <= lng <= -71.05:
        safe_print(f"🎯 User is in Medford area! Adding Medford Target")
        # Calculate real distance from user's location
        medford_target_lat = 42.4184
        medford_target_lng = -71.1062
        real_distance = calculate_distance(lat, lng, medford_target_lat, medford_target_lng)
        safe_print(f"🎯 Calculated distance to Medford Target: {real_distance:.2f} miles")
        
        medford_target = {
            "name": "Target",
            "address": "471 Salem St, Medford, MA 02155, USA",
            "lat": medford_target_lat,
            "lng": medford_target_lng,
            "distance": real_distance,
            "chain": "Target",
            "category": "Department",
            "icon": "🎯",
            "phone": "(781) 658-3365",
            "rating": 4.5,
            "user_ratings_total": 100,
            "place_id": "medford_target_manual",
            "quality_score": 0.9
        }
    
    # Check cache first
    cached_result = store_cache.get(lat, lng, radius_meters, category)
    if cached_result:
        return cached_result
    
    if not gmaps:
        safe_print("❌ Google Maps API not available")
        return []
    
    try:
        location = (lat, lng)
        store_configs = get_comprehensive_store_database()
        
        # Filter by category if specified
        if category:
            store_configs = [s for s in store_configs if s.category.lower() == category.lower()]
        
        # Use parallel processing for store searches
        all_stores = search_stores_parallel(store_configs, location, radius_meters, max_stores_per_type)
        
        # Add Medford Target if applicable
        if medford_target and medford_target['distance'] <= radius_meters / 1609.34:
            medford_already_exists = any(
                store.get('place_id') == 'medford_target_manual' or 
                (store.get('name') == 'Target' and 'Medford' in store.get('address', ''))
                for store in all_stores
            )
            if not medford_already_exists:
                all_stores.append(medford_target)
                safe_print(f"🎯 Added Medford Target manually (distance: {medford_target['distance']:.2f} miles)")
        
        # If no stores found, add some fallback stores for testing
        if not all_stores:
            safe_print("⚠️ No stores found from API, adding fallback stores with real distances")
            
            # Calculate real distances for fallback stores
            target_lat, target_lng = 42.4184, -71.1062
            bjs_lat, bjs_lng = 42.413148, -71.082149
            bestbuy_lat, bestbuy_lng = 42.403403, -71.06815
            
            target_distance = calculate_distance(lat, lng, target_lat, target_lng)
            bjs_distance = calculate_distance(lat, lng, bjs_lat, bjs_lng)
            bestbuy_distance = calculate_distance(lat, lng, bestbuy_lat, bestbuy_lng)
            
            safe_print(f"📍 Calculated distances - Target: {target_distance:.2f}mi, BJ's: {bjs_distance:.2f}mi, Best Buy: {bestbuy_distance:.2f}mi")
            
            fallback_stores = [
                {
                    "name": "Target",
                    "address": "471 Salem St, Medford, MA 02155, USA",
                    "lat": target_lat,
                    "lng": target_lng,
                    "distance": target_distance,
                    "chain": "Target",
                    "category": "Department",
                    "icon": "🎯",
                    "phone": "(781) 658-3365",
                    "rating": 4.5,
                    "user_ratings_total": 100,
                    "place_id": "medford_target_fallback",
                    "quality_score": 0.9
                },
                {
                    "name": "BJ's Wholesale Club",
                    "address": "278 Middlesex Ave, Medford, MA 02155, USA",
                    "lat": bjs_lat,
                    "lng": bjs_lng,
                    "distance": bjs_distance,
                    "chain": "BJ's Wholesale Club",
                    "category": "Wholesale",
                    "icon": "🛒",
                    "phone": "(781) 396-0235",
                    "rating": 4.0,
                    "user_ratings_total": 478,
                    "place_id": "bjs_medford_fallback",
                    "quality_score": 0.8
                },
                {
                    "name": "Best Buy",
                    "address": "162 Santilli Hwy, Everett, MA 02149, USA",
                    "lat": 42.403403,
                    "lng": -71.06815,
                    "distance": 2.2,
                    "chain": "Best Buy",
                    "category": "Electronics",
                    "icon": "🔌",
                    "phone": "(617) 394-5080",
                    "rating": 4.1,
                    "user_ratings_total": 3337,
                    "place_id": "bestbuy_everett_fallback",
                    "quality_score": 0.85
                }
            ]
            all_stores.extend(fallback_stores)
            safe_print(f"🔄 Added {len(fallback_stores)} fallback stores")
        
        # Filter to only include Target, Walmart, BJ's, and Best Buy
        allowed_stores = ['Target', 'Walmart', 'BJ\'s Wholesale Club', 'Best Buy']
        filtered_stores = []
        for store in all_stores:
            store_name = store.get('name', '')
            if any(allowed in store_name for allowed in allowed_stores):
                filtered_stores.append(store)
        
        all_stores = filtered_stores
        safe_print(f"🔍 Filtered to {len(all_stores)} stores (Target, Walmart, BJ's, Best Buy only)")
        
        # Remove duplicates and sort
        unique_stores = remove_duplicate_stores(all_stores)
        unique_stores.sort(key=lambda x: (x.get('priority', 999), x['distance'], -x.get('quality_score', 0)))
        
        safe_print(f"✅ Found {len(unique_stores)} unique stores (from {len(all_stores)} total)")
        
        # Cache the results (shorter TTL to ensure fresh results)
        cache_ttl = 300 if len(unique_stores) > 0 else 60
        store_cache.set(lat, lng, radius_meters, unique_stores, category, cache_ttl)
        
        return unique_stores
        
    except Exception as e:
        handle_error(e, "Enhanced store search")
        return []

def calculate_quality_score(place_details: Dict, distance: float) -> float:
    """Calculate a quality score for ranking stores"""
    score = 0.0
    
    # Rating contribution (0-5 points)
    rating = place_details.get('rating')
    if rating:
        score += rating
    
    # Review count contribution (0-2 points)
    review_count = place_details.get('user_ratings_total', 0)
    if review_count > 0:
        score += min(2.0, math.log10(review_count))
    
    # Distance penalty (closer = better)
    distance_penalty = distance / 5.0  # Penalty increases with distance
    score -= min(3.0, distance_penalty)
    
    # Has phone number (0.5 points)
    if place_details.get('formatted_phone_number'):
        score += 0.5
    
    # Has website (0.5 points)
    if place_details.get('website'):
        score += 0.5
    
    # Is currently open (1 point)
    opening_hours = place_details.get('opening_hours', {})
    if opening_hours.get('open_now'):
        score += 1.0
    
    return max(0.0, score)

def remove_duplicate_stores(stores: List[Dict]) -> List[Dict]:
    """Remove duplicate stores based on place_id and location proximity"""
    seen_place_ids = set()
    unique_stores = []
    
    for store in stores:
        place_id = store.get('place_id')
        
        if place_id in seen_place_ids:
            continue
        
        # Check for location duplicates (within 100 meters)
        is_duplicate = False
        for existing_store in unique_stores:
            # Handle both 'lat'/'lng' and 'latitude'/'longitude' keys
            existing_lat = existing_store.get('lat') or existing_store.get('latitude')
            existing_lng = existing_store.get('lng') or existing_store.get('longitude')
            current_lat = store.get('lat') or store.get('latitude')
            current_lng = store.get('lng') or store.get('longitude')
            
            if not all([existing_lat, existing_lng, current_lat, current_lng]):
                continue  # Skip if coordinates are missing
                
            distance_meters = calculate_distance(
                current_lat, current_lng, 
                existing_lat, existing_lng
            ) * 1609.34  # Convert miles to meters
            
            if distance_meters < 100:  # Within 100 meters
                # Keep the one with better quality score
                current_quality = store.get('quality_score', 0)
                existing_quality = existing_store.get('quality_score', 0)
                if current_quality <= existing_quality:
                    is_duplicate = True
                    break
                else:
                    # Remove the existing lower-quality store
                    unique_stores.remove(existing_store)
                    break
        
        if not is_duplicate:
            seen_place_ids.add(place_id)
            unique_stores.append(store)
    
    return unique_stores

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance using Haversine formula (returns miles)"""
    try:
        R = 3958.8  # Earth radius in miles
        lat1_rad = math.radians(lat1)
        lng1_rad = math.radians(lng1)
        lat2_rad = math.radians(lat2)
        lng2_rad = math.radians(lng2)
        
        dlat = lat2_rad - lat1_rad
        dlng = lng2_rad - lng1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    except Exception as e:
        handle_error(e, "Distance calculation")
        return 999.0

def save_last_location(user_id: str, lat: float, lng: float, accuracy: float = None):
    """Save user's last known location for quick check-ins"""
    try:
        with db_pool.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO last_locations 
                (user_id, latitude, longitude, accuracy, last_updated)
                VALUES (?, ?, ?, ?, datetime('now'))
            ''', (user_id, lat, lng, accuracy))
            conn.commit()
            safe_print(f"💾 Saved last location for user {user_id}: {lat}, {lng}")
    except Exception as e:
        safe_print(f"❌ Error saving last location: {e}")

def get_last_location(user_id: str) -> Optional[Dict]:
    """Get user's last known location"""
    try:
        with db_pool.get_connection() as conn:
            cursor = conn.execute('''
                SELECT latitude, longitude, accuracy, last_updated, store_preference
                FROM last_locations 
                WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result:
                return {
                    'latitude': result[0],
                    'longitude': result[1],
                    'accuracy': result[2],
                    'last_updated': result[3],
                    'store_preference': result[4]
                }
            return None
    except Exception as e:
        safe_print(f"❌ Error getting last location: {e}")
        return None

async def delete_initial_location_message(user_id: str, channel_id: str):
    """Delete the initial location message after check-in"""
    try:
        user_key = f"{channel_id}_{user_id}"
        if user_key in LOCATION_USER_INFO:
            user_info = LOCATION_USER_INFO[user_key]
            message_id = user_info.get('initial_message_id')
            
            if message_id:
                # Get the channel
                channel = bot.get_channel(int(channel_id))
                if channel:
                    try:
                        # Try to delete the message
                        message = await channel.fetch_message(message_id)
                        await message.delete()
                        safe_print(f"🗑️ Deleted initial message {message_id} for user {user_id}")
                    except discord.NotFound:
                        safe_print(f"⚠️ Message {message_id} not found for user {user_id}")
                    except discord.Forbidden:
                        safe_print(f"⚠️ Cannot delete message {message_id} for user {user_id} - no permissions")
                    except Exception as e:
                        safe_print(f"❌ Error deleting message {message_id}: {e}")
                
                # Clean up user info
                del LOCATION_USER_INFO[user_key]
                safe_print(f"🧹 Cleaned up user info for {user_id}")
            
            # Also try to delete any recent messages from this user in the channel (cleanup duplicates)
            try:
                channel = bot.get_channel(int(channel_id))
                if channel:
                    # Look for recent messages from this user (last 5 minutes) that might be duplicates
                    cutoff_time = discord.utils.utcnow() - timedelta(minutes=5)
                    async for message in channel.history(limit=50, after=cutoff_time):
                        if (message.author.id == bot.user.id and 
                            "Location Sharing" in message.embeds[0].title if message.embeds else False):
                            try:
                                await message.delete()
                                safe_print(f"🗑️ Deleted duplicate location message {message.id}")
                            except:
                                pass  # Ignore errors for cleanup messages
            except Exception as cleanup_error:
                safe_print(f"⚠️ Error during duplicate cleanup: {cleanup_error}")
                
    except Exception as e:
        safe_print(f"❌ Error in delete_initial_location_message: {e}")

def cleanup_old_sessions():
    """Clean up old user sessions to prevent memory buildup"""
    try:
        current_time = discord.utils.utcnow()
        keys_to_remove = []
        
        for user_key, user_info in LOCATION_USER_INFO.items():
            session_age = (current_time - user_info['timestamp']).total_seconds()
            # Remove sessions older than 1 hour
            if session_age > 3600:
                keys_to_remove.append(user_key)
        
        for key in keys_to_remove:
            del LOCATION_USER_INFO[key]
            safe_print(f"🧹 Cleaned up old session: {key}")
        
        if keys_to_remove:
            safe_print(f"🧹 Cleaned up {len(keys_to_remove)} old sessions")
            
        # Clean up stale async locks
        async_lock_keys_to_remove = []
        for user_key in USER_ASYNC_LOCKS.keys():
            # If user has a lock but no session, remove the lock
            if user_key not in LOCATION_USER_INFO:
                async_lock_keys_to_remove.append(user_key)
        
        for key in async_lock_keys_to_remove:
            del USER_ASYNC_LOCKS[key]
            safe_print(f"🔓 Cleaned up stale async lock: {key}")
            
    except Exception as e:
        safe_print(f"❌ Error in cleanup_old_sessions: {e}")

# Enhanced user management
def check_user_permissions(user_id: str, required_role: str = 'user') -> bool:
    """Enhanced permission checking with role hierarchy"""
    try:
        with db_pool.get_connection() as conn:
            cursor = conn.execute(
                'SELECT role, permissions FROM user_permissions WHERE user_id = ?',
                (str(user_id),)
            )
            result = cursor.fetchone()
            
            if not result:
                return required_role == 'user'
            
            user_role = result['role']
            role_hierarchy = {'user': 0, 'moderator': 1, 'admin': 2, 'superadmin': 3}
            
            has_permission = role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)
            
            # Update last used timestamp
            if has_permission:
                conn.execute(
                    'UPDATE user_permissions SET last_used = CURRENT_TIMESTAMP WHERE user_id = ?',
                    (str(user_id),)
                )
            
            return has_permission
            
    except Exception as e:
        handle_error(e, "Permission check")
        return required_role == 'user'

def log_analytics(user_id: str, action: str, data: Dict = None, 
                 request_obj = None, guild_id: str = None, session_id: str = None) -> None:
    """Enhanced analytics logging"""
    try:
        with db_pool.get_connection() as conn:
            conn.execute('''
                INSERT INTO usage_analytics 
                (user_id, guild_id, action, data, ip_address, user_agent, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(user_id) if user_id else None,
                str(guild_id) if guild_id else None,
                action,
                json.dumps(data) if data else None,
                request_obj.remote_addr if request_obj else None,
                request_obj.headers.get('User-Agent') if request_obj else None,
                session_id
            ))
    except Exception as e:
        handle_error(e, "Analytics logging")

# Enhanced background task management
class TaskManager:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=6)
        self.active_tasks = set()
    
    async def add_background_task(self, func, *args, **kwargs):
        """Add a background task"""
        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(self.executor, func, *args, **kwargs)
        self.active_tasks.add(task)
        
        # Clean up completed tasks
        task.add_done_callback(lambda t: self.active_tasks.discard(t))
        
        return task
    
    async def cleanup_old_data(self):
        """Clean up old database records"""
        try:
            cutoff_date = datetime.now() - timedelta(days=90)
            
            with db_pool.get_connection() as conn:
                # Clean old location records
                location_result = conn.execute(
                    'DELETE FROM user_locations WHERE timestamp < ?',
                    (cutoff_date,)
                )
                
                # Clean old analytics (keep longer)
                analytics_cutoff = datetime.now() - timedelta(days=180)
                analytics_result = conn.execute(
                    'DELETE FROM usage_analytics WHERE timestamp < ?',
                    (analytics_cutoff,)
                )
                
                safe_print(f"🧹 Cleanup: {location_result.rowcount} locations, "
                          f"{analytics_result.rowcount} analytics")
                
        except Exception as e:
            handle_error(e, "Data cleanup")

task_manager = TaskManager()

# Global state management
LOCATION_CHANNEL_ID = None
LOCATION_USER_INFO = {}
ACTIVE_SESSIONS = {}
USER_LOCKS = {}  # Prevent duplicate embeds per user
USER_ASYNC_LOCKS = {}  # Async locks for better concurrency control
bot_ready = False
bot_connected = False

# Enhanced bot events
@bot.event
async def on_ready():
    """Enhanced bot startup"""
    global bot_ready, bot_connected
    
    safe_print(f"🤖 Discord bot connected: {bot.user}")
    bot_connected = True
    
    try:
        # Initialize database
        safe_print("🗄️ Initializing enhanced database...")
        init_enhanced_database()
        
        # Initialize Google Maps
        safe_print("🗺️ Initializing Google Maps API...")
        api_available = initialize_google_maps()
        
        # Start background tasks
        safe_print("⚙️ Starting background tasks...")
        cleanup_task.start()
        cache_cleanup_task.start()
        
        # Sync slash commands with rate limit handling
        try:
            safe_print("🔄 Syncing slash commands...")
            synced = await bot.tree.sync()
            safe_print(f"✅ Synced {len(synced)} slash commands")
        except Exception as sync_error:
            safe_print(f"⚠️ Slash command sync failed (rate limited?): {sync_error}")
            # Continue anyway - commands will still work
        
        bot_ready = True
        safe_print("✅ Enhanced Location Bot is ready!")
        
        # Set bot status with delay to avoid rate limiting
        try:
            await asyncio.sleep(2)  # Wait 2 seconds before setting status
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"📍 {len(bot.guilds)} servers • /location"
            )
            await bot.change_presence(activity=activity)
            safe_print("✅ Bot status set successfully")
        except Exception as status_error:
            safe_print(f"⚠️ Failed to set bot status: {status_error}")
        
    except Exception as e:
        handle_error(e, "Bot startup")

@bot.event
async def on_guild_join(guild):
    """Handle new guild joins"""
    safe_print(f"🆕 Joined new guild: {guild.name} ({guild.id})")
    log_analytics(None, "guild_join", {"guild_id": guild.id, "guild_name": guild.name})

@bot.event
async def on_guild_remove(guild):
    """Handle guild removals"""
    safe_print(f"👋 Left guild: {guild.name} ({guild.id})")
    log_analytics(None, "guild_leave", {"guild_id": guild.id, "guild_name": guild.name})

# Background tasks
@tasks.loop(hours=24)
async def cleanup_task():
    """Daily cleanup task"""
    await task_manager.cleanup_old_data()

@tasks.loop(hours=6)
async def cache_cleanup_task():
    """Cache cleanup task"""
    store_cache.clear_expired()
    cleanup_old_sessions()  # Clean up old user sessions

def get_enhanced_store_branding(chain: str, category: str, quality_score: float = 0) -> dict:
    """Enhanced store branding with quality-based colors"""
    
    # Base branding map
    branding_map = {
        "Target": {"emoji": "🎯", "color": 0xCC0000, "description": "Department Store"},
        "Walmart": {"emoji": "🏪", "color": 0x0071CE, "description": "Superstore"},
        "Best Buy": {"emoji": "🔌", "color": 0x003F7F, "description": "Electronics Store"},
        "BJs": {"emoji": "🛒", "color": 0xFF6B35, "description": "Wholesale Club"},
        "Costco": {"emoji": "🏬", "color": 0x004B87, "description": "Warehouse Club"},
        "Home Depot": {"emoji": "🔨", "color": 0xFF6600, "description": "Home Improvement"},
        "Lowes": {"emoji": "🏠", "color": 0x004990, "description": "Home Improvement"},
        "CVS": {"emoji": "💊", "color": 0xCC0000, "description": "Pharmacy"},
        "Walgreens": {"emoji": "⚕️", "color": 0x0089CF, "description": "Pharmacy"},
        "Starbucks": {"emoji": "☕", "color": 0x00704A, "description": "Coffee Shop"},
        "Dunkin": {"emoji": "🍩", "color": 0xFF6600, "description": "Coffee & Donuts"},
        "McDonalds": {"emoji": "🍟", "color": 0xFFCC00, "description": "Fast Food"},
        "Shell": {"emoji": "⛽", "color": 0xFFDE00, "description": "Gas Station"},
        "Mobil": {"emoji": "⛽", "color": 0xFF0000, "description": "Gas Station"},
        "BofA": {"emoji": "🏦", "color": 0x012169, "description": "Bank"},
        "TD Bank": {"emoji": "🏦", "color": 0x00B04F, "description": "Bank"},
        "Chase": {"emoji": "🏦", "color": 0x005DAA, "description": "Bank"}
    }
    
    # Default branding
    default_branding = {
        "emoji": get_category_emoji(category),
        "color": get_category_color(category),
        "description": f"{category} Store" if category else "Store"
    }
    
    # Get base branding
    branding = branding_map.get(chain, default_branding)
    
    # Enhance color based on quality score
    if quality_score >= 8:
        branding["color"] = 0xFFD700  # Gold for exceptional
    elif quality_score >= 6:
        branding["color"] = 0x32CD32  # Green for good
    elif quality_score < 3:
        branding["color"] = 0xFF6B6B  # Red for poor
    
    return branding

def get_category_emoji(category: str) -> str:
    """Get emoji for store category"""
    category_emojis = {
        "Department": "🏬", "Superstore": "🏪", "Electronics": "🔌",
        "Wholesale": "🛒", "Hardware": "🔨", "Pharmacy": "💊",
        "Grocery": "🥬", "Coffee": "☕", "Fast Food": "🍟",
        "Gas": "⛽", "Banking": "🏦", "Auto": "🚗"
    }
    return category_emojis.get(category, "🏢")

def get_category_color(category: str) -> int:
    """Get color for store category"""
    category_colors = {
        "Department": 0x7289DA, "Superstore": 0x5865F2, "Electronics": 0x3498DB,
        "Wholesale": 0x9B59B6, "Hardware": 0xE67E22, "Pharmacy": 0xE74C3C,
        "Grocery": 0x2ECC71, "Coffee": 0x8B4513, "Fast Food": 0xF39C12,
        "Gas": 0xF1C40F, "Banking": 0x34495E, "Auto": 0x95A5A6
    }
    return category_colors.get(category, 0x7289DA)

def format_phone_number(phone: str) -> str:
    """Format phone number for better display"""
    # Remove all non-digit characters
    digits = ''.join(filter(str.isdigit, phone))
    
    # Format US phone numbers
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == '1':
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    else:
        return phone  # Return original if not standard US format

def get_railway_url():
    """Get Railway URL with proper fallback logic"""
    # Try environment variables first
    for env_var in ['RAILWAY_STATIC_URL', 'RAILWAY_PUBLIC_DOMAIN', 'RAILWAY_URL']:
        url = os.getenv(env_var)
        if url and url.startswith('http') and 'your-app' not in url:
            safe_print(f"🔗 Using Railway URL from {env_var}: {url}")
            return url
    
    # If no valid URL found, construct from Railway environment
    project = os.getenv('RAILWAY_PROJECT_ID', '')
    if project:
        constructed_url = f"https://{project}.up.railway.app"
        safe_print(f"🔗 Constructed Railway URL: {constructed_url}")
        return constructed_url
    
    # Try to get from Railway's default environment
    railway_project_name = os.getenv('RAILWAY_PROJECT_NAME', '')
    railway_service_name = os.getenv('RAILWAY_SERVICE_NAME', '')
    if railway_project_name and railway_service_name:
        default_url = f"https://{railway_project_name}-{railway_service_name}.up.railway.app"
        safe_print(f"🔗 Using Railway default URL: {default_url}")
        return default_url
    
    # Last resort fallback - use the working URL
    fallback_url = 'https://web-production-f0220.up.railway.app'
    safe_print(f"🔗 Using fallback Railway URL: {fallback_url}")
    return fallback_url

def construct_address_from_place(place: dict, place_details: dict) -> str:
    """Construct a proper address from available place data"""
    # Try formatted_address from place details first (most reliable)
    if place_details and place_details.get('formatted_address'):
        return place_details['formatted_address']
    
    # Try vicinity from place data (Google Places API)
    if place.get('vicinity'):
        return place['vicinity']
    
    # Try to construct from components
    address_parts = []
    
    # Add street address if available
    if place.get('name'):
        address_parts.append(place['name'])
    
    # Add city/area if available
    if place.get('vicinity'):
        address_parts.append(place['vicinity'])
    
    # If we have any parts, join them
    if address_parts:
        return ', '.join(address_parts)
    
    # Fallback addresses for known chains in the area
    store_name = place.get('name', '').lower()
    if 'target' in store_name:
        return "471 Salem St, Medford, MA 02155, USA"
    elif 'best buy' in store_name:
        return "162 Santilli Hwy, Everett, MA 02149, USA"
    elif 'bj' in store_name or 'wholesale' in store_name:
        return "278 Middlesex Ave, Medford, MA 02155, USA"
    elif 'walmart' in store_name:
        return "1000 Broadway, Everett, MA 02149, USA"
    
    return "Address not available"



# Enhanced bot commands
@bot.tree.command(name="ping", description="Check bot status and performance metrics")
async def ping_command(interaction: discord.Interaction):
    """Enhanced ping command with detailed status"""
    try:
        start_time = time.time()
        
        # Test database
        db_start = time.time()
        with db_pool.get_connection() as conn:
            conn.execute('SELECT 1').fetchone()
        db_time = (time.time() - db_start) * 1000
        
        # Test Google Maps API
        maps_status = "✅ Active" if gmaps else "❌ Not Available"
        weather_status = "✅ Active" if WEATHER_API_KEY else "❌ Not Configured"
        cache_status = "✅ Redis" if store_cache.redis_client else "📝 Memory"
        
        embed = discord.Embed(
            title="🏓 Enhanced Location Bot Status",
            description="Real-time location sharing with comprehensive store coverage",
            color=0x00FF00 if gmaps else 0xFFAA00
        )
        
        # Core systems
        embed.add_field(name="🤖 Discord Bot", value="✅ Connected", inline=True)
        embed.add_field(name="🗺️ Google Maps API", value=maps_status, inline=True)
        embed.add_field(name="🌤️ Weather API", value=weather_status, inline=True)
        
        # Performance metrics
        embed.add_field(name="💾 Cache System", value=cache_status, inline=True)
        embed.add_field(name="🗄️ Database Response", value=f"{db_time:.1f}ms", inline=True)
        embed.add_field(name="📊 Latency", value=f"{bot.latency*1000:.1f}ms", inline=True)
        
        # Statistics
        guild_count = len(bot.guilds)
        user_count = sum(guild.member_count for guild in bot.guilds)
        embed.add_field(name="🏢 Servers", value=f"{guild_count:,}", inline=True)
        embed.add_field(name="👥 Users", value=f"{user_count:,}", inline=True)
        embed.add_field(name="🔍 Store Types", value=f"{len(get_comprehensive_store_database())}", inline=True)
        
        # Features
        features = [
            "🔍 Real-time Google Places search",
            "💾 Advanced caching system", 
            "🌤️ Weather integration",
            "📊 Usage analytics",
            "👥 Group location sharing",
            "⭐ Favorite locations",
            "🎯 Smart store filtering"
        ]
        embed.add_field(name="✨ Features", value="\n".join(features), inline=False)
        
        embed.set_footer(text="Enhanced Location Bot • Powered by Google Places & OpenWeather")
        embed.timestamp = discord.utils.utcnow()
        
        response_time = (time.time() - start_time) * 1000
        embed.description += f"\n\n**Response Time:** {response_time:.1f}ms"
        
        await interaction.response.send_message(embed=embed)
        
        log_analytics(
            interaction.user.id, 
            "ping_command", 
            {"response_time": response_time, "db_time": db_time},
            guild_id=interaction.guild.id if interaction.guild else None
        )
        
    except Exception as e:
        error_id = handle_error(e, "Ping command")
        await interaction.response.send_message(f"❌ Error checking bot status (ID: {error_id})")

@bot.tree.command(name="location", description="Start simple location sharing")
async def location_command(interaction: discord.Interaction):
    """Simple location sharing for store check-ins"""
    global LOCATION_CHANNEL_ID, LOCATION_USER_INFO, USER_ASYNC_LOCKS
    
    # Store interaction details for fallback
    channel = interaction.channel
    user = interaction.user
    user_key = f"{interaction.channel.id}_{interaction.user.id}"
    
    # IMMEDIATE RESPONSE - Defer first to prevent timeout
    try:
        await interaction.response.defer(ephemeral=False)
    except:
        pass  # Continue if already deferred
    
    # Get or create async lock for this user
    if user_key not in USER_ASYNC_LOCKS:
        USER_ASYNC_LOCKS[user_key] = asyncio.Lock()
    
    user_lock = USER_ASYNC_LOCKS[user_key]
    
    # Try to acquire the lock
    if user_lock.locked():
        try:
            await interaction.followup.send(
                "⏳ Please wait, your location session is being set up...",
                ephemeral=True
            )
        except:
            await channel.send(f"{user.mention} ⏳ Please wait, your location session is being set up...")
        return
    
    # Acquire the lock
    async with user_lock:
        try:
            # Double-check if user already has an active session
            if user_key in LOCATION_USER_INFO:
                existing_session = LOCATION_USER_INFO[user_key]
                session_age = (discord.utils.utcnow() - existing_session['timestamp']).total_seconds()
                
                # If session is less than 30 seconds old, don't create a new one
                if session_age < 30:
                    try:
                        await interaction.followup.send(
                            "⏳ You already have an active location session. Please wait a moment or use the existing link.",
                            ephemeral=True
                        )
                    except:
                        await channel.send(f"{user.mention} ⏳ You already have an active location session. Please wait a moment or use the existing link.")
                    return
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            
            # Create embed with placeholder URL
            embed = discord.Embed(
                title="📍 Location Sharing",
                description=f"**{interaction.user.display_name}** wants to share their location",
                color=0x5865F2
            )
            
            embed.add_field(
                name="🔗 Location Portal",
                value="🔄 Loading...",
                inline=False
            )
            
            embed.add_field(
                name="ℹ️ How it works",
                value="1. Click the link above\n2. Allow location access\n3. Select a store to check in\n4. Your check-in will be posted here",
                inline=False
            )
            
            embed.set_footer(text="Location Bot • Simple store check-ins")
            embed.timestamp = discord.utils.utcnow()
            
            # Send initial message
            try:
                message = await interaction.followup.send(embed=embed)
            except:
                message = await channel.send(f"{user.mention}", embed=embed)
            
            # Store user info
            LOCATION_CHANNEL_ID = interaction.channel.id
            LOCATION_USER_INFO[user_key] = {
                'user_id': interaction.user.id,
                'username': interaction.user.display_name,
                'full_username': str(interaction.user),
                'avatar_url': interaction.user.display_avatar.url,
                'timestamp': discord.utils.utcnow(),
                'session_id': session_id,
                'initial_message_id': message.id
            }
            
            safe_print(f"✅ Created location session for user {user_key}")
            
            # Background setup
            async def background_setup():
                try:
                    # Check permissions
                    if not check_user_permissions(interaction.user.id, 'user'):
                        await message.edit(content="❌ You don't have permission to use this command.")
                        return
                    
                    # Get Railway URL - always use the working URL
                    railway_url = 'https://web-production-f0220.up.railway.app'
                    website_url = f"{railway_url}?session={session_id}&user={interaction.user.id}&channel={interaction.channel.id}"
                    
                    safe_print(f"🔗 Generated website URL: {website_url}")
                    
                    # Update embed with real URL
                    embed.set_field_at(0, name="🔗 Location Portal", value=f"[Click here to share your location]({website_url})", inline=False)
                    
                    # Add quick check-in buttons
                    view = discord.ui.View()
                    view.add_item(discord.ui.Button(
                        label="🎯 Quick Target Check-in", 
                        style=discord.ButtonStyle.danger,
                        url=website_url
                    ))
                    view.add_item(discord.ui.Button(
                        label="🏪 Quick Walmart Check-in", 
                        style=discord.ButtonStyle.primary,
                        url=website_url
                    ))
                    view.add_item(discord.ui.Button(
                        label="🛒 Quick BJ's Check-in", 
                        style=discord.ButtonStyle.success,
                        url=website_url
                    ))
                    view.add_item(discord.ui.Button(
                        label="🔌 Quick Best Buy Check-in", 
                        style=discord.ButtonStyle.secondary,
                        url=website_url
                    ))
                    
                    # Update the message
                    await message.edit(embed=embed, view=view)
                    
                    safe_print(f"🔗 Using Railway URL: {railway_url}")
                    
                    # Log analytics
                    log_analytics(
                        interaction.user.id,
                        "location_session_created",
                        {
                            "session_id": session_id,
                            "railway_url": railway_url,
                            "simplified": True
                        },
                        guild_id=interaction.guild.id if interaction.guild else None,
                        session_id=session_id
                    )
                    
                except Exception as bg_error:
                    safe_print(f"❌ Background setup error: {bg_error}")
                    try:
                        await message.edit(content=f"❌ Error setting up location session: {str(bg_error)[:100]}")
                    except:
                        safe_print(f"❌ Could not edit message: {bg_error}")
            
            # Start background task
            asyncio.create_task(background_setup())
            
        except Exception as e:
            error_id = handle_error(e, "Location command")
            error_message = f"❌ Error creating location session (ID: {error_id})"
            
            try:
                await interaction.followup.send(error_message, ephemeral=True)
            except:
                try:
                    await channel.send(f"{user.mention} {error_message}")
                except:
                    safe_print(f"❌ Could not send error message to user: {error_message}")

@bot.tree.command(name="search", description="Search for specific store types near you")
async def search_command(interaction: discord.Interaction, 
                        category: str = None, 
                        radius: int = 10):
    """Enhanced store search command"""
    # Store interaction details for fallback
    channel = interaction.channel
    user = interaction.user
    
    try:
        # Check permissions
        if not check_user_permissions(interaction.user.id, 'user'):
            try:
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            except:
                await channel.send(f"{user.mention} ❌ You don't have permission to use this command.")
            return
        
        if radius < 1 or radius > 50:
            try:
                await interaction.response.send_message("❌ Radius must be between 1 and 50 miles.", ephemeral=True)
            except:
                await channel.send(f"{user.mention} ❌ Radius must be between 1 and 50 miles.")
            return
        
        # Get Railway URL using the new function
        railway_url = get_railway_url()
        
        # Generate search URL
        search_url = f"{railway_url}?user={interaction.user.id}&channel={interaction.channel.id}&category={category or ''}&radius={radius}"
        
        # Check categories
        if category:
            categories = list(set(store.category for store in get_comprehensive_store_database()))
            if category not in categories:
                embed = discord.Embed(
                    title="📂 Available Store Categories",
                    description="Choose from these categories:",
                    color=0x5865F2
                )
                
                category_list = ", ".join(f"`{cat}`" for cat in sorted(categories))
                embed.add_field(name="Categories", value=category_list, inline=False)
                
                try:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                except:
                    await channel.send(f"{user.mention}", embed=embed)
                return
        
        # Create embed
        embed = discord.Embed(
            title="🔍 Enhanced Store Search",
            description=f"Use the location portal to search for {category or 'all'} stores within {radius} miles",
            color=0x5865F2
        )
        
        embed.add_field(
            name="🔗 Search Portal",
            value=f"[Click here to search stores]({search_url})",
            inline=False
        )
        
        # Add category info to embed
        if category:
            stores_in_category = [s for s in get_comprehensive_store_database() if s.category == category]
            store_names = ", ".join(s.chain for s in stores_in_category[:10])
            if len(stores_in_category) > 10:
                store_names += f" and {len(stores_in_category) - 10} more"
            
            embed.add_field(
                name=f"🏪 {category} Stores",
                value=store_names,
                inline=False
            )
        
        embed.set_footer(text="Enhanced Store Search • Real-time Google Places Data")
        
        # Try to respond to interaction first
        try:
            await interaction.response.send_message(embed=embed)
        except Exception as interaction_error:
            # If interaction fails, send as regular channel message
            safe_print(f"⚠️ Interaction failed, sending channel message: {interaction_error}")
            await channel.send(f"{user.mention}", embed=embed)
        
    except Exception as e:
        error_id = handle_error(e, "Search command")
        error_message = f"❌ Error with search command (ID: {error_id})"
        
        # Try multiple ways to send error message
        try:
            await interaction.response.send_message(error_message, ephemeral=True)
        except:
            try:
                await channel.send(f"{user.mention} {error_message}")
            except:
                safe_print(f"❌ Could not send error message to user: {error_message}")

@bot.tree.command(name="favorites", description="Manage your favorite locations")
async def favorites_command(interaction: discord.Interaction, 
                           action: str = "list",
                           name: str = None):
    """Manage favorite locations"""
    try:
        if not check_user_permissions(interaction.user.id, 'user'):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)
        
        with db_pool.get_connection() as conn:
            if action == "list":
                cursor = conn.execute('''
                    SELECT name, address, category, visit_count, created_at
                    FROM favorite_locations 
                    WHERE user_id = ? 
                    ORDER BY visit_count DESC, created_at DESC
                    LIMIT 20
                ''', (user_id,))
                
                favorites = cursor.fetchall()
                
                if not favorites:
                    embed = discord.Embed(
                        title="⭐ Your Favorite Locations",
                        description="You haven't saved any favorite locations yet!\nUse the location portal to save places you visit frequently.",
                        color=0x5865F2
                    )
                else:
                    embed = discord.Embed(
                        title="⭐ Your Favorite Locations",
                        description=f"You have {len(favorites)} saved locations:",
                        color=0x5865F2
                    )
                    
                    for fav in favorites[:10]:  # Show top 10
                        visit_text = f"Visited {fav['visit_count']} times" if fav['visit_count'] > 0 else "Never visited"
                        embed.add_field(
                            name=f"{fav['name']} ({fav['category']})",
                            value=f"{fav['address']}\n*{visit_text}*",
                            inline=False
                        )
                
                embed.set_footer(text="Use the location portal to add new favorites")
                
            elif action == "clear":
                result = conn.execute('DELETE FROM favorite_locations WHERE user_id = ?', (user_id,))
                embed = discord.Embed(
                    title="🗑️ Favorites Cleared",
                    description=f"Removed {result.rowcount} favorite locations.",
                    color=0xFF6B6B
                )
                
            else:
                embed = discord.Embed(
                    title="❌ Invalid Action",
                    description="Available actions: `list`, `clear`",
                    color=0xFF6B6B
                )
        
        await interaction.response.send_message(embed=embed)
        
        log_analytics(
            interaction.user.id,
            f"favorites_{action}",
            {"action": action, "name": name},
            guild_id=interaction.guild.id if interaction.guild else None
        )
        
    except Exception as e:
        error_id = handle_error(e, "Favorites command")
        await interaction.response.send_message(f"❌ Error managing favorites (ID: {error_id})")

@bot.tree.command(name="stats", description="View location and usage statistics")
async def stats_command(interaction: discord.Interaction, 
                       scope: str = "personal"):
    """Enhanced statistics command"""
    try:
        user_id = str(interaction.user.id)
        is_admin = check_user_permissions(user_id, 'admin')
        
        if scope == "server" and not is_admin:
            await interaction.response.send_message("❌ Admin permissions required for server stats.", ephemeral=True)
            return
        
        with db_pool.get_connection() as conn:
            if scope == "personal":
                # Personal statistics
                location_count = conn.execute(
                    'SELECT COUNT(*) as count FROM user_locations WHERE user_id = ?',
                    (user_id,)
                ).fetchone()['count']
                
                favorites_count = conn.execute(
                    'SELECT COUNT(*) as count FROM favorite_locations WHERE user_id = ?',
                    (user_id,)
                ).fetchone()['count']
                
                # Most visited category
                top_category = conn.execute('''
                    SELECT store_category, COUNT(*) as visits
                    FROM user_locations 
                    WHERE user_id = ? AND store_category IS NOT NULL
                    GROUP BY store_category
                    ORDER BY visits DESC
                    LIMIT 1
                ''', (user_id,)).fetchone()
                
                # Recent activity
                recent_activity = conn.execute('''
                    SELECT COUNT(*) as count
                    FROM user_locations 
                    WHERE user_id = ? AND timestamp > datetime('now', '-7 days')
                ''', (user_id,)).fetchone()['count']
                
                embed = discord.Embed(
                    title="📊 Your Location Statistics",
                    description=f"Statistics for {interaction.user.display_name}",
                    color=0x5865F2
                )
                
                embed.add_field(name="📍 Total Check-ins", value=f"{location_count:,}", inline=True)
                embed.add_field(name="⭐ Favorite Locations", value=f"{favorites_count:,}", inline=True)
                embed.add_field(name="📅 This Week", value=f"{recent_activity:,}", inline=True)
                
                if top_category:
                    embed.add_field(
                        name="🏆 Favorite Category",
                        value=f"{top_category['store_category']} ({top_category['visits']} visits)",
                        inline=False
                    )
                
            elif scope == "server" and is_admin:
                # Server statistics
                guild_id = str(interaction.guild.id) if interaction.guild else None
                
                total_users = conn.execute('''
                    SELECT COUNT(DISTINCT user_id) as count
                    FROM user_locations 
                    WHERE guild_id = ?
                ''', (guild_id,)).fetchone()['count']
                
                total_locations = conn.execute('''
                    SELECT COUNT(*) as count
                    FROM user_locations 
                    WHERE guild_id = ?
                ''', (guild_id,)).fetchone()['count']
                
                # Popular categories
                popular_categories = conn.execute('''
                    SELECT store_category, COUNT(*) as visits
                    FROM user_locations 
                    WHERE guild_id = ? AND store_category IS NOT NULL
                    GROUP BY store_category
                    ORDER BY visits DESC
                    LIMIT 5
                ''', (guild_id,)).fetchall()
                
                embed = discord.Embed(
                    title="📊 Server Location Statistics",
                    description=f"Statistics for {interaction.guild.name}",
                    color=0x5865F2
                )
                
                embed.add_field(name="👥 Active Users", value=f"{total_users:,}", inline=True)
                embed.add_field(name="📍 Total Check-ins", value=f"{total_locations:,}", inline=True)
                
                if popular_categories:
                    category_list = "\n".join([
                        f"{i+1}. {cat['store_category']}: {cat['visits']:,} visits"
                        for i, cat in enumerate(popular_categories)
                    ])
                    embed.add_field(name="🏆 Popular Categories", value=category_list, inline=False)
        
        embed.set_footer(text="Enhanced Location Bot Statistics")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
        log_analytics(
            interaction.user.id,
            "stats_viewed",
            {"scope": scope},
            guild_id=interaction.guild.id if interaction.guild else None
        )
        
    except Exception as e:
        error_id = handle_error(e, "Stats command")
        await interaction.response.send_message(f"❌ Error retrieving statistics (ID: {error_id})")

@bot.tree.command(name="setperm", description="Set user permissions (Admin only)")
async def setperm_command(interaction: discord.Interaction, 
                         user: discord.Member, 
                         role: str):
    """Enhanced permission management"""
    try:
        if not check_user_permissions(interaction.user.id, 'admin'):
            await interaction.response.send_message("❌ You need admin permissions to use this command.", ephemeral=True)
            return
        
        valid_roles = ['user', 'moderator', 'admin']
        if role not in valid_roles:
            await interaction.response.send_message(f"❌ Invalid role. Use: {', '.join(valid_roles)}", ephemeral=True)
            return
        
        with db_pool.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_permissions 
                (user_id, role, server_id, granted_by)
                VALUES (?, ?, ?, ?)
            ''', (str(user.id), role, str(interaction.guild.id), str(interaction.user.id)))
        
        embed = discord.Embed(
            title="✅ Permissions Updated",
            description=f"Set {user.display_name} role to **{role}**",
            color=0x00FF00
        )
        
        await interaction.response.send_message(embed=embed)
        
        log_analytics(
            interaction.user.id,
            "permission_granted",
            {
                "target_user": str(user.id),
                "role": role,
                "target_username": user.display_name
            },
            guild_id=interaction.guild.id
        )
        
    except Exception as e:
        error_id = handle_error(e, "Setperm command")
        await interaction.response.send_message(f"❌ Error setting permissions (ID: {error_id})")

@bot.tree.command(name="url", description="Show the current Railway URL being used")
async def url_command(interaction: discord.Interaction):
    """Show the current Railway URL"""
    try:
        # Get Railway URL from environment or use a fallback
        railway_url = os.getenv('RAILWAY_URL')
        if not railway_url:
            # Try to get from Railway's environment
            railway_url = os.getenv('RAILWAY_STATIC_URL') or os.getenv('PORT') or 'https://web-production-f0220.up.railway.app'
            if railway_url and not railway_url.startswith('http'):
                railway_url = f"https://web-production-f0220.up.railway.app"
        
        # If still no URL, try to construct from Railway's environment
        if not railway_url or 'your-app' in railway_url:
            # Try to get the actual Railway URL from environment
            railway_project_name = os.getenv('RAILWAY_PROJECT_NAME', 'web-production')
            railway_service_name = os.getenv('RAILWAY_SERVICE_NAME', 'f0220')
            railway_url = f"https://{railway_project_name}-{railway_service_name}.up.railway.app"
        
        embed = discord.Embed(
            title="🔗 Railway URL Info",
            description="Current Railway URL being used by the bot",
            color=0x5865F2
        )
        
        embed.add_field(
            name="Current URL",
            value=f"`{railway_url}`",
            inline=False
        )
        
        embed.add_field(
            name="Test Links",
            value=f"[Test Page]({railway_url}/test) • [Debug Page]({railway_url}/debug) • [Health Check]({railway_url}/health)",
            inline=False
        )
        
        embed.set_footer(text="Location Bot • URL Debug")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        error_id = handle_error(e, "URL command")
        await interaction.response.send_message(f"❌ Error getting URL info (ID: {error_id})", ephemeral=True)

@bot.tree.command(name="quick", description="Quick check-in using your last known location")
async def quick_command(interaction: discord.Interaction):
    """Quick check-in using last known location for super-fast check-ins"""
    try:
        # Check permissions
        if not check_user_permissions(interaction.user.id, 'user'):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        # Get last known location
        last_location = get_last_location(str(interaction.user.id))
        
        if not last_location:
            await interaction.response.send_message(
                "❌ No previous location found. Please use `/location` first to share your location.",
                ephemeral=True
            )
            return
        
        # Check if location is recent (within 24 hours)
        last_updated = datetime.fromisoformat(last_location['last_updated'].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) - last_updated > timedelta(hours=24):
            await interaction.response.send_message(
                "⚠️ Your last location is over 24 hours old. Please use `/location` to update your location.",
                ephemeral=True
            )
            return
        
        # Search for stores near last location
        stores = search_nearby_stores_enhanced(
            last_location['latitude'], 
            last_location['longitude'], 
            12800,  # 8 miles
            None, 
            2
        )
        
        if not stores:
            await interaction.response.send_message(
                "❌ No stores found near your last location. Please use `/location` to update your location.",
                ephemeral=True
            )
            return
        
        # Create quick check-in embed
        embed = discord.Embed(
            title="⚡ Quick Check-in Available",
            description=f"**{interaction.user.display_name}** can check in using their last known location",
            color=0x00FF00
        )
        
        # Show available stores
        store_list = ""
        for i, store in enumerate(stores[:4], 1):  # Show top 4 stores
            distance = store.get('distance', 0)
            store_list += f"{i}. **{store['name']}** - {distance:.1f} miles\n"
            store_list += f"   📍 {store.get('address', 'Address not available')}\n\n"
        
        embed.add_field(name="🏪 Available Stores", value=store_list, inline=False)
        embed.add_field(
            name="📍 Last Location", 
            value=f"Lat: {last_location['latitude']:.4f}, Lng: {last_location['longitude']:.4f}\nUpdated: {last_updated.strftime('%Y-%m-%d %H:%M')}",
            inline=False
        )
        
        embed.add_field(
            name="⚡ Quick Actions",
            value="Use `/location` to update your location or check in to a specific store",
            inline=False
        )
        
        embed.set_footer(text="Location Bot • Quick Check-in")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
        # Log analytics
        log_analytics(
            interaction.user.id,
            "quick_checkin_attempted",
            {
                "last_location_age_hours": (datetime.now(timezone.utc) - last_updated).total_seconds() / 3600,
                "stores_found": len(stores)
            },
            guild_id=interaction.guild.id if interaction.guild else None
        )
        
    except Exception as e:
        error_id = handle_error(e, "Quick command")
        await interaction.response.send_message(f"❌ Error with quick check-in (ID: {error_id})", ephemeral=True)

# Enhanced Flask routes
@app.route('/', methods=['GET'])
def enhanced_index():
    """Serve enhanced location sharing interface"""
    session_id = request.args.get('session')
    user_id = request.args.get('user')
    channel_id = request.args.get('channel')
    category = request.args.get('category', '')
    radius = request.args.get('radius', '10')
    
    user_info_js = json.dumps({
        'session_id': session_id,
        'user_id': user_id,
        'channel_id': channel_id,
        'category': category,
        'radius': int(radius),
        'google_maps_available': gmaps is not None
    }) if user_id and channel_id else 'null'
    
    google_api_key = os.getenv('GOOGLE_MAPS_API_KEY', '')
    
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Location Bot Portal</title>
    <meta name="theme-color" content="#5865F2">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📍</text></svg>">
    
    <style>
        :root {{
            --primary-blue: #4285F4;
            --primary-green: #34A853;
            --accent-red: #EA4335;
            --accent-yellow: #FBBC04;
            --dark-bg: #1a1a2e;
            --dark-secondary: #16213e;
            --glass-bg: rgba(255, 255, 255, 0.1);
            --glass-border: rgba(255, 255, 255, 0.2);
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, var(--primary-blue) 0%, var(--primary-green) 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            transition: all 0.3s ease;
        }}
        
        body.dark-mode {{
            background: linear-gradient(135deg, var(--dark-bg) 0%, var(--dark-secondary) 100%);
        }}
        
        .theme-toggle {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 50%;
            width: 50px;
            height: 50px;
            color: white;
            font-size: 20px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
            z-index: 1000;
        }}
        
        .theme-toggle:hover {{
            transform: scale(1.1);
            background: var(--glass-border);
        }}
        
        .container {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(30px);
            border-radius: 24px;
            padding: 40px;
            max-width: 800px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.1);
            text-align: center;
            transition: all 0.3s ease;
        }}
        
        .dark-mode .container {{
            background: rgba(30, 30, 30, 0.95);
            color: white;
        }}
        
        .logo {{ 
            font-size: 60px; 
            margin-bottom: 20px; 
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
        }}
        
        h1 {{ 
            color: #2d3748; 
            font-size: 32px; 
            font-weight: 700; 
            margin-bottom: 10px;
            background: linear-gradient(135deg, var(--primary-blue), var(--primary-green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .dark-mode h1 {{
            color: white;
            -webkit-text-fill-color: white;
        }}
        
        .subtitle {{ 
            color: #718096; 
            font-size: 18px; 
            margin-bottom: 30px; 
        }}
        
        .dark-mode .subtitle {{
            color: #a0aec0;
        }}
        
        .enhanced-badge {{
            background: linear-gradient(135deg, var(--primary-green), #0F9D58);
            color: white;
            padding: 15px 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-size: 16px;
            font-weight: 600;
            box-shadow: 0 8px 25px rgba(52, 168, 83, 0.3);
        }}
        
        .features-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        
        .feature-card {{
            background: var(--glass-bg);
            backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            padding: 20px;
            transition: all 0.3s ease;
        }}
        
        .feature-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
        }}
        
        .dark-mode .feature-card {{
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.1);
        }}
        
        .action-buttons {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            justify-content: center;
            margin: 30px 0;
        }}
        
        .btn {{
            background: linear-gradient(135deg, var(--primary-blue) 0%, var(--primary-green) 100%);
            color: white;
            border: none;
            padding: 16px 32px;
            border-radius: 16px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 25px rgba(66, 133, 244, 0.3);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 35px rgba(66, 133, 244, 0.4);
        }}
        
        .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        
        .btn-secondary {{
            background: linear-gradient(135deg, #6c757d, #495057);
        }}
        
        #map {{ 
            height: 400px; 
            width: 100%; 
            border-radius: 16px; 
            margin: 25px 0; 
            display: none;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
        }}
        
        .status {{
            margin: 25px 0;
            padding: 20px;
            border-radius: 16px;
            font-weight: 600;
            display: none;
            backdrop-filter: blur(10px);
        }}
        
        .status.success {{ 
            background: linear-gradient(135deg, var(--primary-green), #0F9D58); 
            color: white; 
        }}
        
        .status.error {{ 
            background: linear-gradient(135deg, var(--accent-red), #D33B2C); 
            color: white; 
        }}
        
        .status.info {{ 
            background: linear-gradient(135deg, var(--primary-blue), #3367D6); 
            color: white; 
        }}
        

        
        .nearby-stores {{ 
            margin-top: 30px; 
            text-align: left; 
            display: none; 
            max-height: 800px; 
            overflow-y: auto;
        }}
        
        .store-category {{
            margin-bottom: 25px;
        }}
        
        .category-header {{
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 15px;
            padding: 10px 15px;
            background: var(--glass-bg);
            border-radius: 12px;
            backdrop-filter: blur(10px);
        }}
        
        .store-item {{
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 15px;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }}
        
        .dark-mode .store-item {{
            background: rgba(40, 40, 40, 0.95);
            border-color: rgba(255, 255, 255, 0.1);
            color: white;
        }}
        
        .store-item:hover {{
            transform: translateY(-3px);
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.15);
        }}
        
        .store-item.google-verified {{
            border-left: 4px solid var(--primary-green);
        }}
        
        .store-item.high-rated {{
            border-left: 4px solid var(--accent-yellow);
        }}
        
        .store-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 10px;
        }}
        
        .store-name {{
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .store-details {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-top: 10px;
            font-size: 14px;
            opacity: 0.8;
        }}
        
        .store-badge {{
            background: var(--glass-bg);
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
        }}
        

        
        .loading-spinner {{
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,.3);
            border-radius: 50%;
            border-top-color: #fff;
            animation: spin 1s ease-in-out infinite;
        }}
        
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        
        .footer-info {{
            margin-top: 40px;
            color: #a0aec0;
            font-size: 14px;
            line-height: 1.6;
        }}
        
        .dark-mode .footer-info {{
            color: #718096;
        }}
        
        @media (max-width: 768px) {{
            .container {{ padding: 30px 20px; }}
            h1 {{ font-size: 28px; }}
            .action-buttons {{ flex-direction: column; }}
            .btn {{ width: 100%; }}
            .features-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <button class="theme-toggle" onclick="toggleTheme()" title="Toggle Dark Mode">
        🌙
    </button>
    
    <div class="container">
        <div class="logo">📍</div>
        <h1>Location Portal</h1>
        <p class="subtitle">Simple store check-ins for Discord</p>
        
        <div class="enhanced-badge">
            📍 Simple store check-ins with real-time location
        </div>
        
        <div class="features-grid">
            <div class="feature-card">
                <div style="font-size: 24px; margin-bottom: 10px;">📍</div>
                <h3>Real-time Location</h3>
                <p>Get your current location instantly</p>
            </div>
            <div class="feature-card">
                <div style="font-size: 24px; margin-bottom: 10px;">🏪</div>
                <h3>Store Check-ins</h3>
                <p>Find and check in to nearby stores</p>
            </div>
            <div class="feature-card">
                <div style="font-size: 24px; margin-bottom: 10px;">📱</div>
                <h3>Simple & Fast</h3>
                <p>Quick and easy check-in process</p>
            </div>
            <div class="feature-card">
                <div style="font-size: 24px; margin-bottom: 10px;">💬</div>
                <h3>Discord Integration</h3>
                <p>Posts directly to your Discord channel</p>
            </div>
        </div>
        
        <div class="action-buttons">
            <button id="shareLocationBtn" class="btn">
                📍 Share Location
            </button>
        </div>
        

        
        <div id="map"></div>
        <div id="status" class="status"></div>
        

        
        <div id="nearbyStores" class="nearby-stores"></div>
        
        <div class="footer-info">
            <p><strong>Simple & Fast:</strong></p>
            <p>📍 Real-time location sharing</p>
            <p>🏪 Quick store check-ins</p>
            <p>💬 Direct Discord integration</p>
            <p>📱 Mobile-friendly interface</p>
        </div>
    </div>

    <script>
        const USER_INFO = {user_info_js};
        const GOOGLE_API_KEY = '{google_api_key}';
        
        let map, userMarker, storeMarkers = [], userLocation = null, nearbyStores = [], favoriteLocations = [], currentWeather = null, isDarkMode = false;
        
        function initializeApp() {{
            loadGoogleMapsAPI();
            setupEventListeners();
            checkDarkModePreference();
            if (USER_INFO) {{
                showStatus('✅ Connected to Discord bot', 'success');
                setTimeout(() => hideStatus(), 3000);
            }}
        }}
        
        function setupEventListeners() {{
            document.getElementById('shareLocationBtn').addEventListener('click', shareLocation);
        }}
        
        function checkDarkModePreference() {{
            const savedTheme = localStorage.getItem('enhanced-location-bot-theme');
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            if (savedTheme === 'dark' || (!savedTheme && prefersDark)) enableDarkMode();
        }}
        
        function toggleTheme() {{
            isDarkMode ? disableDarkMode() : enableDarkMode();
        }}
        
        function enableDarkMode() {{
            document.body.classList.add('dark-mode');
            document.querySelector('.theme-toggle').textContent = '☀️';
            localStorage.setItem('enhanced-location-bot-theme', 'dark');
            isDarkMode = true;
        }}
        
        function disableDarkMode() {{
            document.body.classList.remove('dark-mode');
            document.querySelector('.theme-toggle').textContent = '🌙';
            localStorage.setItem('enhanced-location-bot-theme', 'light');
            isDarkMode = false;
        }}
        
        function loadGoogleMapsAPI() {{
            // Skip Google Maps entirely - use simplified mode
            console.log('Using simplified mode without Google Maps');
            initializeSimplifiedMode();
        }}
        
        function initializeSimplifiedMode() {{
            console.log('Initializing simplified mode');
            const mapContainer = document.getElementById('map');
            if (mapContainer) {{
                mapContainer.innerHTML = `
                    <div style="text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 12px; margin: 20px 0;">
                        <div style="font-size: 48px; margin-bottom: 16px;">📍</div>
                        <h3>Fast Store Check-ins</h3>
                        <p>Click "Update Location" to find nearby stores and check in quickly!</p>
                        <p>No map required - just location and store selection.</p>
                    </div>
                `;
            }}
            showStatus('✅ Ready for fast check-ins', 'success');
            setTimeout(() => hideStatus(), 3000);
        }}
        
        function initializeMap() {{
            // This function is not used in simplified mode
            console.log('Map initialization skipped in simplified mode');
        }}
        
        async function shareLocation() {{
            const button = document.getElementById('shareLocationBtn');
            if (!navigator.geolocation) {{ showStatus('❌ Geolocation not supported', 'error'); return; }}
            
            button.disabled = true;
            button.innerHTML = '<span class="loading-spinner"></span> Getting location...';
            showStatus('📍 Requesting location access...', 'info');
            
            try {{
                const position = await getCurrentPosition({{ enableHighAccuracy: true, timeout: 30000, maximumAge: 60000 }});
                const {{ latitude, longitude }} = position.coords;
                userLocation = {{ lat: latitude, lng: longitude }};
                
                console.log('GPS Location obtained:', {{ lat: latitude, lng: longitude }});
                console.log('Location accuracy:', position.coords.accuracy, 'meters');
                console.log('Location URL:', `https://www.google.com/maps?q=${{latitude}},${{longitude}}`);
                
                showUserLocation(latitude, longitude);
                await searchNearbyStores(latitude, longitude);
                
                button.innerHTML = '✅ Location Shared!';
                showStatus('✅ Location shared successfully!', 'success');
                setTimeout(() => {{ button.disabled = false; button.innerHTML = '📍 Update Location'; }}, 3000);
            }} catch (error) {{
                console.error('Geolocation error:', error);
                let errorMessage = '❌ Failed to get location. ';
                switch (error.code) {{
                    case error.PERMISSION_DENIED: errorMessage += 'Please allow location access.'; break;
                    case error.POSITION_UNAVAILABLE: errorMessage += 'Location information unavailable.'; break;
                    case error.TIMEOUT: errorMessage += 'Location request timed out.'; break;
                    default: errorMessage += 'Unknown error occurred.'; break;
                }}
                showStatus(errorMessage, 'error');
                button.disabled = false; button.innerHTML = '📍 Try Again';
            }}
        }}
        
        function getCurrentPosition(options) {{
            return new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, options));
        }}
        
        function showUserLocation(lat, lng) {{
            userLocation = {{ lat, lng }};
            console.log('Location captured:', userLocation);
            
            // Update the map container to show location confirmation
            const mapContainer = document.getElementById('map');
            if (mapContainer) {{
                mapContainer.innerHTML = `
                    <div style="text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 12px; margin: 20px 0;">
                        <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                        <h3>Location Captured!</h3>
                        <p>Latitude: ${{lat.toFixed(6)}}</p>
                        <p>Longitude: ${{lng.toFixed(6)}}</p>
                        <p><a href="https://www.google.com/maps?q=${{lat}},${{lng}}" target="_blank" style="color: #007bff;">📍 Verify Location on Google Maps</a></p>
                        <p>Searching for nearby stores...</p>
                        <button onclick="retryLocation()" style="margin-top: 10px; padding: 8px 16px; background: var(--primary-blue); color: white; border: none; border-radius: 8px; cursor: pointer;">Retry Location</button>
                    </div>
                `;
            }}
        }}
        
        function retryLocation() {{
            shareLocation();
        }}
        

        
        async function searchNearbyStores(lat, lng) {{
            showStatus('🔍 Searching for nearby stores...', 'info');
            try {{
                const requestData = {{ latitude: lat, longitude: lng, radius: 5, user_id: USER_INFO?.user_id }};
                console.log('Searching stores with data:', requestData);
                const response = await fetch('/api/search-stores', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(requestData) }});
                if (!response.ok) throw new Error(`Search failed: ${{response.status}}`);
                
                const data = await response.json();
                console.log('Store search response:', data);
                console.log('Number of stores found:', data.stores ? data.stores.length : 0);
                nearbyStores = data.stores || [];
                showStatus(`✅ Found ${{nearbyStores.length}} stores nearby`, 'success');
                displayStoresList();
                setTimeout(() => hideStatus(), 3000);
            }} catch (error) {{
                console.error('Store search error:', error);
                showStatus('❌ Failed to search for stores: ' + error.message, 'error');
            }}
        }}
        
        function displayStoresList() {{
            const storesContainer = document.getElementById('nearbyStores');
            console.log('Displaying stores list. Container found:', !!storesContainer);
            console.log('Number of stores to display:', nearbyStores.length);
            
            if (!storesContainer) {{
                console.error('Stores container not found!');
                return;
            }}
            
            if (nearbyStores.length === 0) {{
                console.log('No stores found, showing empty message');
                storesContainer.innerHTML = '<div style="text-align: center; padding: 40px; opacity: 0.6;"><div style="font-size: 48px; margin-bottom: 16px;">🔍</div><p>No stores found nearby.</p></div>';
                storesContainer.style.display = 'block';
                return;
            }}
            
            const storesByCategory = groupStoresByCategory(nearbyStores);
            console.log('Categories found:', Object.keys(storesByCategory));
            console.log('Total stores:', nearbyStores.length);
            
            let storesHTML = '';
            let categoryCount = 0;
            
            Object.entries(storesByCategory).forEach(([category, stores]) => {{
                if (stores.length === 0) return;
                categoryCount++;
                console.log(`Displaying category: ${{category}} with ${{stores.length}} stores`);
                storesHTML += `
                    <div class="store-category">
                        <div class="category-header">${{getCategoryIcon(category)}} ${{category}} (${{stores.length}})</div>
                        ${{stores.slice(0, 8).map(store => createStoreItemHTML(store)).join('')}}
                    </div>
                `;
            }});
            
            console.log(`Total categories displayed: ${{categoryCount}}`);
            storesContainer.innerHTML = storesHTML;
            storesContainer.style.display = 'block';
        }}
        
        function groupStoresByCategory(stores) {{
            const grouped = {{}};
            stores.forEach(store => {{
                const category = store.category || 'Other';
                if (!grouped[category]) grouped[category] = [];
                grouped[category].push(store);
            }});
            return grouped;
        }}
        
        function createStoreItemHTML(store) {{
            const distance = store.distance.toFixed(1);
            
            return `
                <div class="store-item google-verified" onclick="selectStore('${{store.place_id}}')">
                    <div class="store-header">
                        <div style="flex: 1;">
                            <div class="store-name">${{store.icon}} ${{store.name}}</div>
                            <div style="color: #666; font-size: 14px; margin: 4px 0;">${{store.address}}</div>
                            <div class="store-details">
                                <span class="store-badge">📏 ${{distance}} mi</span>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 18px; font-weight: bold; color: var(--primary-blue);">${{distance}} mi</div>
                        </div>
                    </div>
                </div>
            `;
        }}
        
        function getCategoryIcon(category) {{
            const icons = {{ 'Department': '🏬', 'Superstore': '🏪', 'Electronics': '🔌', 'Wholesale': '🛒', 'Hardware': '🔨', 'Pharmacy': '💊', 'Grocery': '🥬', 'Coffee': '☕', 'Fast Food': '🍟', 'Gas': '⛽', 'Banking': '🏦', 'Auto': '🚗' }};
            return icons[category] || '🏢';
        }}
        
        async function selectStore(storeId) {{
            const store = nearbyStores.find(s => s.place_id === storeId);
            if (!store || !userLocation) {{ showStatus('❌ Store or location not found', 'error'); return; }}
            
            showStatus(`📍 Checking in to ${{store.name}}...`, 'info');
            try {{
                const checkInData = {{ 
                    latitude: userLocation.lat, 
                    longitude: userLocation.lng, 
                    accuracy: 10, 
                    isManualCheckIn: true, 
                    selectedStore: store, 
                    user_id: USER_INFO?.user_id,
                    session_id: USER_INFO?.session_id,
                    channel_id: USER_INFO?.channel_id
                }};
                console.log('Sending check-in data:', checkInData);
                const response = await fetch('/webhook/location', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(checkInData) }});
                const responseData = await response.json();
                console.log('Check-in response:', responseData);
                if (response.ok) {{
                    showStatus(`✅ Checked in to ${{store.name}}! Posted to Discord.`, 'success');
                    // Hide the store list after successful check-in
                    const storesContainer = document.getElementById('nearbyStores');
                    if (storesContainer) {{
                        storesContainer.innerHTML = `
                            <div style="text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 12px; margin: 20px 0;">
                                <div style="font-size: 48px; margin-bottom: 16px;">✅</div>
                                <h3>Check-in Complete!</h3>
                                <p>Successfully checked in to ${{store.name}}</p>
                                <p>Your check-in has been posted to Discord.</p>
                            </div>
                        `;
                    }}
                }} else {{
                    showStatus(`❌ Failed to check in: ${{responseData.error || 'Unknown error'}}`, 'error');
                }}
            }} catch (error) {{
                console.error('Check-in error:', error);
                showStatus('❌ Check-in failed: ' + error.message, 'error');
            }}
        }}
        
        async function searchStores() {{
            if (!userLocation) {{ showStatus('📍 Please share your location first', 'info'); return; }}
            await searchNearbyStores(userLocation.lat, userLocation.lng);
        }}
        
        function showStatus(message, type) {{
            const statusDiv = document.getElementById('status');
            if (!statusDiv) return;
            statusDiv.textContent = message; statusDiv.className = `status ${{type}}`;
            statusDiv.style.display = 'block';
            if (type === 'success' || type === 'info') setTimeout(() => hideStatus(), 5000);
        }}
        
        function hideStatus() {{
            const statusDiv = document.getElementById('status');
            if (statusDiv) statusDiv.style.display = 'none';
        }}
        
        window.initializeMap = initializeMap;
        document.addEventListener('DOMContentLoaded', initializeApp);
    </script>
</body>
</html>
    '''

@app.route('/api/search-stores', methods=['POST'])
@limiter.limit("20 per minute")
def api_search_stores_enhanced():
    """Enhanced API endpoint for searching nearby stores"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        # Validate coordinates
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        radius = data.get('radius', 5)
        
        # Use the real search function
        stores = search_nearby_stores_enhanced(lat, lng, radius * 1609.34, None, 3)
        
        return jsonify({
            "status": "success",
            "stores": stores,
            "total_found": len(stores),
            "search_location": {"lat": lat, "lng": lng, "radius": radius},
            "search_timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
        
    except Exception as e:
        error_id = handle_error(e, "API search stores")
        return jsonify({"error": f"Search failed (ID: {error_id})"}), 500



@app.route('/webhook/location', methods=['POST'])
@limiter.limit("50 per minute")
def simplified_location_webhook():
    """Simplified location webhook for store check-ins"""
    try:
        data = request.get_json()
        safe_print(f"📨 Webhook received: {data}")
        
        if not data:
            safe_print("❌ No data in webhook request")
            return jsonify({"error": "No data provided"}), 400
        
        if not bot_connected or not bot_ready:
            safe_print(f"❌ Bot not ready: connected={bot_connected}, ready={bot_ready}")
            return jsonify({"error": "Bot not ready"}), 503
        
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        user_id = data['user_id']
        
        safe_print(f"📍 Location data: lat={lat}, lng={lng}, user={user_id}")
        
        # Get store data
        selected_store_data = data.get('selectedStore')
        session_id = data.get('session_id')
        
        if not selected_store_data:
            safe_print("❌ No selected store data")
            return jsonify({"error": "No store selected"}), 400
        
        safe_print(f"🏪 Store selected: {selected_store_data.get('name', 'Unknown')}")
        
        # Save to database with minimal data
        if user_id and selected_store_data:
            try:
                # Get channel ID from data or use global
                channel_id = data.get('channel_id') or LOCATION_CHANNEL_ID
                
                with db_pool.get_connection() as conn:
                    conn.execute('''
                        INSERT INTO user_locations 
                        (user_id, channel_id, guild_id, lat, lng, accuracy, store_name, store_address, 
                         store_place_id, store_category, distance, session_id, is_real_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(user_id),
                        str(channel_id) if channel_id else None,
                        data.get('guild_id'),
                        lat, lng,
                        data.get('accuracy'),
                        selected_store_data['name'],
                        selected_store_data['address'],
                        selected_store_data.get('place_id'),
                        selected_store_data.get('category'),
                        selected_store_data['distance'],
                        session_id,
                        data.get('isRealTime', True)
                    ))
                safe_print("✅ Location saved to database")
            except Exception as db_error:
                safe_print(f"⚠️ Database error: {db_error}")
        
        # Post to Discord
        if bot.loop and not bot.loop.is_closed():
            safe_print("🤖 Posting to Discord...")
            future = asyncio.run_coroutine_threadsafe(
                post_enhanced_location_to_discord(data), 
                bot.loop
            )
            
            result = future.result(timeout=20)
            if result:
                safe_print("✅ Successfully posted to Discord")
                
                # Delete the initial location message
                if bot.loop and not bot.loop.is_closed():
                    delete_future = asyncio.run_coroutine_threadsafe(
                        delete_initial_location_message(user_id, data.get('channel_id')),
                        bot.loop
                    )
                    try:
                        delete_future.result(timeout=10)
                    except Exception as delete_error:
                        safe_print(f"⚠️ Error deleting initial message: {delete_error}")
                
                log_analytics(
                    user_id,
                    "simplified_location_shared",
                    {
                        "store_name": selected_store_data.get('name') if selected_store_data else None,
                        "distance": selected_store_data.get('distance') if selected_store_data else None,
                        "session_id": session_id
                    },
                    request_obj=request,
                    session_id=session_id
                )
                
                return jsonify({"status": "success"}), 200
            else:
                safe_print("❌ Failed to post to Discord")
                return jsonify({"error": "Failed to post to Discord"}), 500
        else:
            safe_print(f"❌ Bot loop not available: loop={bot.loop}, closed={bot.loop.is_closed() if bot.loop else 'No loop'}")
            return jsonify({"error": "Bot loop not available"}), 503
        
    except Exception as e:
        error_id = handle_error(e, "Simplified location webhook")
        safe_print(f"❌ Webhook error: {e}")
        return jsonify({"error": f"Internal server error (ID: {error_id})"}), 500

async def post_enhanced_location_to_discord(location_data):
    """Simplified Discord location posting with minimal information"""
    global LOCATION_CHANNEL_ID, bot_ready, bot_connected, LOCATION_USER_INFO
    
    try:
        if not bot_connected or not bot_ready:
            safe_print("❌ Bot not ready for posting")
            return False
        
        # Get channel ID from location data or use global
        channel_id = location_data.get('channel_id') or LOCATION_CHANNEL_ID
        
        if not channel_id:
            safe_print("❌ No channel ID available for posting")
            return False
        
        channel = bot.get_channel(int(channel_id))
        if not channel:
            safe_print(f"❌ Channel {channel_id} not found")
            return False
        
        lat = float(location_data['latitude'])
        lng = float(location_data['longitude'])
        selected_store_data = location_data.get('selectedStore', None)
        user_id = location_data.get('user_id', None)
        session_id = location_data.get('session_id', None)
        
        if not selected_store_data:
            safe_print("❌ No store data provided")
            return False
        
        # Get user information
        username = "Someone"
        avatar_url = None
        
        if user_id:
            user_key = f"{channel_id}_{user_id}"
            if user_key in LOCATION_USER_INFO:
                user_info = LOCATION_USER_INFO[user_key]
                username = user_info['username']
                avatar_url = user_info['avatar_url']
        
        # Extract only essential store information
        store_name = selected_store_data['name']
        store_address = selected_store_data['address']
        distance = selected_store_data['distance']
        
        # Create simplified embed with only essential information
        embed = discord.Embed(
            title=f"{username}'s Check-in",
            description=f"**{store_name}** • **{distance:.1f} miles away**",
            color=0x5865F2  # Simple blue color
        )
        
        # Set author with user avatar
        if avatar_url:
            embed.set_author(
                name=f"{username}",
                icon_url=avatar_url
            )
        
        # Only essential information: store name, address, and distance
        embed.add_field(
            name="📍 Location",
            value=f"**{store_name}**\n{store_address}",
            inline=False
        )
        
        embed.add_field(
            name="📏 Distance",
            value=f"**{distance:.1f} miles** from {username}",
            inline=False
        )
        
        # Simple footer
        embed.set_footer(text="Location Bot • Real-time check-in")
        embed.timestamp = discord.utils.utcnow()
        
        # Delete previous embed if it exists
        try:
            # Get recent messages from the channel
            async for message in channel.history(limit=10):
                # Look for embeds from the same user with location information
                if (message.author == bot.user and 
                    message.embeds and 
                    any("Check-in" in embed.title for embed in message.embeds)):
                    await message.delete()
                    safe_print(f"🗑️ Deleted previous check-in embed")
                    break
        except Exception as delete_error:
            safe_print(f"⚠️ Could not delete previous embed: {delete_error}")
        
        # Send the new simplified embed
        message = await channel.send(embed=embed)
        
        # Add simple reactions
        reactions = ["👍", "📍"]
        for reaction in reactions:
            try:
                await message.add_reaction(reaction)
            except:
                pass  # Ignore reaction failures
        
        # Log analytics
        analytics_data = {
            "store_name": store_name,
            "distance": distance,
            "guild_name": channel.guild.name if channel.guild else "Direct Message",
            "channel_name": channel.name
        }
        
        log_analytics(
            user_id,
            "simplified_location_posted",
            analytics_data,
            guild_id=channel.guild.id if channel.guild else None,
            session_id=session_id
        )
        
        safe_print(f"✅ Simplified location posted to Discord for {username} at {store_name}")
        return True
        
    except Exception as e:
        error_id = handle_error(e, "Simplified Discord posting")
        safe_print(f"❌ Error posting to Discord: {error_id}")
        return False

@app.route('/health', methods=['GET'])
def enhanced_health_check():
    """Enhanced health check with detailed status"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {
                "discord_bot": {
                    "connected": bot_connected,
                    "ready": bot_ready,
                    "guilds": len(bot.guilds) if bot_connected else 0
                },
                "google_maps": {
                    "available": gmaps is not None,
                    "api_key_configured": bool(os.getenv('GOOGLE_MAPS_API_KEY'))
                },

                "cache": {
                    "type": "redis" if store_cache.redis_client else "memory",
                    "connected": store_cache.redis_client is not None
                }
            },
            "database": {
                "accessible": False,
                "response_time_ms": None
            }
        }
        
        # Test database connection
        db_start = time.time()
        try:
            with db_pool.get_connection() as conn:
                conn.execute('SELECT 1').fetchone()
            
            health_status["database"]["accessible"] = True
            health_status["database"]["response_time_ms"] = round((time.time() - db_start) * 1000, 2)
        except Exception as db_error:
            health_status["database"]["error"] = str(db_error)
            health_status["status"] = "degraded"
        
        # Overall health determination
        critical_services = [
            health_status["services"]["discord_bot"]["connected"],
            health_status["database"]["accessible"]
        ]
        
        if not all(critical_services):
            health_status["status"] = "unhealthy"
            return jsonify(health_status), 503
        elif not health_status["services"]["google_maps"]["available"]:
            health_status["status"] = "degraded"
            return jsonify(health_status), 200
        else:
            return jsonify(health_status), 200
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500

def run_enhanced_flask():
    """Run enhanced Flask server with production settings"""
    try:
        # Use production WSGI server
        from waitress import serve
        safe_print("🌐 Starting enhanced Flask server with Waitress...")
        serve(app, host=FLASK_HOST, port=FLASK_PORT, threads=4)
    except ImportError:
        # Fallback to development server if waitress not available
        safe_print("🌐 Starting enhanced Flask server (development mode)...")
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG, threaded=True)
    except Exception as e:
        # Fallback to basic Flask server if Waitress fails
        safe_print(f"⚠️ Waitress failed, using Flask development server: {e}")
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)

def main():
    """Simplified main function for Railway deployment"""
    safe_print("=== Starting Simplified Location Bot ===")
    
    # Environment validation
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        safe_print("❌ DISCORD_TOKEN environment variable not found!")
        return
    
    GOOGLE_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
    if not GOOGLE_API_KEY:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - store search will be limited")
    else:
        safe_print("✅ Google Maps API key found")
    
    # Check Railway environment
    railway_url = os.getenv('RAILWAY_URL')
    if railway_url:
        safe_print(f"✅ Railway URL: {railway_url}")
    else:
        safe_print("⚠️ RAILWAY_URL not set - using fallback URL: https://web-production-f0220.up.railway.app")
    
    def start_bot():
        safe_print("🤖 Starting simplified Discord bot...")
        try:
            bot.run(TOKEN, log_handler=None)  # Use our custom logging
        except Exception as e:
            handle_error(e, "Bot runtime")
    
    # Start Flask server immediately in a separate thread
    def start_flask():
        safe_print("🌐 Starting Flask server immediately...")
        try:
            run_enhanced_flask()
        except Exception as e:
            handle_error(e, "Flask server error")
    
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    
    # Give Flask a moment to start
    time.sleep(2)
    safe_print("✅ Flask server started!")
    
    # Start bot in separate thread
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Wait for bot to connect (shorter timeout for Railway)
    safe_print("⏰ Waiting for Discord bot to connect...")
    max_wait = 60  # Reduced from 90 to 60 seconds
    waited = 0
    while not bot_connected and waited < max_wait:
        time.sleep(1)
        waited += 1
        if waited % 10 == 0:  # Log every 10 seconds instead of 15
            safe_print(f"⏰ Still waiting... ({waited}s)")
    
    if bot_connected:
        safe_print("✅ Discord bot connected!")
    else:
        safe_print("⚠️ Bot not ready yet, but Flask is running...")
    
    # Keep the main thread alive
    try:
        heartbeat_count = 0
        while True:
            time.sleep(300)  # Sleep for 5 minutes instead of 1 minute
            heartbeat_count += 1
            if heartbeat_count % 12 == 0:  # Only log every hour (12 * 5 minutes = 60 minutes)
                safe_print("💓 Bot heartbeat... (hourly)")
    except KeyboardInterrupt:
        safe_print("🛑 Shutting down...")

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint to check bot status"""
    try:
        status = {
            "bot_connected": bot_connected,
            "bot_ready": bot_ready,
            "google_maps_available": gmaps is not None,
            "location_channel_id": LOCATION_CHANNEL_ID,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        safe_print(f"🧪 Test endpoint called: {status}")
        
        return jsonify(status), 200
        
    except Exception as e:
        error_id = handle_error(e, "Test endpoint")
        return jsonify({"error": f"Test failed (ID: {error_id})"}), 500

@app.route('/debug', methods=['GET'])
def debug_endpoint():
    """Debug endpoint to show Railway URL and environment"""
    try:
        railway_url = os.getenv('RAILWAY_URL')
        railway_static_url = os.getenv('RAILWAY_STATIC_URL')
        port = os.getenv('PORT')
        
        # If still no URL, try to construct from Railway's environment
        if not railway_url or 'your-app' in railway_url:
            # Try to get the actual Railway URL from environment
            railway_project_name = os.getenv('RAILWAY_PROJECT_NAME', 'web-production')
            railway_service_name = os.getenv('RAILWAY_SERVICE_NAME', 'f0220')
            railway_url = f"https://{railway_project_name}-{railway_service_name}.up.railway.app"
        
        debug_info = {
            "railway_url": railway_url,
            "railway_static_url": railway_static_url,
            "port": port,
            "bot_connected": bot_connected,
            "bot_ready": bot_ready,
            "google_maps_available": gmaps is not None,
            "location_channel_id": LOCATION_CHANNEL_ID,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        safe_print(f"🐛 Debug endpoint called: {debug_info}")
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        error_id = handle_error(e, "Debug endpoint")
        return jsonify({"error": f"Debug failed (ID: {error_id})"}), 500

@app.route('/simple-debug', methods=['GET'])
def simple_debug():
    """Super simple debug endpoint"""
    return jsonify({
        "status": "ok",
        "bot_ready": bot_ready,
        "timestamp": datetime.now().isoformat(),
        "stores": len(get_comprehensive_store_database()),
        "railway_url": get_railway_url(),
        "working_url": "https://web-production-f0220.up.railway.app"
    })

@app.route('/test-portal', methods=['GET'])
def test_portal():
    """Test if the web portal is working"""
    session_id = request.args.get('session', 'test')
    user_id = request.args.get('user', 'test')
    channel_id = request.args.get('channel', 'test')
    
    return jsonify({
        "status": "portal_working",
        "session_id": session_id,
        "user_id": user_id,
        "channel_id": channel_id,
        "timestamp": datetime.now().isoformat(),
        "message": "Web portal is working correctly!"
    })

if __name__ == "__main__":
    main()
