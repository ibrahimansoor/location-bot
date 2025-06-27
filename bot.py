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
from datetime import datetime, timedelta
import sqlite3
from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import uuid
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import redis
import pickle
from marshmallow import Schema, fields, validate, ValidationError
import heapq
from collections import defaultdict

# Enhanced Flask app with rate limiting
app = Flask(__name__)
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["500 per day", "100 per hour"],
    storage_uri="memory://"
)

# Enhanced bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Google Maps and Weather clients
gmaps = None
WEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')

# Enhanced database configuration
DATABASE_PATH = 'enhanced_location_bot.db'
CACHE_ENABLED = os.getenv('REDIS_URL') is not None

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
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
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
    """Redis-backed cache with fallback to in-memory"""
    
    def __init__(self, default_ttl=1800):
        self.default_ttl = default_ttl
        self.memory_cache = {}
        self.redis_client = None
        
        if CACHE_ENABLED:
            try:
                redis_url = os.getenv('REDIS_URL')
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                safe_print("✅ Redis cache connected")
            except Exception as e:
                safe_print(f"⚠️ Redis connection failed, using memory cache: {e}")
    
    def _get_cache_key(self, lat: float, lng: float, radius: int, category: str = None) -> str:
        rounded_lat = round(lat, 3)
        rounded_lng = round(lng, 3)
        base_key = f"stores:{rounded_lat}:{rounded_lng}:{radius}"
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

# Input validation schemas
class LocationSchema(Schema):
    latitude = fields.Float(required=True, validate=validate.Range(min=-90, max=90))
    longitude = fields.Float(required=True, validate=validate.Range(min=-180, max=180))
    user_id = fields.String(required=True, validate=validate.Length(min=1, max=25))
    accuracy = fields.Float(missing=None, validate=validate.Range(min=0))

class StoreSearchSchema(Schema):
    latitude = fields.Float(required=True, validate=validate.Range(min=-90, max=90))
    longitude = fields.Float(required=True, validate=validate.Range(min=-180, max=180))
    radius = fields.Integer(missing=16000, validate=validate.Range(min=100, max=50000))
    category = fields.String(missing=None)
    user_id = fields.String(required=True)

def validate_input(schema_class, data):
    """Validate input data against schema"""
    schema = schema_class()
    try:
        return schema.load(data)
    except ValidationError as err:
        raise ValueError(f"Invalid input: {err.messages}")

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
                session_id TEXT,
                
                INDEX idx_user_timestamp (user_id, timestamp),
                INDEX idx_location (lat, lng),
                INDEX idx_store_category (store_category)
            )
        ''')
        
        # Enhanced user permissions
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                server_id TEXT,
                permissions TEXT,  -- JSON string of additional permissions
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_user_favorites (user_id),
                INDEX idx_category (category)
            )
        ''')
        
        # Analytics table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS usage_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                guild_id TEXT,
                action TEXT NOT NULL,
                data TEXT,  -- JSON data
                ip_address TEXT,
                user_agent TEXT,
                session_id TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                INDEX idx_action_timestamp (action, timestamp),
                INDEX idx_user_analytics (user_id, timestamp)
            )
        ''')
        
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
                expires_at TIMESTAMP,
                
                INDEX idx_session_channel (channel_id, is_active)
            )
        ''')
        
        # Session participants
        conn.execute('''
            CREATE TABLE IF NOT EXISTS session_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_location_update TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                
                UNIQUE(session_id, user_id),
                INDEX idx_session_participants (session_id, is_active)
            )
        ''')
        
        # Store cache table (persistent cache)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS store_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                location_lat REAL NOT NULL,
                location_lng REAL NOT NULL,
                radius INTEGER NOT NULL,
                category TEXT,
                store_data TEXT NOT NULL,  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                
                INDEX idx_location_cache (location_lat, location_lng, radius),
                INDEX idx_cache_expiry (expires_at)
            )
        ''')

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
    """Enhanced store database with detailed configurations"""
    return [
        # Department Stores (Priority 1)
        StoreConfig("Target", "Target", "🎯", "Department", 1, ["Target", "Target Store"]),
        StoreConfig("Walmart", "Walmart", "🏪", "Superstore", 1, ["Walmart", "Walmart Supercenter"]),
        StoreConfig("Macy's", "Macys", "👗", "Department", 2, ["Macy's", "Macys"]),
        StoreConfig("Nordstrom", "Nordstrom", "👔", "Department", 2, ["Nordstrom"]),
        StoreConfig("Kohl's", "Kohls", "🛍️", "Department", 2, ["Kohl's", "Kohls"]),
        
        # Electronics (Priority 1-2)
        StoreConfig("Best Buy", "Best Buy", "🔌", "Electronics", 1, ["Best Buy"]),
        StoreConfig("Apple Store", "Apple", "📱", "Electronics", 2, ["Apple Store", "Apple"]),
        StoreConfig("GameStop", "GameStop", "🎮", "Electronics", 3, ["GameStop"]),
        StoreConfig("Micro Center", "Micro Center", "💻", "Electronics", 2, ["Micro Center"]),
        
        # Wholesale/Warehouse (Priority 1-2)
        StoreConfig("BJ's Wholesale Club", "BJs", "🛒", "Wholesale", 1, ["BJ's", "BJs"]),
        StoreConfig("Costco", "Costco", "🏬", "Wholesale", 1, ["Costco"]),
        StoreConfig("Sam's Club", "Sams Club", "🛍️", "Wholesale", 2, ["Sam's Club", "Sams"]),
        
        # Hardware/Home Improvement (Priority 1-2)
        StoreConfig("Home Depot", "Home Depot", "🔨", "Hardware", 1, ["Home Depot", "The Home Depot"]),
        StoreConfig("Lowe's", "Lowes", "🏠", "Hardware", 1, ["Lowe's", "Lowes"]),
        StoreConfig("Menards", "Menards", "🔧", "Hardware", 2, ["Menards"]),
        StoreConfig("Harbor Freight", "Harbor Freight", "⚒️", "Hardware", 3, ["Harbor Freight"]),
        
        # Pharmacies (Priority 1-2)
        StoreConfig("CVS Pharmacy", "CVS", "💊", "Pharmacy", 1, ["CVS", "CVS Pharmacy"]),
        StoreConfig("Walgreens", "Walgreens", "⚕️", "Pharmacy", 1, ["Walgreens"]),
        StoreConfig("Rite Aid", "Rite Aid", "🏥", "Pharmacy", 2, ["Rite Aid"]),
        
        # Grocery (Priority 1-3)
        StoreConfig("Stop & Shop", "Stop & Shop", "🛒", "Grocery", 1, ["Stop & Shop", "Stop and Shop"]),
        StoreConfig("Market Basket", "Market Basket", "🥬", "Grocery", 1, ["Market Basket"]),
        StoreConfig("Whole Foods", "Whole Foods", "🥗", "Grocery", 2, ["Whole Foods", "Whole Foods Market"]),
        StoreConfig("Trader Joe's", "Trader Joes", "🌽", "Grocery", 2, ["Trader Joe's", "Trader Joes"]),
        StoreConfig("Shaw's", "Shaws", "🥕", "Grocery", 2, ["Shaw's", "Shaws"]),
        StoreConfig("Big Y", "Big Y", "🍎", "Grocery", 3, ["Big Y"]),
        
        # Coffee & Fast Food (Priority 1-3)
        StoreConfig("Starbucks", "Starbucks", "☕", "Coffee", 1, ["Starbucks"]),
        StoreConfig("Dunkin'", "Dunkin", "🍩", "Coffee", 1, ["Dunkin'", "Dunkin Donuts"]),
        StoreConfig("McDonald's", "McDonalds", "🍟", "Fast Food", 1, ["McDonald's", "McDonalds"]),
        StoreConfig("Subway", "Subway", "🥪", "Fast Food", 2, ["Subway"]),
        StoreConfig("Burger King", "Burger King", "🍔", "Fast Food", 2, ["Burger King"]),
        StoreConfig("Taco Bell", "Taco Bell", "🌮", "Fast Food", 3, ["Taco Bell"]),
        
        # Gas Stations (Priority 1-3)
        StoreConfig("Shell", "Shell", "⛽", "Gas", 1, ["Shell", "Shell Gas"]),
        StoreConfig("Mobil", "Mobil", "⛽", "Gas", 1, ["Mobil", "Exxon Mobil"]),
        StoreConfig("Gulf", "Gulf", "⛽", "Gas", 2, ["Gulf"]),
        StoreConfig("Citgo", "Citgo", "⛽", "Gas", 2, ["Citgo"]),
        StoreConfig("Cumberland Farms", "Cumberland", "⛽", "Gas", 2, ["Cumberland Farms", "Cumbys"]),
        
        # Banking (Priority 1-3)
        StoreConfig("Bank of America", "BofA", "🏦", "Banking", 1, ["Bank of America", "BofA"]),
        StoreConfig("TD Bank", "TD Bank", "🏦", "Banking", 1, ["TD Bank"]),
        StoreConfig("Citizens Bank", "Citizens", "🏦", "Banking", 2, ["Citizens Bank"]),
        StoreConfig("Wells Fargo", "Wells Fargo", "🏦", "Banking", 2, ["Wells Fargo"]),
        StoreConfig("Chase Bank", "Chase", "🏦", "Banking", 1, ["Chase", "JPMorgan Chase"]),
        
        # Auto/Service (Priority 2-3)
        StoreConfig("AutoZone", "AutoZone", "🔧", "Auto", 2, ["AutoZone"]),
        StoreConfig("Jiffy Lube", "Jiffy Lube", "🛠️", "Auto", 3, ["Jiffy Lube"]),
        StoreConfig("Valvoline", "Valvoline", "🛢️", "Auto", 3, ["Valvoline Instant Oil"]),
    ]

def initialize_google_maps():
    """Enhanced Google Maps initialization"""
    global gmaps
    
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - real-time search disabled")
        return False
    
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

async def get_weather_data(lat: float, lng: float) -> Optional[Dict]:
    """Get weather data for location"""
    if not WEATHER_API_KEY:
        return None
    
    try:
        url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            'lat': lat,
            'lon': lng,
            'appid': WEATHER_API_KEY,
            'units': 'imperial'  # Fahrenheit for US users
        }
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                'temperature': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'description': data['weather'][0]['description'].title(),
                'humidity': data['main']['humidity'],
                'icon': data['weather'][0]['icon'],
                'visibility': data.get('visibility', 0) / 1000,  # Convert to miles
                'wind_speed': data.get('wind', {}).get('speed', 0),
                'timestamp': datetime.utcnow().isoformat()
            }
    except Exception as e:
        handle_error(e, "Weather API request")
    
    return None

def search_nearby_stores_enhanced(lat: float, lng: float, radius_meters: int = 16000, 
                                 category: str = None, max_stores_per_type: int = 4) -> List[Dict]:
    """Enhanced store search with comprehensive coverage and caching"""
    
    # Check cache first
    cached_result = store_cache.get(lat, lng, radius_meters, category)
    if cached_result:
        return cached_result
    
    if not gmaps:
        safe_print("❌ Google Maps API not available")
        return []
    
    try:
        all_stores = []
        location = (lat, lng)
        store_configs = get_comprehensive_store_database()
        
        # Filter by category if specified
        if category:
            store_configs = [s for s in store_configs if s.category.lower() == category.lower()]
        
        # Group by priority for efficient searching
        priority_groups = defaultdict(list)
        for store_config in store_configs:
            priority_groups[store_config.priority].append(store_config)
        
        safe_print(f"🔍 Searching {len(store_configs)} store types in {len(priority_groups)} priority groups")
        
        # Search by priority (1 = highest priority)
        for priority in sorted(priority_groups.keys()):
            safe_print(f"🔍 Priority {priority} stores ({len(priority_groups[priority])} types)...")
            
            for store_config in priority_groups[priority]:
                try:
                    search_terms = store_config.search_terms or [store_config.query]
                    
                    for search_term in search_terms:
                        try:
                            safe_print(f"  🔍 Searching: {search_term}")
                            
                            # Search for nearby places
                            places_result = gmaps.places_nearby(
                                location=location,
                                radius=radius_meters,
                                keyword=search_term,
                                type='establishment'
                            )
                            
                            found_places = places_result.get('results', [])
                            if found_places:
                                safe_print(f"    📍 Found {len(found_places)} {store_config.chain} locations")
                                break  # Found results for this store, no need to try other search terms
                            
                        except Exception as search_error:
                            safe_print(f"    ❌ Search term '{search_term}' failed: {search_error}")
                            continue
                    
                    if not found_places:
                        continue
                    
                    # Process found places (limit per store type)
                    places_to_process = found_places[:max_stores_per_type]
                    processed_count = 0
                    
                    for place in places_to_process:
                        try:
                            place_lat = place['geometry']['location']['lat']
                            place_lng = place['geometry']['location']['lng']
                            distance = calculate_distance(lat, lng, place_lat, place_lng)
                            
                            # Skip if too far (convert radius to miles)
                            max_distance_miles = radius_meters / 1609.34
                            if distance > max_distance_miles:
                                continue
                            
                            # Get detailed place information
                            place_details = gmaps.place(
                                place_id=place['place_id'],
                                fields=[
                                    'name', 'formatted_address', 'place_id', 'geometry', 
                                    'rating', 'user_ratings_total', 'formatted_phone_number',
                                    'opening_hours', 'website', 'business_status', 'price_level',
                                    'types', 'vicinity'
                                ]
                            )
                            
                            details = place_details.get('result', {})
                            
                            # Enhanced opening hours processing
                            opening_hours = details.get('opening_hours', {})
                            is_open = opening_hours.get('open_now', None)
                            weekly_hours = opening_hours.get('weekday_text', [])
                            
                            # Business status validation
                            business_status = details.get('business_status', 'OPERATIONAL')
                            if business_status in ['CLOSED_PERMANENTLY', 'CLOSED_TEMPORARILY']:
                                continue
                            
                            # Enhanced store data
                            store_data = {
                                'name': details.get('name', place.get('name', 'Unknown Store')),
                                'address': details.get('formatted_address', place.get('vicinity', 'Unknown Address')),
                                'place_id': place['place_id'],
                                'lat': place_lat,
                                'lng': place_lng,
                                'chain': store_config.chain,
                                'icon': store_config.icon,
                                'category': store_config.category,
                                'priority': store_config.priority,
                                'distance': distance,
                                'rating': details.get('rating'),
                                'rating_count': details.get('user_ratings_total'),
                                'phone': details.get('formatted_phone_number'),
                                'website': details.get('website'),
                                'is_open': is_open,
                                'weekly_hours': weekly_hours,
                                'business_status': business_status,
                                'price_level': details.get('price_level'),
                                'types': details.get('types', []),
                                'verified': 'google_places',
                                'search_timestamp': datetime.utcnow().isoformat(),
                                'search_radius': radius_meters,
                                'quality_score': calculate_quality_score(details, distance)
                            }
                            
                            all_stores.append(store_data)
                            processed_count += 1
                            
                        except Exception as place_error:
                            handle_error(place_error, f"Processing place for {store_config.chain}")
                            continue
                    
                    if processed_count > 0:
                        safe_print(f"    ✅ Processed {processed_count} {store_config.chain} locations")
                    
                    # Rate limiting between store types
                    time.sleep(0.1)
                    
                except Exception as store_error:
                    handle_error(store_error, f"Searching {store_config.chain}")
                    continue
            
            # Longer pause between priority groups
            if priority < max(priority_groups.keys()):
                time.sleep(0.2)
        
        # Remove duplicates and sort
        unique_stores = remove_duplicate_stores(all_stores)
        unique_stores.sort(key=lambda x: (x['priority'], x['distance'], -x.get('quality_score', 0)))
        
        safe_print(f"✅ Found {len(unique_stores)} unique stores (from {len(all_stores)} total)")
        
        # Cache the results
        cache_ttl = 1800 if len(unique_stores) > 0 else 300  # Cache longer if we found results
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
            existing_lat = existing_store['lat']
            existing_lng = existing_store['lng']
            distance_meters = calculate_distance(
                store['lat'], store['lng'], 
                existing_lat, existing_lng
            ) * 1609.34  # Convert miles to meters
            
            if distance_meters < 100:  # Within 100 meters
                # Keep the one with better quality score
                if store.get('quality_score', 0) <= existing_store.get('quality_score', 0):
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
                
                # Clean expired cache entries
                cache_result = conn.execute(
                    'DELETE FROM store_cache WHERE expires_at < CURRENT_TIMESTAMP'
                )
                
                safe_print(f"🧹 Cleanup: {location_result.rowcount} locations, "
                          f"{analytics_result.rowcount} analytics, {cache_result.rowcount} cache")
                
        except Exception as e:
            handle_error(e, "Data cleanup")

task_manager = TaskManager()

# Global state management
LOCATION_CHANNEL_ID = None
LOCATION_USER_INFO = {}
ACTIVE_SESSIONS = {}
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
        
        # Sync slash commands
        synced = await bot.tree.sync()
        safe_print(f"🔄 Synced {len(synced)} slash commands")
        
        bot_ready = True
        safe_print("✅ Enhanced Location Bot is ready!")
        
        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"📍 {len(bot.guilds)} servers • /location"
        )
        await bot.change_presence(activity=activity)
        
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

# Continue with more commands in the next part...
