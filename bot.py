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
import pickle
from collections import defaultdict

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

# Google Maps client
gmaps = None

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
        StoreConfig("Target", "Target", "🎯", "Department", 1, ["Target", "Target Store", "Target Corporation", "Target Superstore"]),
        StoreConfig("Walmart", "Walmart", "🏪", "Superstore", 1, ["Walmart", "Walmart Supercenter"]),
        StoreConfig("BJ's Wholesale Club", "BJs", "🛒", "Wholesale", 1, ["BJ's", "BJs", "BJ's Wholesale"]),
        StoreConfig("Best Buy", "Best Buy", "🔌", "Electronics", 1, ["Best Buy", "BestBuy"]),
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



def search_nearby_stores_enhanced(lat: float, lng: float, radius_meters: int = 8000, 
                                 category: str = None, max_stores_per_type: int = 2) -> List[Dict]:
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
                                    'vicinity'
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
                                'types': place.get('types', []),
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
                    
                    # Rate limiting between store types (reduced for speed)
                    time.sleep(0.05)
                    
                except Exception as store_error:
                    handle_error(store_error, f"Searching {store_config.chain}")
                    continue
            
            # Shorter pause between priority groups (optimized for speed)
            if priority < max(priority_groups.keys()):
                time.sleep(0.1)
        
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
                
                safe_print(f"🧹 Cleanup: {location_result.rowcount} locations, "
                          f"{analytics_result.rowcount} analytics")
                
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
    global LOCATION_CHANNEL_ID, LOCATION_USER_INFO
    
    # Store interaction details for fallback
    channel = interaction.channel
    user = interaction.user
    
    try:
        # Check permissions first
        if not check_user_permissions(interaction.user.id, 'user'):
            try:
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            except:
                await channel.send(f"{user.mention} ❌ You don't have permission to use this command.")
            return
        
        # Get Railway URL with correct priority
        railway_url = os.getenv('RAILWAY_STATIC_URL')  # This has the correct URL
        if not railway_url:
            railway_url = os.getenv('RAILWAY_URL') or os.getenv('PORT') or 'https://web-production-f0220.up.railway.app'
        
        # Ensure URL has https:// prefix
        if railway_url and not railway_url.startswith('http'):
            railway_url = f"https://{railway_url}"
        
        # If still no URL, try to construct from Railway's environment
        if not railway_url or 'your-app' in railway_url:
            railway_project_name = os.getenv('RAILWAY_PROJECT_NAME', 'web-production')
            railway_service_name = os.getenv('RAILWAY_SERVICE_NAME', 'f0220')
            railway_url = f"https://{railway_project_name}-{railway_service_name}.up.railway.app"
        
        # Generate session ID and URL
        session_id = str(uuid.uuid4())
        website_url = f"{railway_url}?session={session_id}&user={interaction.user.id}&channel={interaction.channel.id}"
        
        # Store user info
        LOCATION_CHANNEL_ID = interaction.channel.id
        user_key = f"{interaction.channel.id}_{interaction.user.id}"
        LOCATION_USER_INFO[user_key] = {
            'user_id': interaction.user.id,
            'username': interaction.user.display_name,
            'full_username': str(interaction.user),
            'avatar_url': interaction.user.display_avatar.url,
            'timestamp': discord.utils.utcnow(),
            'session_id': session_id
        }
        
        # Create embed
        embed = discord.Embed(
            title="📍 Location Sharing",
            description=f"**{interaction.user.display_name}** wants to share their location",
            color=0x5865F2
        )
        
        embed.add_field(
            name="🔗 Location Portal",
            value=f"[Click here to share your location]({website_url})",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ How it works",
            value="1. Click the link above\n2. Allow location access\n3. Select a store to check in\n4. Your check-in will be posted here",
            inline=False
        )
        
        embed.set_footer(text="Location Bot • Simple store check-ins")
        embed.timestamp = discord.utils.utcnow()
        
        # Try to respond to interaction first
        try:
            await interaction.response.send_message(embed=embed)
        except Exception as interaction_error:
            # If interaction fails, send as regular channel message
            safe_print(f"⚠️ Interaction failed, sending channel message: {interaction_error}")
            await channel.send(f"{user.mention}", embed=embed)
        
        safe_print(f"🔗 Using Railway URL: {railway_url}")
        
        # Log analytics in background
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
        
    except Exception as e:
        error_id = handle_error(e, "Location command")
        error_message = f"❌ Error creating location session (ID: {error_id})"
        
        # Try multiple ways to send error message
        try:
            await interaction.response.send_message(error_message, ephemeral=True)
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
        
        # Get Railway URL with correct priority
        railway_url = os.getenv('RAILWAY_STATIC_URL')  # This has the correct URL
        if not railway_url:
            railway_url = os.getenv('RAILWAY_URL') or os.getenv('PORT') or 'https://web-production-f0220.up.railway.app'
        
        # Ensure URL has https:// prefix
        if railway_url and not railway_url.startswith('http'):
            railway_url = f"https://{railway_url}"
        
        # If still no URL, try to construct from Railway's environment
        if not railway_url or 'your-app' in railway_url:
            railway_project_name = os.getenv('RAILWAY_PROJECT_NAME', 'web-production')
            railway_service_name = os.getenv('RAILWAY_SERVICE_NAME', 'f0220')
            railway_url = f"https://{railway_project_name}-{railway_service_name}.up.railway.app"
        
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
            if (!storesContainer) return;
            
            if (nearbyStores.length === 0) {{
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
    """Enhanced API endpoint for store search"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        radius = data.get('radius', 5)  # 5 mile radius as requested
        category = data.get('category')
        user_id = data['user_id']
        
        safe_print(f"🔍 Search request: lat={lat}, lng={lng}, radius={radius}, user={user_id}")
        
        # Check if Google Maps is available
        if not gmaps:
            safe_print("❌ Google Maps API not available")
            return jsonify({
                "error": "Google Maps API not available",
                "status": "error",
                "stores": [],
                "total_found": 0
            }), 503
        
        # Search for stores
        stores = search_nearby_stores_enhanced(lat, lng, radius * 1609.34, category)  # Convert miles to meters
        
        safe_print(f"🔍 Search completed: found {len(stores)} stores")
        
        # Group stores by category
        categorized_stores = defaultdict(list)
        for store in stores:
            categorized_stores[store['category']].append(store)
        
        safe_print(f"🔍 Enhanced search found {len(stores)} stores in {len(categorized_stores)} categories for user {user_id}")
        
        # Log analytics
        log_analytics(
            user_id,
            "simplified_store_search",
            {
                "location": {"lat": lat, "lng": lng},
                "radius": radius,
                "category": category,
                "results_count": len(stores),
                "categories_found": list(categorized_stores.keys())
            },
            request_obj=request
        )
        
        return jsonify({
            "status": "success",
            "stores": stores,
            "categorized_stores": dict(categorized_stores),
            "search_location": {"lat": lat, "lng": lng, "radius": radius},
            "total_found": len(stores),
            "categories": list(categorized_stores.keys()),
            "search_timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        error_id = handle_error(e, "Enhanced store search API")
        safe_print(f"❌ Search API error: {e}")
        return jsonify({"error": f"Internal server error (ID: {error_id})"}), 500



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
                with db_pool.get_connection() as conn:
                    conn.execute('''
                        INSERT INTO user_locations 
                        (user_id, channel_id, guild_id, lat, lng, accuracy, store_name, store_address, 
                         store_place_id, store_category, distance, session_id, is_real_time)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(user_id),
                        str(LOCATION_CHANNEL_ID),
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
        if not bot_connected or not bot_ready or not LOCATION_CHANNEL_ID:
            safe_print("❌ Bot or channel not ready for posting")
            return False
        
        channel = bot.get_channel(LOCATION_CHANNEL_ID)
        if not channel:
            safe_print(f"❌ Channel {LOCATION_CHANNEL_ID} not found")
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
            user_key = f"{LOCATION_CHANNEL_ID}_{user_id}"
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
            "timestamp": datetime.utcnow().isoformat(),
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
            "timestamp": datetime.utcnow().isoformat()
        }), 500

def run_enhanced_flask():
    """Run enhanced Flask server"""
    try:
        port = int(os.getenv('PORT', 5000))
        debug_mode = os.getenv('FLASK_ENV') == 'development'
        safe_print(f"🌐 Starting enhanced Flask server on port {port}")
        app.run(
            host='0.0.0.0', 
            port=port, 
            debug=debug_mode, 
            use_reloader=False, 
            threaded=True
        )
    except Exception as e:
        handle_error(e, "Flask startup")

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
        time.sleep(3)  # Reduced from 5 to 3 seconds
    else:
        safe_print("⚠️ Bot not ready yet, but starting Flask anyway...")
    
    try:
        run_enhanced_flask()
    except Exception as e:
        handle_error(e, "Critical server error")

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Simple test endpoint to check bot status"""
    try:
        status = {
            "bot_connected": bot_connected,
            "bot_ready": bot_ready,
            "google_maps_available": gmaps is not None,
            "location_channel_id": LOCATION_CHANNEL_ID,
            "timestamp": datetime.utcnow().isoformat()
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
            "timestamp": datetime.utcnow().isoformat()
        }
        
        safe_print(f"🐛 Debug endpoint called: {debug_info}")
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        error_id = handle_error(e, "Debug endpoint")
        return jsonify({"error": f"Debug failed (ID: {error_id})"}), 500

if __name__ == "__main__":
    main()
