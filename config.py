# Configuration file for Location Bot
import os
from typing import List, Dict

# Bot Configuration
BOT_NAME = "Location Bot"
BOT_VERSION = "2.0.0"
BOT_DESCRIPTION = "Simple store check-ins with real-time location"

# Discord Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DISCORD_PREFIX = '!'
DISCORD_INTENTS = {
    'message_content': True,
    'guilds': True,
    'guild_messages': True
}

# Google Maps Configuration
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
GOOGLE_PLACES_FIELDS = [
    'name', 'formatted_address', 'formatted_phone_number', 
    'rating', 'user_ratings_total', 'opening_hours', 
    'website', 'price_level'
]

# Database Configuration
DATABASE_PATH = 'enhanced_location_bot.db'
DATABASE_POOL_SIZE = 10
CACHE_ENABLED = os.getenv('REDIS_URL') is not None
CACHE_TTL = 1800  # 30 minutes default
CACHE_TTL_SHORT = 300  # 5 minutes for fresh results

# Search Configuration
DEFAULT_SEARCH_RADIUS = 5  # miles
MAX_SEARCH_RADIUS = 20  # miles
MAX_STORES_PER_TYPE = 3
SEARCH_TIMEOUT = 30  # seconds
PARALLEL_WORKERS = 4

# Store Configuration
ALLOWED_STORES = ['Target', 'Walmart', 'BJ\'s Wholesale Club', 'Best Buy']

# Medford Target Configuration
MEDFORD_TARGET = {
    'name': 'Target',
    'address': '471 Salem St, Medford, MA 02155, USA',
    'latitude': 42.4184,
    'longitude': -71.1062,
    'phone': '(781) 658-3365',
    'rating': 4.5,
    'user_ratings_total': 100,
    'place_id': 'medford_target_manual',
    'quality_score': 0.9
}

MEDFORD_AREA = {
    'lat_min': 42.40,
    'lat_max': 42.45,
    'lng_min': -71.15,
    'lng_max': -71.05
}

# Flask Configuration
FLASK_HOST = '0.0.0.0'
FLASK_PORT = int(os.getenv('PORT', 8080))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# Rate Limiting
RATE_LIMITS = {
    'default': ["500 per day", "100 per hour"],
    'search': "20 per minute",
    'webhook': "50 per minute"
}

# Logging Configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = 'location_bot.log'
LOG_MAX_SIZE = 50 * 1024 * 1024  # 50MB
LOG_BACKUP_COUNT = 10

# Railway Configuration
RAILWAY_URL = os.getenv('RAILWAY_URL')
RAILWAY_STATIC_URL = os.getenv('RAILWAY_STATIC_URL')
RAILWAY_PROJECT_NAME = os.getenv('RAILWAY_PROJECT_NAME', 'web-production')
RAILWAY_SERVICE_NAME = os.getenv('RAILWAY_SERVICE_NAME', 'f0220')

# Fallback URL if Railway URL not set
FALLBACK_URL = f"https://{RAILWAY_PROJECT_NAME}-{RAILWAY_SERVICE_NAME}.up.railway.app"

# Performance Configuration
BOT_CONNECTION_TIMEOUT = 60  # seconds
BOT_READY_WAIT = 3  # seconds
CLEANUP_INTERVAL = 24  # hours
CACHE_CLEANUP_INTERVAL = 6  # hours

# Error Handling
ERROR_ID_LENGTH = 8
MAX_ERROR_MESSAGE_LENGTH = 1000

# Validation
MIN_LATITUDE = -90
MAX_LATITUDE = 90
MIN_LONGITUDE = -180
MAX_LONGITUDE = 180
MIN_RADIUS = 1
MAX_RADIUS = 50

def validate_coordinates(lat: float, lng: float) -> bool:
    """Validate latitude and longitude coordinates"""
    return (MIN_LATITUDE <= lat <= MAX_LATITUDE and 
            MIN_LONGITUDE <= lng <= MAX_LONGITUDE)

def validate_radius(radius: int) -> bool:
    """Validate search radius"""
    return MIN_RADIUS <= radius <= MAX_RADIUS

def get_railway_url() -> str:
    """Get the Railway URL with fallbacks"""
    if RAILWAY_STATIC_URL:
        return RAILWAY_STATIC_URL
    elif RAILWAY_URL and 'your-app' not in RAILWAY_URL:
        return RAILWAY_URL
    else:
        return FALLBACK_URL 