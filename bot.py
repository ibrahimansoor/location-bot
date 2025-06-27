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

# Flask app
app = Flask(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Google Maps client
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
                store_address TEXT,
                store_place_id TEXT,
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
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - real-time search disabled")
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

def search_nearby_stores(lat, lng, radius_meters=16000):
    """Search for Target, Walmart, Best Buy, and BJ's stores near location using Google Places"""
    if not gmaps:
        safe_print("❌ Google Maps API not available for real-time search")
        return []
    
    try:
        all_stores = []
        
        # Define the store chains we want to find with multiple search terms
        store_queries = [
            {"query": "Target", "chain": "Target", "icon": "🎯", "keywords": ["Target", "Super Target"]},
            {"query": "Walmart", "chain": "Walmart", "icon": "🏪", "keywords": ["Walmart", "Walmart Supercenter"]},
            {"query": "Best Buy", "chain": "Best Buy", "icon": "🔌", "keywords": ["Best Buy"]},
            {"query": "BJ's Wholesale Club", "chain": "BJs", "icon": "🛒", "keywords": ["BJ's", "BJs Wholesale", "BJ's Wholesale Club"]}
        ]
        
        location = (lat, lng)
        
        for store_info in store_queries:
            try:
                safe_print(f"🔍 Searching for {store_info['query']} within {radius_meters/1000:.1f}km of {lat:.4f}, {lng:.4f}")
                
                # Try multiple search approaches for better coverage
                for keyword in store_info['keywords']:
                    try:
                        # Use Places API nearby search
                        places_result = gmaps.places_nearby(
                            location=location,
                            radius=radius_meters,
                            keyword=keyword,
                            type='store'
                        )
                        
                        found_count = len(places_result.get('results', []))
                        safe_print(f"📍 Found {found_count} {keyword} locations")
                        
                        for place in places_result.get('results', []):
                            try:
                                place_lat = place['geometry']['location']['lat']
                                place_lng = place['geometry']['location']['lng']
                                
                                # Calculate distance
                                distance = calculate_distance(lat, lng, place_lat, place_lng)
                                
                                # Skip if we already have this place (avoid duplicates)
                                place_id = place['place_id']
                                if any(store.get('place_id') == place_id for store in all_stores):
                                    continue
                        
                        # Get detailed place information
                        place_details = gmaps.place(
                            place_id=place['place_id'],
                            fields=[
                                'name', 'formatted_address', 'place_id', 'geometry', 
                                'rating', 'user_ratings_total', 'formatted_phone_number',
                                'opening_hours', 'website', 'price_level',
                                'business_status', 'plus_code'
                            ]
                        )
                        
                        details = place_details.get('result', {})
                        
                        # Check if store is currently open
                        opening_hours = details.get('opening_hours', {})
                        is_open = opening_hours.get('open_now', None)
                        hours_text = None
                        if opening_hours.get('weekday_text'):
                            # Get today's hours
                            today = datetime.utcnow().weekday()  # Monday is 0
                            if today < len(opening_hours['weekday_text']):
                                hours_text = opening_hours['weekday_text'][today]
                        
                        store_data = {
                            'name': details.get('name', place.get('name', 'Unknown Store')),
                            'address': details.get('formatted_address', place.get('vicinity', 'Unknown Address')),
                            'place_id': place['place_id'],
                            'lat': place_lat,
                            'lng': place_lng,
                            'chain': store_info['chain'],
                            'icon': store_info['icon'],
                            'distance': distance,
                            'rating': details.get('rating'),
                            'rating_count': details.get('user_ratings_total'),
                            'phone': details.get('formatted_phone_number'),
                            'website': details.get('website'),
                            'is_open': is_open,
                            'hours_today': hours_text,
                            'price_level': details.get('price_level'),
                            'business_status': details.get('business_status'),
                            'verified': 'google_places',
                            'search_query': store_info['query'],
                            'plus_code': details.get('plus_code', {}).get('global_code')
                        }
                        
                        all_stores.append(store_data)
                        
                    except Exception as place_error:
                        safe_print(f"❌ Error processing place: {place_error}")
                        continue
                
                # Small delay to respect API limits
                time.sleep(0.2)
                
            except Exception as search_error:
                safe_print(f"❌ Error searching for {store_info['query']}: {search_error}")
                continue
        
        # Sort by distance
        all_stores.sort(key=lambda x: x['distance'])
        
        safe_print(f"✅ Found {len(all_stores)} total stores within {radius_meters/1000:.1f}km")
        return all_stores
        
    except Exception as e:
        safe_print(f"❌ Error in nearby store search: {e}")
        return []

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

def get_store_branding(chain):
    """Return store-specific branding"""
    branding_map = {
        "Target": {
            "emoji": "🎯",
            "color": 0xCC0000,
            "description": "Department Store"
        },
        "Walmart": {
            "emoji": "🏪", 
            "color": 0x0071CE,
            "description": "Superstore"
        },
        "Best Buy": {
            "emoji": "🔌",
            "color": 0xFFE000,
            "description": "Electronics Store"
        },
        "BJs": {
            "emoji": "🛒",
            "color": 0xFF6B35,
            "description": "Wholesale Club"
        }
    }
    
    return branding_map.get(chain, {
        "emoji": "🏢",
        "color": 0x7289DA,
        "description": "Store"
    })

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
                return required_role == 'user'
            
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

def save_location_to_db(user_id, channel_id, lat, lng, accuracy=None, store_name=None, store_address=None, store_place_id=None, distance=None, is_real_time=False):
    """Save location to database"""
    try:
        with get_db_connection() as conn:
            conn.execute('''
                INSERT INTO user_locations 
                (user_id, channel_id, lat, lng, accuracy, store_name, store_address, store_place_id, distance, is_real_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(user_id), str(channel_id), lat, lng, accuracy, store_name, store_address, store_place_id, distance, is_real_time))
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
    
    bot_connected = True
    
    try:
        synced = await bot.tree.sync()
        safe_print(f"🔄 Synced {len(synced)} slash commands")
        bot_ready = True
        safe_print("✅ Bot is now ready with real-time Google Places integration!")
    except Exception as e:
        safe_print(f"❌ Failed to sync commands: {e}")

# Bot commands
@bot.tree.command(name="ping", description="Test if bot is working")
async def ping(interaction: discord.Interaction):
    """Enhanced ping with real-time search status"""
    try:
        google_status = "✅ Real-time Search Active" if gmaps else "❌ Not Available"
        
        embed = discord.Embed(
            title="🏓 Real-Time Location Bot Status",
            description="Dynamic Google Places integration",
            color=0x00FF00 if gmaps else 0xFFAA00
        )
        
        embed.add_field(
            name="🤖 Discord Bot",
            value="✅ Connected",
            inline=True
        )
        
        embed.add_field(
            name="🗺️ Google Places API",
            value=google_status,
            inline=True
        )
        
        embed.add_field(
            name="🔍 Search Method",
            value="🆕 Real-time Places Search" if gmaps else "❌ Static Database Only",
            inline=True
        )
        
        # API Key status
        api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        api_status = "🔑 Configured" if api_key else "❌ Missing"
        embed.add_field(
            name="🔐 API Key Status",
            value=api_status,
            inline=True
        )
        
        embed.add_field(
            name="🎯 Features",
            value="• Live store search\n• Accurate addresses\n• No duplicates\n• Real-time data",
            inline=False
        )
        
        embed.set_footer(text="Real-Time Location Bot • Google Places Powered")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        safe_print("Real-time ping command executed successfully")
        
    except Exception as e:
        safe_print(f"Ping command error: {e}")
        await interaction.response.send_message("❌ Error checking bot status")

@bot.tree.command(name="location", description="Share your location with real-time store search")
async def location_command(interaction: discord.Interaction):
    """Enhanced location sharing with real-time Google Places"""
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
            title="🔍 Real-Time Location Sharing",
            description=f"Hey {interaction.user.display_name}! Use the new real-time store search!",
            color=0x5865F2
        )
        
        railway_url = os.getenv('RAILWAY_URL', 'https://web-production-f0220.up.railway.app')
        website_url = f"{railway_url}?user={interaction.user.id}&channel={interaction.channel.id}"
        
        embed.add_field(
            name="🔗 Real-Time Location Link",
            value=f"[Click here for live store search]({website_url})",
            inline=False
        )
        
        embed.add_field(
            name="🆕 Real-Time Features",
            value="• Live Google Places search\n• Always accurate and up-to-date\n• No duplicate stores\n• Real store addresses\n• Current ratings & info",
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
        
        embed.set_footer(text="Real-Time Location System • Google Places API • Live Search")
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

# Enhanced Flask routes with real-time Google Places search
@app.route('/', methods=['GET'])
def index():
    """Serve real-time location sharing page with Google Places integration"""
    user_id = request.args.get('user')
    channel_id = request.args.get('channel')
    
    user_info_js = json.dumps({
        'user_id': user_id,
        'channel_id': channel_id,
        'google_maps_available': gmaps is not None
    }) if user_id and channel_id else 'null'
    
    google_api_key = os.getenv('GOOGLE_MAPS_API_KEY', '')
    
    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Real-Time Location Bot - Live Google Places Search</title>
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

        .realtime-badge {{
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
            max-height: 400px;
            overflow-y: auto;
        }}

        .store-item {{
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            transition: all 0.3s ease;
            cursor: pointer;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }}

        .store-item:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
            border-color: #4285F4;
        }}

        .store-item.google-verified {{
            border-left: 4px solid #34A853;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.95), rgba(232, 245, 232, 0.3));
        }}

        .realtime-badge-small {{
            background: linear-gradient(135deg, #34A853, #0F9D58);
            color: white;
            font-size: 10px;
            padding: 3px 8px;
            border-radius: 12px;
            margin-left: 8px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .store-status {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 8px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .store-status.open {{
            background: #E8F5E8;
            color: #137333;
        }}

        .store-status.closed {{
            background: #FEF7E0;
            color: #B7791F;
        }}

        .store-status.unknown {{
            background: #F3F4F6;
            color: #6B7280;
        }}

        .distance-badge {{
            background: linear-gradient(135deg, #4285F4, #3367D6);
            color: white;
            padding: 8px 12px;
            border-radius: 12px;
            text-align: center;
            font-weight: 600;
        }}

        .distance-badge.nearby {{
            background: linear-gradient(135deg, #34A853, #0F9D58);
        }}

        .distance-badge.far {{
            background: linear-gradient(135deg, #EA4335, #D33B2C);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🔍</div>
        <h1>Real-Time Location Sharing</h1>
        <p class="subtitle">Live Google Places search - always accurate!</p>
        
        <div class="realtime-badge">
            🔍 REAL-TIME: Live Google Places API • No static database • Always current
        </div>
        
        <button id="shareLocationBtn" class="location-button">
            📍 Search Nearby Stores
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
            <p>🔍 Real-time Google Places search</p>
            <p>📍 Always current, accurate store data</p>
            <p>🚫 No static database or duplicates</p>
        </div>
    </div>

    <script>
        const USER_INFO = {user_info_js};
        const GOOGLE_API_KEY = '{google_api_key}';
        
        let map;
        let userMarker;
        let storeMarkers = [];
        let userLocation = null;
        let currentFilter = 'all';
        let nearbyStores = [];
        
        // Load Google Maps API dynamically
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
            script.src = `https://maps.googleapis.com/maps/api/js?key=${{GOOGLE_API_KEY}}&libraries=marker,places&callback=initializeMap`;
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
                    mapId: 'DEMO_MAP_ID',
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
        
        async function searchNearbyStores(lat, lng) {{
            showStatus('🔍 Searching for nearby stores in real-time...', 'info');
            
            try {{
                const response = await fetch('/api/search-stores', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        latitude: lat,
                        longitude: lng,
                        user_id: USER_INFO?.user_id
                    }})
                }});
                
                if (!response.ok) {{
                    throw new Error('Search failed');
                }}
                
                const data = await response.json();
                nearbyStores = data.stores || [];
                
                showStatus(`✅ Found ${{nearbyStores.length}} stores nearby`, 'success');
                
                // Show stores on map and list
                showStoresOnMap();
                showStoresList();
                
                document.getElementById('storeFilters').style.display = 'block';
                
            }} catch (error) {{
                console.error('Store search error:', error);
                showStatus('❌ Failed to search for stores', 'error');
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
                
                // Create user marker
                const userIcon = document.createElement('div');
                userIcon.innerHTML = '📍';
                userIcon.style.fontSize = '24px';
                
                userMarker = new google.maps.marker.AdvancedMarkerElement({{
                    map: map,
                    position: userLocation,
                    content: userIcon,
                    title: 'Your Location'
                }});
                
                // Search for nearby stores
                searchNearbyStores(lat, lng);
                
            }} catch (error) {{
                console.error('Error showing user location:', error);
                showStatus('❌ Error displaying location on map', 'error');
            }}
        }}
        
        function showStoresOnMap() {{
            // Clear existing markers
            storeMarkers.forEach(marker => marker.map = null);
            storeMarkers = [];
            
            const filteredStores = filterStores(nearbyStores);
            
            filteredStores.slice(0, 20).forEach(store => {{
                try {{
                    const storeIcon = document.createElement('div');
                    storeIcon.innerHTML = getStoreEmoji(store.chain);
                    storeIcon.style.fontSize = '20px';
                    storeIcon.style.cursor = 'pointer';
                    
                    const marker = new google.maps.marker.AdvancedMarkerElement({{
                        map: map,
                        position: {{ lat: store.lat, lng: store.lng }},
                        content: storeIcon,
                        title: `${{store.name}} (${{store.distance.toFixed(1)}} miles)`
                    }});
                    
                    marker.addListener('click', () => {{
                        selectStore(store);
                    }});
                    
                    storeMarkers.push(marker);
                    
                }} catch (error) {{
                    console.error('Error creating store marker:', error);
                }}
            }});
        }}
        
        function showStoresList() {{
            const filteredStores = filterStores(nearbyStores);
            const storesContainer = document.getElementById('nearbyStores');
            
            if (filteredStores.length === 0) {{
                storesContainer.innerHTML = '<p>No stores found matching current filter.</p>';
                storesContainer.style.display = 'block';
                return;
            }}
            
            const storesHTML = filteredStores.slice(0, 15).map(store => {{
                const distance = store.distance;
                const rating = store.rating ? `⭐ ${{store.rating}}` : '';
                const ratingCount = store.rating_count ? `(${{store.rating_count.toLocaleString()}})` : '';
                
                // Store status
                let statusIcon = '';
                let statusText = '';
                if (store.is_open === true) {{
                    statusIcon = '🟢';
                    statusText = 'OPEN';
                }} else if (store.is_open === false) {{
                    statusIcon = '🔴';
                    statusText = 'CLOSED';
                }} else {{
                    statusIcon = '🟡';
                    statusText = 'HOURS UNKNOWN';
                }}
                
                // Hours today
                const hoursToday = store.hours_today || '';
                
                // Phone number
                const phone = store.phone || '';
                
                return `
                    <div class="store-item google-verified" 
                         onclick="selectStore(${{JSON.stringify(store).replace(/"/g, '&quot;')}})">
                        <div style="display: flex; justify-content: space-between; align-items: start;">
                            <div style="flex: 1;">
                                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                                    <strong>${{getStoreEmoji(store.chain)}} ${{store.name}}</strong>
                                    <span class="realtime-badge-small">🔍 Live</span>
                                    <span style="margin-left: 8px; font-size: 12px;">${{statusIcon}} ${{statusText}}</span>
                                </div>
                                
                                <div style="color: #666; font-size: 14px; line-height: 1.4;">
                                    📍 ${{store.address}}<br>
                                    ${{rating ? `${{rating}} ${{ratingCount}}<br>` : ''}}
                                    ${{hoursToday ? `🕐 ${{hoursToday}}<br>` : ''}}
                                    ${{phone ? `📞 ${{phone}}` : ''}}
                                </div>
                            </div>
                            <div style="text-align: right; margin-left: 16px;">
                                <div style="font-size: 18px; font-weight: bold; color: #1a73e8;">
                                    ${{distance.toFixed(1)}} mi
                                </div>
                                <div style="font-size: 12px; margin-top: 4px;">
                                    ${{getDistanceStatus(distance)}}
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }}).join('');
            
            storesContainer.innerHTML = storesHTML;
            storesContainer.style.display = 'block';
        }}
        
        function filterStores(stores) {{
            if (currentFilter === 'all') return stores;
            return stores.filter(store => 
                store.chain.toLowerCase().includes(currentFilter.toLowerCase())
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
                const response = await fetch('/webhook/location', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        latitude: userLocation.lat,
                        longitude: userLocation.lng,
                        accuracy: 10,
                        isManualCheckIn: true,
                        selectedStore: store,
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
                    
                    setTimeout(() => {{
                        button.disabled = false;
                        button.innerHTML = '📍 Search Nearby Stores';
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
                    button.innerHTML = '📍 Search Nearby Stores';
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
                if (nearbyStores.length > 0) {{
                    showStoresOnMap();
                    showStoresList();
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

@app.route('/api/search-stores', methods=['POST'])
def api_search_stores():
    """API endpoint for real-time store search"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        user_id = data.get('user_id')
        
        # Perform real-time search
        stores = search_nearby_stores(lat, lng)
        
        safe_print(f"🔍 Real-time search found {len(stores)} stores for user {user_id}")
        
        return jsonify({
            "status": "success",
            "stores": stores,
            "search_location": {"lat": lat, "lng": lng},
            "total_found": len(stores)
        }), 200
        
    except Exception as e:
        safe_print(f"❌ Store search API error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Enhanced location webhook with real-time store data"""
    try:
        data = request.get_json()
        if not data or not bot_connected or not bot_ready:
            return jsonify({"error": "Bot not ready"}), 503
        
        # Handle real-time selected store
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        user_id = data.get('user_id')
        selected_store_data = data.get('selectedStore')
        
        if user_id and selected_store_data:
            # Save the real-time store data
            save_location_to_db(
                user_id=user_id,
                channel_id=LOCATION_CHANNEL_ID,
                lat=lat,
                lng=lng,
                accuracy=data.get('accuracy'),
                store_name=selected_store_data['name'],
                store_address=selected_store_data['address'],
                store_place_id=selected_store_data.get('place_id'),
                distance=selected_store_data['distance'],
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
    """Enhanced Discord posting with premium-style embed"""
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
        selected_store_data = location_data.get('selectedStore', None)
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
        
        # Use real-time store data
        if selected_store_data:
            store_name = selected_store_data['name']
            store_address = selected_store_data['address']
            distance = selected_store_data['distance']
            chain = selected_store_data['chain']
            rating = selected_store_data.get('rating')
            rating_count = selected_store_data.get('rating_count')
            place_id = selected_store_data.get('place_id')
            store_lat = selected_store_data['lat']
            store_lng = selected_store_data['lng']
            phone = selected_store_data.get('phone')
            website = selected_store_data.get('website')
            is_open = selected_store_data.get('is_open')
            hours_today = selected_store_data.get('hours_today')
            business_status = selected_store_data.get('business_status')
        else:
            return False
        
        # Get store branding
        branding = get_store_branding(chain)
        
        # Distance status and color
        if distance <= 0.2:
            distance_status = "🟢 AT STORE"
            distance_color = "🟢"
        elif distance <= 1.0:
            distance_status = "🟡 NEARBY"
            distance_color = "🟡"
        else:
            distance_status = "🔴 FAR"
            distance_color = "🔴"
        
        # Time-based greeting
        current_hour = datetime.utcnow().hour - 5  # EST
        if 5 <= current_hour < 12:
            time_greeting = "Good morning"
        elif 12 <= current_hour < 17:
            time_greeting = "Good afternoon"
        elif 17 <= current_hour < 21:
            time_greeting = "Good evening"
        else:
            time_greeting = "Hello"
        
        # Create premium embed
        embed = discord.Embed(
            title=f"{branding['emoji']} {store_name}",
            description=f"**{time_greeting} {username}!** You're **{distance:.1f} miles** from this {branding['description'].lower()}",
            color=branding['color']
        )
        
        # Set store logo as thumbnail if available
        store_logos = {
            "Target": "https://logos-world.net/wp-content/uploads/2020/04/Target-Logo.png",
            "Walmart": "https://logos-world.net/wp-content/uploads/2020/05/Walmart-Logo.png", 
            "Best Buy": "https://logos-world.net/wp-content/uploads/2020/04/Best-Buy-Logo.png",
            "BJs": "https://logos-world.net/wp-content/uploads/2022/02/BJs-Wholesale-Club-Logo.png"
        }
        
        if chain in store_logos:
            embed.set_thumbnail(url=store_logos[chain])
        
        if avatar_url:
            embed.set_author(
                name=f"{username}'s Location Check-in", 
                icon_url=avatar_url
            )
        
        # LOCATION STATUS (prominent first field)
        embed.add_field(
            name=f"{distance_color} **LOCATION STATUS**",
            value=f"**{distance_status}**\n📏 {distance:.1f} miles away\n🎯 GPS accuracy: ±{accuracy}m",
            inline=False
        )
        
        # STORE INFORMATION (two columns)
        store_info = f"**{branding['emoji']} {store_name}**\n"
        
        # Rating and reviews
        if rating and rating_count:
            stars = "⭐" * int(rating)
            store_info += f"{stars} **{rating}/5** ({rating_count:,} reviews)\n"
        
        # Open/closed status
        if is_open is not None:
            if is_open:
                store_info += f"🟢 **OPEN NOW**\n"
            else:
                store_info += f"🔴 **CLOSED**\n"
        elif business_status == "OPERATIONAL":
            store_info += f"🟡 **STATUS UNKNOWN**\n"
        
        # Hours today
        if hours_today:
            store_info += f"🕐 {hours_today}\n"
        
        # Phone number
        if phone:
            store_info += f"📞 {phone}\n"
        
        store_info += f"🏢 {branding['description']}"
        
        embed.add_field(
            name="🏪 **STORE DETAILS**",
            value=store_info,
            inline=True
        )
        
        # LOCATION DETAILS
        location_info = f"📍 **Address:**\n{store_address}\n\n"
        location_info += f"🧭 **Coordinates:**\n{store_lat:.5f}, {store_lng:.5f}"
        
        embed.add_field(
            name="📍 **LOCATION INFO**",
            value=location_info,
            inline=True
        )
        
        # ACTIONS & LINKS (prominent section)
        google_maps_url = f"https://maps.google.com/maps/place/?q=place_id:{place_id}" if place_id else f"https://maps.google.com/maps?q={store_lat},{store_lng}"
        apple_maps_url = f"https://maps.apple.com/?q={store_lat},{store_lng}"
        directions_url = f"https://maps.google.com/maps/dir/{lat},{lng}/{store_lat},{store_lng}"
        
        actions_text = f"🗺️ [**Open in Google Maps**]({google_maps_url})\n"
        actions_text += f"🧭 [**Get Directions**]({directions_url})\n"
        
        if phone:
            # Format phone for tel: link
            phone_clean = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            actions_text += f"📞 [**Call Store**](tel:{phone_clean})\n"
        
        if website:
            actions_text += f"🌐 [**Visit Website**]({website})\n"
        
        actions_text += f"🍎 [**Apple Maps**]({apple_maps_url})"
        
        embed.add_field(
            name="🚗 **QUICK ACTIONS**",
            value=actions_text,
            inline=False
        )
        
        # TECHNICAL INFO (smaller, less prominent)
        tech_info = f"🔍 **Data Source:** Live Google Places API\n"
        tech_info += f"✅ **Verification:** Real-time search results\n"
        tech_info += f"📊 **Accuracy:** Professional-grade GPS\n"
        tech_info += f"🕐 **Search Time:** {datetime.utcnow().strftime('%I:%M %p UTC')}"
        
        embed.add_field(
            name="⚙️ **TECHNICAL DETAILS**",
            value=tech_info,
            inline=True
        )
        
        # USER LOCATION (matching column)
        user_info = f"👤 **Your Location:**\n{lat:.5f}, {lng:.5f}\n\n"
        user_info += f"📱 **Check-in Method:**\n{'🎯 Manual Selection' if is_manual else '📍 Auto-detected'}"
        
        embed.add_field(
            name="📱 **YOUR POSITION**",
            value=user_info,
            inline=True
        )
        
        # FOOTER with enhanced branding
        embed.set_footer(
            text=f"🔍 Real-Time Location System • Powered by Google Places API • Always Current & Accurate",
            icon_url="https://cdn-icons-png.flaticon.com/512/2875/2875404.png"
        )
        embed.timestamp = discord.utils.utcnow()
        
        # Send the enhanced embed
        await channel.send(embed=embed)
        
        # Optional: Send additional interactive buttons (if you want even more enhancement)
        try:
            # Create view with buttons for additional actions
            from discord import ui
            
            class LocationView(ui.View):
                def __init__(self):
                    super().__init__(timeout=300)  # 5 minutes timeout
                
                @ui.button(label="📍 Share with Others", style=discord.ButtonStyle.primary, emoji="📍")
                async def share_location(self, interaction: discord.Interaction, button: ui.Button):
                    share_url = f"https://maps.google.com/maps?q={store_lat},{store_lng}"
                    await interaction.response.send_message(
                        f"📍 **{store_name}** location link:\n{share_url}", 
                        ephemeral=True
                    )
                
                @ui.button(label="📊 Store Info", style=discord.ButtonStyle.secondary, emoji="📊")
                async def store_info(self, interaction: discord.Interaction, button: ui.Button):
                    info_text = f"**{store_name}**\n"
                    info_text += f"📍 {store_address}\n"
                    if rating:
                        info_text += f"⭐ {rating}/5 ({rating_count:,} reviews)\n"
                    info_text += f"🏢 {branding['description']}\n"
                    info_text += f"🔍 Data from Google Places API"
                    
                    await interaction.response.send_message(info_text, ephemeral=True)
                
                @ui.button(label="🧭 Get Directions", style=discord.ButtonStyle.success, emoji="🧭")
                async def get_directions(self, interaction: discord.Interaction, button: ui.Button):
                    directions_url = f"https://maps.google.com/maps/dir/{lat},{lng}/{store_lat},{store_lng}"
                    await interaction.response.send_message(
                        f"🧭 **Directions to {store_name}:**\n{directions_url}", 
                        ephemeral=True
                    )
            
            # Send view with buttons (comment out if you don't want buttons)
            # await channel.send(view=LocationView())
            
        except Exception as button_error:
            safe_print(f"⚠️ Button creation error: {button_error}")
        
        safe_print(f"✅ Posted enhanced location embed for {username}")
        return True
        
    except Exception as e:
        safe_print(f"❌ Error posting enhanced embed: {e}")
        return False

@app.route('/health', methods=['GET'])
def health():
    """Enhanced health check with real-time search status"""
    try:
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
            "google_places_api": gmaps is not None,
            "real_time_search": True,
            "database": "connected",
            "search_method": "live_google_places" if gmaps else "disabled",
            "active_tracking_sessions": active_sessions,
            "total_location_records": total_locations,
            "features": [
                "real_time_store_search",
                "google_places_integration", 
                "no_static_database",
                "always_accurate_data"
            ]
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

def run_flask():
    """Run Flask server"""
    try:
        port = int(os.getenv('PORT', 5000))
        safe_print(f"🌐 Starting real-time Flask server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        safe_print(f"❌ Flask startup error: {e}")

def main():
    """Enhanced main function with real-time search"""
    safe_print("=== Starting Real-Time Location Bot with Google Places ===")
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        safe_print("❌ DISCORD_TOKEN environment variable not found!")
        return
    
    GOOGLE_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')
    if not GOOGLE_API_KEY:
        safe_print("⚠️ GOOGLE_MAPS_API_KEY not found - real-time search will be disabled")
    else:
        safe_print("✅ Google Maps API key found - real-time search enabled")
    
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
        safe_print("✅ Discord bot connected with real-time search capabilities!")
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
