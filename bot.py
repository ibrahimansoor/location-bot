import discord
from discord.ext import commands
import os
import math
import asyncio
import json
from flask import Flask, request, jsonify
import threading
import time
import sys
import requests
import googlemaps
from datetime import datetime, timedelta
import sqlite3
from contextlib import contextmanager

# Flask app with enhanced error handling
app = Flask(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Google Maps client - will be initialized with API key
gmaps = None

# Database setup
DATABASE_PATH = 'location_bot.db'

def safe_print(msg):
    """Safe printing for Railway logs"""
    try:
        print(f"[BOT] {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} {msg}")
        sys.stdout.flush()
    except:
        pass

@contextmanager
def get_db_connection():
    """Database connection context manager"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        safe_print(f"Database error: {e}")
        raise
    finally:
        conn.close()

def init_database():
    """Initialize SQLite database"""
    with get_db_connection() as conn:
        # Stores table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                chain TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                verified TEXT DEFAULT 'unverified',
                geocoded_date TEXT,
                place_id TEXT,
                location_type TEXT,
                formatted_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # User locations table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                accuracy REAL,
                store_name TEXT,
                distance REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_real_time BOOLEAN DEFAULT FALSE
            )
        ''')
        
        # User permissions table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_permissions (
                user_id TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                server_id TEXT,
                granted_by TEXT,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Real-time tracking sessions
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tracking_sessions (
                user_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                active BOOLEAN DEFAULT TRUE,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

# Store database - will be populated from database
STORE_ADDRESSES = [
    # TARGET STORES
    {"name": "Target Abington", "address": "385 Centre Ave, Abington, MA 02351", "chain": "Target"},
    {"name": "Target Boston Fenway", "address": "1341 Boylston St, Boston, MA 02215", "chain": "Target"},
    {"name": "Target Boston South Bay", "address": "250 Granite St, Boston, MA 02125", "chain": "Target"},
    {"name": "Target Braintree", "address": "550 Grossman Dr, Braintree, MA 02184", "chain": "Target"},
    {"name": "Target Burlington", "address": "51 Middlesex Tpke, Burlington, MA 01803", "chain": "Target"},
    {"name": "Target Cambridge", "address": "180 Somerville Ave, Cambridge, MA 02143", "chain": "Target"},
    {"name": "Target Danvers", "address": "112 Endicott St, Danvers, MA 01923", "chain": "Target"},
    {"name": "Target Dedham", "address": "850 Providence Hwy, Dedham, MA 02026", "chain": "Target"},
    {"name": "Target Dorchester", "address": "7 Allstate Rd, Dorchester, MA 02125", "chain": "Target"},
    {"name": "Target Everett", "address": "1 Mystic View Rd, Everett, MA 02149", "chain": "Target"},
    {"name": "Target Framingham", "address": "400 Cochituate Rd, Framingham, MA 01701", "chain": "Target"},
    
    # WALMART STORES
    {"name": "Walmart Abington", "address": "777 Brockton Ave, Abington, MA 02351", "chain": "Walmart"},
    {"name": "Walmart Avon", "address": "30 Memorial Dr, Avon, MA 02322", "chain": "Walmart"},
    {"name": "Walmart Bellingham", "address": "250 Hartford Ave, Bellingham, MA 02019", "chain": "Walmart"},
    {"name": "Walmart Brockton", "address": "700 Oak St, Brockton, MA 02301", "chain": "Walmart"},
    {"name": "Walmart Chelmsford", "address": "66 Parkhurst Rd, Chelmsford, MA 01824", "chain": "Walmart"},
    
    # BEST BUY STORES
    {"name": "Best Buy Braintree", "address": "550 Grossman Dr, Braintree, MA 02184", "chain": "Best Buy"},
    {"name": "Best Buy Burlington", "address": "84 Middlesex Tpke, Burlington, MA 01803", "chain": "Best Buy"},
    {"name": "Best Buy Cambridge", "address": "100 CambridgeSide Pl, Cambridge, MA 02141", "chain": "Best Buy"},
    
    # BJS WHOLESALE STORES
    {"name": "BJs Wholesale Auburn", "address": "777 Washington St, Auburn, MA 01501", "chain": "BJs"},
    {"name": "BJs Wholesale Chicopee", "address": "650 Memorial Dr, Chicopee, MA 01020", "chain": "BJs"},
]

# Global state
LOCATION_CHANNEL_ID = None
LOCATION_USER_INFO = {}
bot_ready = False
bot_connected = False

def initialize_google_maps():
    """Initialize Google Maps client with enhanced validation"""
    global gmaps
    
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - using fallback coordinates")
        return False
    
    try:
        gmaps = googlemaps.Client(key=api_key)
        
        # Test the API key with a simple geocoding request
        test_result = gmaps.geocode("Boston, MA")
        if test_result:
            safe_print("✅ Google Maps API initialized and validated successfully")
            return True
        else:
            safe_print("❌ Google Maps API key validation failed")
            return False
            
    except Exception as e:
        safe_print(f"❌ Google Maps API initialization failed: {e}")
        gmaps = None
        return False

def load_stores_from_db():
    """Load stores from database"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute('SELECT * FROM stores ORDER BY name')
            stores = []
            for row in cursor.fetchall():
                stores.append({
                    'id': row['id'],
                    'name': row['name'],
                    'address': row['address'],
                    'chain': row['chain'],
                    'lat': row['lat'],
                    'lng': row['lng'],
                    'verified': row['verified'],
                    'geocoded_date': row['geocoded_date'],
                    'place_id': row['place_id'],
                    'location_type': row['location_type'],
                    'formatted_address': row['formatted_address']
                })
            return stores
    except Exception as e:
        safe_print(f"Error loading stores from database: {e}")
        return []

def save_store_to_db(store_data):
    """Save store to database"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO stores 
                (name, address, chain, lat, lng, verified, geocoded_date, place_id, location_type, formatted_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                store_data['name'],
                store_data['address'],
                store_data['chain'],
                store_data['lat'],
                store_data['lng'],
                store_data.get('verified', 'unverified'),
                store_data.get('geocoded_date'),
                store_data.get('place_id'),
                store_data.get('location_type'),
                store_data.get('formatted_address')
            ))
        return True
    except Exception as e:
        safe_print(f"Error saving store to database: {e}")
        return False

def check_user_permissions(user_id, required_role='user'):
    """Check user permissions"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute(
                'SELECT role FROM user_permissions WHERE user_id = ?',
                (str(user_id),)
            )
            result = cursor.fetchone()
            
            if not result:
                return required_role == 'user'  # Default users have 'user' role
            
            user_role = result['role']
            role_hierarchy = {'user': 0, 'moderator': 1, 'admin': 2}
            
            return role_hierarchy.get(user_role, 0) >= role_hierarchy.get(required_role, 0)
    except Exception as e:
        safe_print(f"Error checking permissions: {e}")
        return required_role == 'user'

def set_user_permission(user_id, role, granted_by, server_id=None):
    """Set user permissions"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO user_permissions 
                (user_id, role, server_id, granted_by)
                VALUES (?, ?, ?, ?)
            ''', (str(user_id), role, str(server_id) if server_id else None, str(granted_by)))
        return True
    except Exception as e:
        safe_print(f"Error setting permissions: {e}")
        return False

def save_location_to_db(user_id, channel_id, lat, lng, accuracy=None, store_name=None, distance=None, is_real_time=False):
    """Save location to database"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO user_locations 
                (user_id, channel_id, lat, lng, accuracy, store_name, distance, is_real_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(user_id), str(channel_id), lat, lng, accuracy, store_name, distance, is_real_time))
        return True
    except Exception as e:
        safe_print(f"Error saving location: {e}")
        return False

def get_user_location_history(user_id, limit=10):
    """Get user location history"""
    try:
        with get_db_connection() as conn:
            cursor = conn.execute('''
                SELECT * FROM user_locations 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (str(user_id), limit))
            return cursor.fetchall()
    except Exception as e:
        safe_print(f"Error getting location history: {e}")
        return []

def start_tracking_session(user_id, channel_id):
    """Start tracking session in database"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO tracking_sessions 
                (user_id, channel_id, active, started_at, last_update)
                VALUES (?, ?, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (str(user_id), str(channel_id)))
        return True
    except Exception as e:
        safe_print(f"Error starting tracking session: {e}")
        return False

def stop_tracking_session(user_id):
    """Stop tracking session"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                UPDATE tracking_sessions 
                SET active = FALSE 
                WHERE user_id = ?
            ''', (str(user_id),))
        return True
    except Exception as e:
        safe_print(f"Error stopping tracking session: {e}")
        return False

def geocode_store_address(store_data):
    """Enhanced geocoding with better error handling"""
    global gmaps
    
    if not gmaps:
        return {
            **store_data,
            "lat": 42.3601,  # Boston center
            "lng": -71.0589,
            "verified": "fallback",
            "geocoded_date": None,
            "place_id": None
        }
    
    try:
        # Enhanced search with multiple attempts
        search_queries = [
            f"{store_data['name']}, {store_data['address']}",
            f"{store_data['chain']} {store_data['address']}",
            store_data['address']
        ]
        
        for query in search_queries:
            try:
                result = gmaps.geocode(query)
                if result and len(result) > 0:
                    location = result[0]['geometry']['location']
                    place_id = result[0]['place_id']
                    location_type = result[0]['geometry'].get('location_type', 'APPROXIMATE')
                    formatted_address = result[0]['formatted_address']
                    
                    geocoded_store = {
                        **store_data,
                        "lat": round(location['lat'], 7),
                        "lng": round(location['lng'], 7),
                        "verified": "google_api",
                        "geocoded_date": datetime.utcnow().isoformat(),
                        "place_id": place_id,
                        "location_type": location_type,
                        "formatted_address": formatted_address
                    }
                    
                    # Save to database
                    save_store_to_db(geocoded_store)
                    return geocoded_store
                    
            except Exception as query_error:
                safe_print(f"Query '{query}' failed: {query_error}")
                continue
        
        # If all queries failed
        fallback_store = {
            **store_data,
            "lat": 42.3601,
            "lng": -71.0589,
            "verified": "failed_geocoding",
            "geocoded_date": None,
            "place_id": None
        }
        save_store_to_db(fallback_store)
        return fallback_store
            
    except Exception as e:
        safe_print(f"❌ Geocoding error for {store_data['name']}: {e}")
        fallback_store = {
            **store_data,
            "lat": 42.3601,
            "lng": -71.0589,
            "verified": "geocoding_error",
            "geocoded_date": None,
            "place_id": None
        }
        save_store_to_db(fallback_store)
        return fallback_store

def initialize_stores():
    """Initialize store database if empty"""
    existing_stores = load_stores_from_db()
    
    if existing_stores:
        safe_print(f"📍 Loaded {len(existing_stores)} stores from database")
        return existing_stores
    
    safe_print("📍 Initializing store database...")
    geocoded_stores = []
    
    for i, store_data in enumerate(STORE_ADDRESSES, 1):
        safe_print(f"[{i}/{len(STORE_ADDRESSES)}] Geocoding: {store_data['name']}")
        geocoded_store = geocode_store_address(store_data)
        geocoded_stores.append(geocoded_store)
        
        if gmaps:
            time.sleep(0.1)  # Rate limiting
    
    safe_print(f"✅ Initialized {len(geocoded_stores)} stores")
    return geocoded_stores

def get_store_branding(store_name):
    """Return store-specific branding"""
    store_lower = store_name.lower()
    
    if "target" in store_lower:
        return {
            "emoji": "🎯",
            "color": 0xCC0000,
            "logo": "https://logos-world.net/wp-content/uploads/2020/04/Target-Logo.png",
            "description": "Department Store • Clothing, Electronics, Home"
        }
    elif "walmart" in store_lower:
        return {
            "emoji": "🏪", 
            "color": 0x0071CE,
            "logo": "https://logos-world.net/wp-content/uploads/2020/05/Walmart-Logo.png",
            "description": "Superstore • Groceries, Electronics, Everything"
        }
    elif "best buy" in store_lower:
        return {
            "emoji": "🔌",
            "color": 0xFFE000,
            "logo": "https://logos-world.net/wp-content/uploads/2020/04/Best-Buy-Logo.png", 
            "description": "Electronics Store • Tech, Computers, Gaming"
        }
    elif "bjs" in store_lower:
        return {
            "emoji": "🛒",
            "color": 0xFF6B35,
            "logo": "https://logos-world.net/wp-content/uploads/2022/02/BJs-Wholesale-Club-Logo.png",
            "description": "Wholesale Club • Bulk Shopping, Membership Required"
        }
    else:
        return {
            "emoji": "🏢",
            "color": 0x7289DA,
            "logo": None,
            "description": "Store Location"
        }

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance using Haversine formula"""
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
    except:
        return 999

def find_closest_store(user_lat, user_lng):
    """Find the closest store"""
    try:
        stores = load_stores_from_db()
        min_distance = float('inf')
        closest_store = None
        
        for store in stores:
            distance = calculate_distance(user_lat, user_lng, store['lat'], store['lng'])
            if distance < min_distance:
                min_distance = distance
                closest_store = store
        
        return closest_store, min_distance
    except Exception as e:
        safe_print(f"Error finding closest store: {e}")
        return None, 999

def find_nearby_stores(user_lat, user_lng, radius_miles=5):
    """Find all stores within specified radius"""
    try:
        stores = load_stores_from_db()
        nearby_stores = []
        
        for store in stores:
            distance = calculate_distance(user_lat, user_lng, store['lat'], store['lng'])
            if distance <= radius_miles:
                nearby_stores.append({
                    'store': store,
                    'distance': distance
                })
        
        nearby_stores.sort(key=lambda x: x['distance'])
        return nearby_stores
    except Exception as e:
        safe_print(f"Error finding nearby stores: {e}")
        return []

# Bot events
@bot.event
async def on_ready():
    global bot_ready, bot_connected
    safe_print(f"🤖 Discord bot connected: {bot.user}")
    
    # Initialize database
    safe_print("🗄️ Initializing database...")
    init_database()
    
    # Initialize Google Maps
    safe_print("🗺️ Initializing Google Maps API...")
    api_available = initialize_google_maps()
    
    # Initialize stores
    safe_print("📍 Loading stores...")
    stores = initialize_stores()
    
    google_verified = len([s for s in stores if s.get('verified') == 'google_api'])
    
    safe_print(f"📍 Loaded {len(stores)} store locations:")
    safe_print(f"   ✅ {google_verified} Google-verified coordinates")
    
    bot_connected = True
    
    try:
        synced = await bot.tree.sync()
        safe_print(f"🔄 Synced {len(synced)} slash commands")
        bot_ready = True
        safe_print("✅ Bot is now fully ready!")
    except Exception as e:
        safe_print(f"❌ Failed to sync commands: {e}")

# Enhanced slash commands with permissions
@bot.tree.command(name="ping", description="Test if bot is working")
async def ping(interaction: discord.Interaction):
    """Test command"""
    try:
        google_status = "✅ Active" if gmaps else "❌ Not Available"
        stores = load_stores_from_db()
        await interaction.response.send_message(
            f"🏓 Pong! Bot is working!\n🗺️ Google Maps API: {google_status}\n📍 Stores: {len(stores)}"
        )
    except Exception as e:
        safe_print(f"Ping command error: {e}")

@bot.tree.command(name="location", description="Share your location with the team")
async def location_command(interaction: discord.Interaction):
    """Enhanced location sharing command"""
    global LOCATION_CHANNEL_ID, LOCATION_USER_INFO
    
    try:
        if not check_user_permissions(interaction.user.id, 'user'):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        LOCATION_CHANNEL_ID = interaction.channel.id
        
        user_key = f"{interaction.channel.id}_{interaction.user.id}"
        LOCATION_USER_INFO[user_key] = {
            'user_id': interaction.user.id,
            'username': interaction.user.display_name,
            'full_username': str(interaction.user),
            'avatar_url': interaction.user.display_avatar.url,
            'timestamp': discord.utils.utcnow()
        }
        
        embed = discord.Embed(
            title="📍 Enhanced Location Sharing",
            description=f"Hey {interaction.user.display_name}! Use the improved location system below!",
            color=0x5865F2
        )
        
        railway_url = os.getenv('RAILWAY_URL', 'https://web-production-f0220.up.railway.app')
        website_url = f"{railway_url}?user={interaction.user.id}&channel={interaction.channel.id}"
        
        embed.add_field(
            name="🔗 Location Link",
            value=f"[Click here to share location]({website_url})",
            inline=False
        )
        
        embed.add_field(
            name="🆕 New Features",
            value="• Fixed Google Maps integration\n• Persistent location history\n• Role-based permissions\n• Enhanced store filtering\n• Improved real-time tracking",
            inline=False
        )
        
        # Show location history
        history = get_user_location_history(interaction.user.id, 3)
        if history:
            history_text = "\n".join([
                f"• {row['store_name'] or 'Unknown'} ({row['distance']:.1f}mi) - {row['timestamp'][:16]}"
                for row in history
            ])
            embed.add_field(
                name="📊 Recent Locations",
                value=history_text,
                inline=False
            )
        
        embed.set_footer(text="Enhanced Location System • Database Powered • Fixed Google Maps")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        safe_print(f"Location command error: {e}")
        try:
            await interaction.response.send_message("❌ Error setting up location sharing")
        except:
            pass

@bot.tree.command(name="setperm", description="Set user permissions (Admin only)")
async def setperm_command(interaction: discord.Interaction, user: discord.Member, role: str):
    """Set user permissions"""
    try:
        # Check if user is admin
        if not check_user_permissions(interaction.user.id, 'admin'):
            await interaction.response.send_message("❌ You need admin permissions to use this command.", ephemeral=True)
            return
        
        if role not in ['user', 'moderator', 'admin']:
            await interaction.response.send_message("❌ Invalid role. Use: user, moderator, or admin", ephemeral=True)
            return
        
        success = set_user_permission(user.id, role, interaction.user.id, interaction.guild.id)
        
        if success:
            await interaction.response.send_message(f"✅ Set {user.display_name} role to **{role}**")
        else:
            await interaction.response.send_message("❌ Failed to set permissions")
            
    except Exception as e:
        safe_print(f"Setperm command error: {e}")
        await interaction.response.send_message("❌ Error setting permissions")

@bot.tree.command(name="history", description="View your location history")
async def history_command(interaction: discord.Interaction, limit: int = 10):
    """View location history"""
    try:
        if not check_user_permissions(interaction.user.id, 'user'):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return
        
        history = get_user_location_history(interaction.user.id, min(limit, 20))
        
        if not history:
            await interaction.response.send_message("📍 No location history found.")
            return
        
        embed = discord.Embed(
            title=f"📊 Location History for {interaction.user.display_name}",
            color=0x5865F2
        )
        
        for i, row in enumerate(history[:10], 1):
            store_name = row['store_name'] or 'Unknown Location'
            distance = f"{row['distance']:.1f}mi" if row['distance'] else 'N/A'
            timestamp = row['timestamp'][:16].replace('T', ' ')
            tracking_type = "🔄" if row['is_real_time'] else "📍"
            
            embed.add_field(
                name=f"{i}. {tracking_type} {store_name}",
                value=f"Distance: {distance}\nTime: {timestamp}",
                inline=True
            )
        
        embed.set_footer(text=f"Showing {len(history)} most recent locations")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        safe_print(f"History command error: {e}")
        await interaction.response.send_message("❌ Error retrieving location history")

@bot.tree.command(name="fixstore", description="Fix incorrect store data (Admin only)")
async def fixstore_command(interaction: discord.Interaction, old_name: str, new_name: str, new_address: str = None):
    """Fix store data - for correcting things like 'Target Boston South Bay' to 'Target Braintree'"""
    try:
        if not check_user_permissions(interaction.user.id, 'admin'):
            await interaction.response.send_message("❌ You need admin permissions to use this command.", ephemeral=True)
            return
        
        # Find and update the store
        with get_db_connection() as conn:
            # Check if store exists
            cursor = conn.execute('SELECT * FROM stores WHERE name = ?', (old_name,))
            store = cursor.fetchone()
            
            if not store:
                await interaction.response.send_message(f"❌ Store '{old_name}' not found in database.")
                return
            
            # Update the store
            if new_address:
                conn.execute(
                    'UPDATE stores SET name = ?, address = ? WHERE name = ?',
                    (new_name, new_address, old_name)
                )
                message = f"✅ Updated store:\n**Old:** {old_name}\n**New:** {new_name}\n**New Address:** {new_address}"
            else:
                conn.execute(
                    'UPDATE stores SET name = ? WHERE name = ?',
                    (new_name, old_name)
                )
                message = f"✅ Updated store name:\n**Old:** {old_name}\n**New:** {new_name}"
            
            # Update location history records too
            conn.execute(
                'UPDATE user_locations SET store_name = ? WHERE store_name = ?',
                (new_name, old_name)
            )
            
        await interaction.response.send_message(message)
        safe_print(f"Store data updated: {old_name} -> {new_name}")
        
    except Exception as e:
        safe_print(f"Fix store command error: {e}")
        await interaction.response.send_message("❌ Error updating store data")

@bot.tree.command(name="regeocodestore", description="Re-geocode a store with Google Maps (Admin only)")
async def regeocodestore_command(interaction: discord.Interaction, store_name: str):
    """Re-geocode a specific store to get updated coordinates"""
    try:
        if not check_user_permissions(interaction.user.id, 'admin'):
            await interaction.response.send_message("❌ You need admin permissions to use this command.", ephemeral=True)
            return
        
        await interaction.response.defer()  # This might take a moment
        
        # Find the store
        with get_db_connection() as conn:
            cursor = conn.execute('SELECT * FROM stores WHERE name LIKE ?', (f'%{store_name}%',))
            store = cursor.fetchone()
            
            if not store:
                await interaction.followup.send(f"❌ Store matching '{store_name}' not found.")
                return
        
        # Convert to dict for geocoding
        store_data = {
            'name': store['name'],
            'address': store['address'],
            'chain': store['chain']
        }
        
        # Re-geocode
        updated_store = geocode_store_address(store_data)
        
        embed = discord.Embed(
            title=f"🗺️ Re-geocoded: {updated_store['name']}",
            color=0x34A853 if updated_store['verified'] == 'google_api' else 0xFBBC04
        )
        
        embed.add_field(
            name="📍 New Coordinates",
            value=f"{updated_store['lat']:.6f}, {updated_store['lng']:.6f}",
            inline=True
        )
        
        embed.add_field(
            name="✅ Verification",
            value=updated_store['verified'],
            inline=True
        )
        
        if updated_store.get('formatted_address'):
            embed.add_field(
                name="🏠 Google Address",
                value=updated_store['formatted_address'],
                inline=False
            )
        
        if updated_store.get('place_id'):
            google_url = f"https://maps.google.com/maps/place/?q=place_id:{updated_store['place_id']}"
            embed.add_field(
                name="🗺️ Google Maps",
                value=f"[View on Google Maps]({google_url})",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        safe_print(f"Re-geocode command error: {e}")
        await interaction.followup.send("❌ Error re-geocoding store")

# Enhanced Flask routes with fixed Google Maps
@app.route('/', methods=['GET'])
def index():
    """Serve fixed location sharing page"""
    user_id = request.args.get('user')
    channel_id = request.args.get('channel')
    
    user_info_js = json.dumps({
        'user_id': user_id,
        'channel_id': channel_id,
        'google_maps_available': gmaps is not None
    }) if user_id and channel_id else 'null'
    
    google_api_key = os.getenv('GOOGLE_MAPS_API_KEY', '')
    stores = load_stores_from_db()
    
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enhanced Location Bot - Fixed Google Maps</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #4285F4 0%, #34A853 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }}

        .container {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 40px;
            max-width: 600px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}

        .logo {{
            font-size: 48px;
            margin-bottom: 16px;
            animation: bounce 2s infinite;
        }}

        @keyframes bounce {{
            0%, 20%, 50%, 80%, 100% {{ transform: translateY(0); }}
            40% {{ transform: translateY(-10px); }}
            60% {{ transform: translateY(-5px); }}
        }}

        h1 {{
            color: #2d3748;
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
        }}

        .subtitle {{
            color: #718096;
            font-size: 16px;
            margin-bottom: 32px;
        }}

        .fix-badge {{
            background: linear-gradient(135deg, #34A853, #0F9D58);
            color: white;
            padding: 12px;
            border-radius: 12px;
            margin-bottom: 24px;
            font-size: 14px;
            font-weight: 500;
        }}

        .location-button {{
            background: linear-gradient(135deg, #4285F4 0%, #34A853 100%);
            color: white;
            border: none;
            padding: 16px 32px;
            border-radius: 16px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 25px rgba(66, 133, 244, 0.3);
            margin-bottom: 24px;
            width: 100%;
        }}

        .location-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 35px rgba(66, 133, 244, 0.4);
        }}

        .location-button:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}

        #map {{
            height: 350px;
            width: 100%;
            border-radius: 12px;
            margin: 20px 0;
            display: none;
            border: 1px solid #e2e8f0;
        }}

        .status {{
            margin: 24px 0;
            padding: 16px;
            border-radius: 12px;
            font-weight: 500;
            transition: all 0.3s ease;
            display: none;
        }}

        .status.success {{
            background: linear-gradient(135deg, #34A853, #0F9D58);
            color: white;
        }}

        .status.error {{
            background: linear-gradient(135deg, #EA4335, #D33B2C);
            color: white;
        }}

        .status.info {{
            background: linear-gradient(135deg, #4285F4, #3367D6);
            color: white;
        }}

        .loading {{
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

        .store-filters {{
            margin: 20px 0;
            display: none;
        }}

        .filter-button {{
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid #e2e8f0;
            padding: 8px 16px;
            margin: 4px;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
        }}

        .filter-button.active {{
            background: #4285F4;
            color: white;
        }}

        .nearby-stores {{
            margin-top: 24px;
            text-align: left;
            display: none;
            max-height: 300px;
            overflow-y: auto;
        }}

        .store-item {{
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            transition: all 0.3s ease;
            cursor: pointer;
        }}

        .store-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
        }}

        .store-item.google-verified {{
            border-left: 4px solid #34A853;
        }}

        .verification-badge {{
            font-size: 12px;
            padding: 2px 6px;
            border-radius: 6px;
            margin-left: 8px;
        }}

        .google-badge {{
            background: #E8F5E8;
            color: #137333;
        }}

        .fallback-badge {{
            background: #FEF7E0;
            color: #B7791F;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🗺️</div>
        <h1>Enhanced Location Sharing</h1>
        <p class="subtitle">Fixed Google Maps integration with enhanced features!</p>
        
        <div class="fix-badge">
            ✅ FIXED: Google Maps API • Advanced Marker API • Database persistence
        </div>
        
        <button id="shareLocationBtn" class="location-button">
            📍 Share My Location
        </button>
        
        <div class="store-filters" id="storeFilters">
            <button class="filter-button active" data-chain="all">All Stores</button>
            <button class="filter-button" data-chain="target">🎯 Target</button>
            <button class="filter-button" data-chain="walmart">🏪 Walmart</button>
            <button class="filter-button" data-chain="best buy">🔌 Best Buy</button>
            <button class="filter-button" data-chain="bjs">🛒 BJ's</button>
        </div>
        
        <div id="map"></div>
        <div id="status" class="status"></div>
        <div id="nearbyStores" class="nearby-stores"></div>
        
        <div class="footer" style="margin-top: 32px; color: #a0aec0; font-size: 14px;">
            <p>🔧 Fixed Google Maps API integration</p>
            <p>🗄️ Database-powered location history</p>
            <p>🎯 Enhanced store filtering and search</p>
        </div>
    </div>

    <script>
        const USER_INFO = {user_info_js};
        const STORES = {json.dumps(stores)};
        const GOOGLE_API_KEY = '{google_api_key}';
        
        let map;
        let userMarker;
        let storeMarkers = [];
        let userLocation = null;
        let currentFilter = 'all';
        
        // Load Google Maps API dynamically with error handling
        function loadGoogleMapsAPI() {{
            if (typeof google !== 'undefined') {{
                initializeMap();
                return;
            }}
            
            if (!GOOGLE_API_KEY) {{
                showStatus('❌ Google Maps API key not configured', 'error');
                return;
            }}
            
            const script = document.createElement('script');
            script.src = `https://maps.googleapis.com/maps/api/js?key=${{GOOGLE_API_KEY}}&libraries=marker&callback=initializeMap`;
            script.onerror = () => {{
                showStatus('❌ Failed to load Google Maps API', 'error');
            }};
            document.head.appendChild(script);
        }}
        
        function initializeMap() {{
            try {{
                map = new google.maps.Map(document.getElementById('map'), {{
                    zoom: 12,
                    center: {{ lat: 42.3601, lng: -71.0589 }},
                    mapId: 'DEMO_MAP_ID', // Required for Advanced Markers
                    styles: [
                        {{
                            featureType: 'poi',
                            elementType: 'labels',
                            stylers: [{{ visibility: 'off' }}]
                        }}
                    ]
                }});
                
                showStatus('✅ Google Maps loaded successfully', 'success');
                setTimeout(() => {{
                    document.getElementById('status').style.display = 'none';
                }}, 2000);
                
            }} catch (error) {{
                console.error('Map initialization error:', error);
                showStatus('❌ Map initialization failed', 'error');
            }}
        }}
        
        function showUserLocation(lat, lng) {{
            if (!map) return;
            
            userLocation = {{ lat, lng }};
            
            try {{
                // Center map on user
                map.setCenter(userLocation);
                map.setZoom(14);
                
                // Remove existing user marker
                if (userMarker) {{
                    userMarker.map = null;
                }}
                
                // Create user marker with Advanced Marker API
                const userIcon = document.createElement('div');
                userIcon.innerHTML = '📍';
                userIcon.style.fontSize = '24px';
                
                userMarker = new google.maps.marker.AdvancedMarkerElement({{
                    map: map,
                    position: userLocation,
                    content: userIcon,
                    title: 'Your Location'
                }});
                
                // Show nearby stores
                showNearbyStoresOnMap(lat, lng);
                showNearbyStoresList(lat, lng);
                document.getElementById('storeFilters').style.display = 'block';
                
            }} catch (error) {{
                console.error('Error showing user location:', error);
                showStatus('❌ Error displaying location on map', 'error');
            }}
        }}
        
        function showNearbyStoresOnMap(userLat, userLng) {{
            // Clear existing markers
            storeMarkers.forEach(marker => marker.map = null);
            storeMarkers = [];
            
            const nearbyStores = findNearbyStores(userLat, userLng, 10);
            const filteredStores = filterStores(nearbyStores);
            
            filteredStores.slice(0, 20).forEach(item => {{
                const store = item.store;
                
                try {{
                    const storeIcon = document.createElement('div');
                    storeIcon.innerHTML = getStoreEmoji(store.chain);
                    storeIcon.style.fontSize = '20px';
                    storeIcon.style.cursor = 'pointer';
                    
                    const marker = new google.maps.marker.AdvancedMarkerElement({{
                        map: map,
                        position: {{ lat: store.lat, lng: store.lng }},
                        content: storeIcon,
                        title: `${{store.name}} (${{item.distance.toFixed(1)}} miles)`
                    }});
                    
                    // Add click listener
                    marker.addListener('click', () => {{
                        selectStore(store);
                    }});
                    
                    storeMarkers.push(marker);
                    
                }} catch (error) {{
                    console.error('Error creating store marker:', error);
                }}
            }});
        }}
        
        function showNearbyStoresList(userLat, userLng) {{
            const nearbyStores = findNearbyStores(userLat, userLng, 10);
            const filteredStores = filterStores(nearbyStores);
            const storesContainer = document.getElementById('nearbyStores');
            
            if (filteredStores.length === 0) {{
                storesContainer.innerHTML = '<p>No stores found within 10 miles.</p>';
                storesContainer.style.display = 'block';
                return;
            }}
            
            const storesHTML = filteredStores.slice(0, 15).map(item => {{
                const store = item.store;
                const distance = item.distance;
                const verification = store.verified === 'google_api' ? 'google-badge' : 'fallback-badge';
                const verificationText = store.verified === 'google_api' ? '✅ Google' : '⚠️ Fallback';
                
                return `
                    <div class="store-item ${{store.verified === 'google_api' ? 'google-verified' : ''}}" 
                         onclick="selectStore(${{JSON.stringify(store).replace(/"/g, '&quot;')}})">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong>${{getStoreEmoji(store.chain)}} ${{store.name}}</strong>
                                <span class="verification-badge ${{verification}}">${{verificationText}}</span>
                                <br>
                                <small style="color: #666;">${{store.address}}</small>
                            </div>
                            <div style="text-align: right;">
                                <strong>${{distance.toFixed(1)}} mi</strong>
                                <br>
                                <small>${{getDistanceStatus(distance)}}</small>
                            </div>
                        </div>
                    </div>
                `;
            }}).join('');
            
            storesContainer.innerHTML = storesHTML;
            storesContainer.style.display = 'block';
        }}
        
        function filterStores(nearbyStores) {{
            if (currentFilter === 'all') return nearbyStores;
            return nearbyStores.filter(item => 
                item.store.chain.toLowerCase().includes(currentFilter.toLowerCase())
            );
        }}
        
        function getStoreEmoji(chain) {{
            const chainLower = chain.toLowerCase();
            if (chainLower.includes('target')) return '🎯';
            if (chainLower.includes('walmart')) return '🏪';
            if (chainLower.includes('best buy')) return '🔌';
            if (chainLower.includes('bjs')) return '🛒';
            return '🏢';
        }}
        
        function getDistanceStatus(distance) {{
            if (distance <= 0.2) return '🟢 AT STORE';
            if (distance <= 1.0) return '🟡 NEARBY';
            return '🔴 FAR';
        }}
        
        function findNearbyStores(userLat, userLng, radiusMiles) {{
            const nearbyStores = [];
            
            STORES.forEach(store => {{
                const distance = calculateDistance(userLat, userLng, store.lat, store.lng);
                if (distance <= radiusMiles) {{
                    nearbyStores.push({{ store: store, distance: distance }});
                }}
            }});
            
            nearbyStores.sort((a, b) => a.distance - b.distance);
            return nearbyStores;
        }}
        
        function calculateDistance(lat1, lng1, lat2, lng2) {{
            const R = 3958.8; // Earth radius in miles
            const lat1Rad = lat1 * Math.PI / 180;
            const lng1Rad = lng1 * Math.PI / 180;
            const lat2Rad = lat2 * Math.PI / 180;
            const lng2Rad = lng2 * Math.PI / 180;
            
            const dlat = lat2Rad - lat1Rad;
            const dlng = lng2Rad - lng1Rad;
            
            const a = Math.sin(dlat/2)**2 + Math.cos(lat1Rad) * Math.cos(lat2Rad) * Math.sin(dlng/2)**2;
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            
            return R * c;
        }}
        
        function showStatus(message, type) {{
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = `status ${{type}}`;
            statusDiv.style.display = 'block';
        }}
        
        async function selectStore(store) {{
            if (!userLocation) {{
                showStatus('❌ Please share your location first', 'error');
                return;
            }}
            
            showStatus(`📍 Checking in to ${{store.name}}...`, 'info');
            
            try {{
                const distance = calculateDistance(
                    userLocation.lat, userLocation.lng,
                    store.lat, store.lng
                );
                
                const response = await fetch('/webhook/location', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        latitude: userLocation.lat,
                        longitude: userLocation.lng,
                        accuracy: 10,
                        isManualCheckIn: true,
                        selectedStore: store.name,
                        user_id: USER_INFO?.user_id
                    }})
                }});
                
                if (response.ok) {{
                    showStatus(`✅ Checked in to ${{store.name}}!`, 'success');
                }} else {{
                    showStatus('❌ Failed to check in', 'error');
                }}
                
            }} catch (error) {{
                console.error('Check-in error:', error);
                showStatus('❌ Check-in failed', 'error');
            }}
        }}
        
        // Event listeners
        document.getElementById('shareLocationBtn').addEventListener('click', function() {{
            const button = this;
            
            if (!navigator.geolocation) {{
                showStatus('❌ Geolocation not supported by this browser', 'error');
                return;
            }}
            
            button.disabled = true;
            button.innerHTML = '<div class="loading"></div> Getting location...';
            showStatus('📍 Requesting location access...', 'info');
            
            navigator.geolocation.getCurrentPosition(
                position => {{
                    const latitude = position.coords.latitude;
                    const longitude = position.coords.longitude;
                    
                    // Show on map
                    document.getElementById('map').style.display = 'block';
                    showUserLocation(latitude, longitude);
                    
                    button.innerHTML = '✅ Location Found!';
                    button.style.background = 'linear-gradient(135deg, #34A853, #0F9D58)';
                    showStatus('📍 Location found! Click stores below to check in.', 'success');
                    
                    setTimeout(() => {{
                        button.disabled = false;
                        button.innerHTML = '📍 Share My Location';
                        button.style.background = 'linear-gradient(135deg, #4285F4 0%, #34A853 100%)';
                    }}, 3000);
                }},
                error => {{
                    let errorMessage = 'Failed to get location. ';
                    switch(error.code) {{
                        case error.PERMISSION_DENIED:
                            errorMessage += 'Please allow location access.';
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage += 'Location information unavailable.';
                            break;
                        case error.TIMEOUT:
                            errorMessage += 'Location request timed out.';
                            break;
                        default:
                            errorMessage += 'Unknown error occurred.';
                    }}
                    
                    showStatus(`❌ ${{errorMessage}}`, 'error');
                    button.disabled = false;
                    button.innerHTML = '📍 Share My Location';
                }},
                {{ 
                    enableHighAccuracy: true, 
                    timeout: 15000, 
                    maximumAge: 300000 
                }}
            );
        }});
        
        // Store filter buttons
        document.getElementById('storeFilters').addEventListener('click', function(e) {{
            if (e.target.classList.contains('filter-button')) {{
                // Update active button
                document.querySelectorAll('.filter-button').forEach(btn => btn.classList.remove('active'));
                e.target.classList.add('active');
                
                // Update filter
                currentFilter = e.target.dataset.chain;
                
                // Refresh store display
                if (userLocation) {{
                    showNearbyStoresOnMap(userLocation.lat, userLocation.lng);
                    showNearbyStoresList(userLocation.lat, userLocation.lng);
                }}
            }}
        }});
        
        // Load Google Maps when page loads
        window.initializeMap = initializeMap;
        loadGoogleMapsAPI();
    </script>
</body>
</html>
    '''

@app.route('/health', methods=['GET'])
def health():
    """Enhanced health check"""
    try:
        stores = load_stores_from_db()
        google_verified = len([s for s in stores if s.get('verified') == 'google_api'])
        
        with get_db_connection() as conn:
            # Count active tracking sessions
            cursor = conn.execute('SELECT COUNT(*) as count FROM tracking_sessions WHERE active = TRUE')
            active_sessions = cursor.fetchone()['count']
            
            # Count total location records
            cursor = conn.execute('SELECT COUNT(*) as count FROM user_locations')
            total_locations = cursor.fetchone()['count']
        
        return jsonify({
            "status": "healthy",
            "bot_connected": bot_connected,
            "bot_ready": bot_ready,
            "google_maps_api": gmaps is not None,
            "database": "connected",
            "stores_total": len(stores),
            "stores_google_verified": google_verified,
            "google_verification_rate": round((google_verified / len(stores)) * 100, 1) if stores else 0,
            "active_tracking_sessions": active_sessions,
            "total_location_records": total_locations
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Enhanced location webhook with database persistence"""
    try:
        data = request.get_json()
        if not data or not bot_connected or not bot_ready:
            return jsonify({"error": "Bot not ready"}), 503
        
        # Save to database
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        user_id = data.get('user_id')
        
        if user_id:
            closest_store, distance = find_closest_store(lat, lng)
            store_name = closest_store['name'] if closest_store else None
            
            save_location_to_db(
                user_id=user_id,
                channel_id=LOCATION_CHANNEL_ID,
                lat=lat,
                lng=lng,
                accuracy=data.get('accuracy'),
                store_name=store_name,
                distance=distance,
                is_real_time=data.get('isRealTime', False)
            )
        
        # Send to Discord
        if bot.loop and not bot.loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                post_location_to_discord(data), 
                bot.loop
            )
            
            result = future.result(timeout=15)
            if result:
                return jsonify({"status": "success", "message": "Location shared successfully"}), 200
            else:
                return jsonify({"error": "Failed to post to Discord"}), 500
        else:
            return jsonify({"error": "Bot loop not available"}), 503
        
    except Exception as e:
        safe_print(f"❌ Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

async def post_location_to_discord(location_data):
    """Enhanced Discord posting with database integration"""
    global LOCATION_CHANNEL_ID, bot_ready, bot_connected, LOCATION_USER_INFO
    
    try:
        if not bot_connected or not bot_ready or not LOCATION_CHANNEL_ID:
            return False
        
        channel = bot.get_channel(LOCATION_CHANNEL_ID)
        if not channel:
            return False
        
        lat = float(location_data['latitude'])
        lng = float(location_data['longitude'])
        accuracy = location_data.get('accuracy', 'Unknown')
        is_manual = location_data.get('isManualCheckIn', False)
        selected_store = location_data.get('selectedStore', None)
        user_id = location_data.get('user_id', None)
        
        # Get user info
        username = "Someone"
        avatar_url = None
        
        if user_id:
            user_key = f"{LOCATION_CHANNEL_ID}_{user_id}"
            if user_key in LOCATION_USER_INFO:
                user_info = LOCATION_USER_INFO[user_key]
                username = user_info['username']
                avatar_url = user_info['avatar_url']
        
        # Find closest store
        closest_store, distance = find_closest_store(lat, lng)
        if not closest_store:
            return False
        
        # Handle manual check-in
        if is_manual and selected_store:
            stores = load_stores_from_db()
            for store in stores:
                if store['name'] == selected_store:
                    closest_store = store
                    distance = calculate_distance(lat, lng, store['lat'], store['lng'])
                    break
        
        # Get store branding
        branding = get_store_branding(closest_store['name'])
        
        # Create enhanced embed
        title_text = f"{branding['emoji']} {username} is {distance:.1f} miles from {closest_store['name']}"
        
        embed = discord.Embed(
            title=title_text,
            description=f"**{username}** {'manually selected' if is_manual else 'is at'} **{closest_store['name']}**",
            color=branding['color']
        )
        
        if branding['logo']:
            embed.set_thumbnail(url=branding['logo'])
        
        if avatar_url:
            embed.set_author(name=f"Location Update from {username}", icon_url=avatar_url)
        
        # Enhanced fields
        embed.add_field(name="🏪 Store", value=closest_store['name'], inline=True)
        embed.add_field(name="📏 Distance", value=f"{distance:.1f} miles", inline=True)
        embed.add_field(name="🎯 Accuracy", value=f"±{accuracy}m", inline=True)
        
        # Google Maps link
        if closest_store.get('place_id'):
            google_maps_url = f"https://maps.google.com/maps/place/?q=place_id:{closest_store['place_id']}"
            embed.add_field(name="🗺️ Google Maps", value=f"[View Store]({google_maps_url})", inline=True)
        
        # Address
        embed.add_field(name="📍 Address", value=closest_store['address'], inline=False)
        
        # Coordinates
        embed.add_field(
            name="🧭 Coordinates",
            value=f"**User:** {lat:.6f}, {lng:.6f}\n**Store:** {closest_store['lat']:.6f}, {closest_store['lng']:.6f}",
            inline=True
        )
        
        # Enhanced footer
        verification_status = "Google Verified" if closest_store.get('verified') == 'google_api' else "Standard"
        embed.set_footer(text=f"Enhanced Location System • Database Powered • {verification_status}")
        embed.timestamp = discord.utils.utcnow()
        
        await channel.send(embed=embed)
        safe_print(f"✅ Posted enhanced location to Discord for {username}")
        return True
        
    except Exception as e:
        safe_print(f"❌ Error posting to Discord: {e}")
        return False

def run_flask():
    """Run Flask server"""
    try:
        port = int(os.getenv('PORT', 5000))
        safe_print(f"🌐 Starting enhanced Flask server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        safe_print(f"❌ Flask startup error: {e}")

def main():
    """Enhanced main function"""
    safe_print("=== Starting Enhanced Location Bot with Fixes ===")
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        safe_print("❌ DISCORD_TOKEN environment variable not found!")
        return
    
    GOOGLE_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
    if not GOOGLE_API_KEY:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - bot will use fallback coordinates")
    else:
        safe_print("✅ Google Maps API key found")
    
    # Start Discord bot
    def start_bot():
        safe_print("🤖 Starting Discord bot...")
        try:
            bot.run(TOKEN)
        except Exception as e:
            safe_print(f"❌ Bot error: {e}")
    
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Wait for bot connection
    safe_print("⏰ Waiting for Discord bot to connect...")
    max_wait = 60
    waited = 0
    while not bot_connected and waited < max_wait:
        time.sleep(1)
        waited += 1
        if waited % 10 == 0:
            safe_print(f"⏰ Still waiting... ({waited}s)")
    
    if bot_connected:
        safe_print("✅ Discord bot connected!")
        time.sleep(3)
    else:
        safe_print("⚠️ Bot not ready yet, but starting Flask anyway...")
    
    # Start Flask server
    try:
        run_flask()
    except Exception as e:
        safe_print(f"❌ Critical error: {e}")

if __name__ == "__main__":
    main()
