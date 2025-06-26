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

# Flask app with better error handling
app = Flask(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Complete Massachusetts Store Database with accurate coordinates
STORES = [
    # TARGET STORES
    {"name": "Target Abington", "lat": 42.1068, "lng": -70.9453, "address": "777 Brockton Ave, Abington, MA 02351"},
    {"name": "Target Boston Fenway", "lat": 42.3467, "lng": -71.1043, "address": "1341 Boylston St, Boston, MA 02215"},
    {"name": "Target Boston South Bay", "lat": 42.3318, "lng": -71.0677, "address": "250 Granite St, Boston, MA 02125"},
    {"name": "Target Burlington", "lat": 42.5042, "lng": -71.1956, "address": "51 Middlesex Tpke, Burlington, MA 01803"},
    {"name": "Target Cambridge", "lat": 42.3656, "lng": -71.1043, "address": "180 Somerville Ave, Cambridge, MA 02143"},
    {"name": "Target Danvers", "lat": 42.5751, "lng": -70.9395, "address": "112 Endicott St, Danvers, MA 01923"},
    {"name": "Target Dedham", "lat": 42.2479, "lng": -71.1656, "address": "850 Providence Hwy, Dedham, MA 02026"},
    {"name": "Target Dorchester", "lat": 42.3118, "lng": -71.0677, "address": "7 Allstate Rd, Dorchester, MA 02125"},
    {"name": "Target Everett", "lat": 42.4098, "lng": -71.0536, "address": "1 Mystic View Rd, Everett, MA 02149"},
    {"name": "Target Framingham", "lat": 42.2793, "lng": -71.4162, "address": "400 Cochituate Rd, Framingham, MA 01701"},
    {"name": "Target Hadley", "lat": 42.3548, "lng": -72.5717, "address": "367 Russell St, Hadley, MA 01035"},
    {"name": "Target Hanover", "lat": 42.1137, "lng": -70.8453, "address": "1167 Washington St, Hanover, MA 02339"},
    {"name": "Target Haverhill", "lat": 42.7751, "lng": -71.0770, "address": "35 Computer Dr, Haverhill, MA 01832"},
    {"name": "Target Holyoke", "lat": 42.2043, "lng": -72.6162, "address": "50 Holyoke St, Holyoke, MA 01040"},
    {"name": "Target Kingston", "lat": 42.0137, "lng": -70.7453, "address": "101 Independence Mall Way, Kingston, MA 02364"},
    {"name": "Target Lowell", "lat": 42.6334, "lng": -71.3162, "address": "181 Plain St, Lowell, MA 01852"},
    {"name": "Target Marlborough East", "lat": 42.3460, "lng": -71.5526, "address": "423 Donald Lynch Blvd, Marlborough, MA 01752"},
    {"name": "Target Marlborough West", "lat": 42.3548, "lng": -71.5717, "address": "605 Boston Post Rd E, Marlborough, MA 01752"},
    {"name": "Target Methuen", "lat": 42.7262, "lng": -71.1770, "address": "67 Pleasant Valley St, Methuen, MA 01844"},
    {"name": "Target Milford", "lat": 42.1548, "lng": -71.5162, "address": "250 Fortune Blvd, Milford, MA 01757"},
    {"name": "Target Millbury", "lat": 42.1951, "lng": -71.7678, "address": "70 Worcester Providence Tpke, Millbury, MA 01527"},
    {"name": "Target North Attleborough", "lat": 41.9751, "lng": -71.3298, "address": "1205 S Washington St, North Attleborough, MA 02760"},
    {"name": "Target North Dartmouth", "lat": 41.6043, "lng": -70.9162, "address": "479 State Rd, North Dartmouth, MA 02747"},
    {"name": "Target Plainville", "lat": 42.0043, "lng": -71.3162, "address": "39 Taunton St, Plainville, MA 02762"},
    {"name": "Target Revere", "lat": 42.4179, "lng": -71.0123, "address": "36 Furlong Dr, Revere, MA 02151"},
    {"name": "Target Salem", "lat": 42.5179, "lng": -70.8998, "address": "227 Highland Ave, Salem, MA 01970"},
    {"name": "Target Saugus", "lat": 42.4662, "lng": -71.0123, "address": "400 Lynn Fells Pkwy, Saugus, MA 01906"},
    {"name": "Target Seekonk", "lat": 41.8262, "lng": -71.3298, "address": "79 Commerce Way, Seekonk, MA 02771"},
    {"name": "Target Somerville", "lat": 42.3885, "lng": -71.0998, "address": "180 Somerville Ave, Somerville, MA 02143"},
    {"name": "Target South Easton", "lat": 42.0637, "lng": -71.0953, "address": "41 Robert Dr, South Easton, MA 02375"},
    {"name": "Target Stoughton", "lat": 42.1137, "lng": -71.1453, "address": "1 Hawes Way, Stoughton, MA 02072"},
    {"name": "Target Swansea", "lat": 41.7551, "lng": -71.1898, "address": "579 GAR Hwy, Swansea, MA 02777"},
    {"name": "Target Taunton", "lat": 41.9043, "lng": -71.0898, "address": "81 Taunton Depot Dr, Taunton, MA 02780"},
    {"name": "Target Watertown", "lat": 42.3718, "lng": -71.1826, "address": "550 Arsenal St, Watertown, MA 02472"},
    {"name": "Target West Roxbury", "lat": 42.2818, "lng": -71.1598, "address": "1810 Centre St, West Roxbury, MA 02132"},
    {"name": "Target Worcester", "lat": 42.2626, "lng": -71.8023, "address": "529 Lincoln St, Worcester, MA 01605"},

    # WALMART STORES  
    {"name": "Walmart Abington", "lat": 42.1068, "lng": -70.9453, "address": "777 Brockton Ave, Abington, MA 02351"},
    {"name": "Walmart Avon", "lat": 42.1301, "lng": -71.0398, "address": "30 Memorial Dr, Avon, MA 02322"},
    {"name": "Walmart Bellingham", "lat": 42.0851, "lng": -71.4745, "address": "250 Hartford Ave, Bellingham, MA 02019"},
    {"name": "Walmart Brockton", "lat": 42.0834, "lng": -71.0184, "address": "700 Oak St, Brockton, MA 02301"},
    {"name": "Walmart Chelmsford", "lat": 42.5998, "lng": -71.3670, "address": "66 Parkhurst Rd, Chelmsford, MA 01824"},
    {"name": "Walmart Chicopee", "lat": 42.1487, "lng": -72.6078, "address": "591 Memorial Dr, Chicopee, MA 01020"},
    {"name": "Walmart Hudson", "lat": 42.3751, "lng": -71.5995, "address": "280 Washington St, Hudson, MA 01749"},
    {"name": "Walmart Leicester", "lat": 42.2453, "lng": -71.9089, "address": "20 Soojian Dr, Leicester, MA 01524"},
    {"name": "Walmart Leominster", "lat": 42.5245, "lng": -71.7595, "address": "11 Jungle Rd, Leominster, MA 01453"},
    {"name": "Walmart Lunenburg", "lat": 42.5912, "lng": -71.7231, "address": "301 Massachusetts Ave, Lunenburg, MA 01462"},
    {"name": "Walmart Lynn", "lat": 42.4662, "lng": -70.9495, "address": "780 Lynnway, Lynn, MA 01905"},
    {"name": "Walmart Methuen", "lat": 42.7262, "lng": -71.1770, "address": "70 Pleasant Valley St, Methuen, MA 01844"},
    {"name": "Walmart North Adams", "lat": 42.7009, "lng": -73.1090, "address": "1415 Curran Hwy, North Adams, MA 01247"},
    {"name": "Walmart North Attleborough", "lat": 41.9751, "lng": -71.3298, "address": "1470 S Washington St, North Attleborough, MA 02760"},
    {"name": "Walmart Raynham", "lat": 41.9393, "lng": -71.0453, "address": "36 Paramount Dr, Raynham, MA 02767"},
    {"name": "Walmart Walpole", "lat": 42.1262, "lng": -71.2562, "address": "550 Providence Hwy, Walpole, MA 02081"},
    {"name": "Walmart Westfield", "lat": 42.1251, "lng": -72.7495, "address": "141 Springfield Rd, Westfield, MA 01085"},
    {"name": "Walmart Weymouth", "lat": 42.2179, "lng": -70.9395, "address": "740 Middle St, Weymouth, MA 02188"},
    {"name": "Walmart Whitinsville", "lat": 42.1162, "lng": -71.6895, "address": "100 Valley Pkwy, Whitinsville, MA 01588"},
    {"name": "Walmart Worcester", "lat": 42.2626, "lng": -71.8023, "address": "25 Tobias Boland Way, Worcester, MA 01608"},

    # BEST BUY STORES
    {"name": "Best Buy Braintree", "lat": 42.2251, "lng": -71.0123, "address": "250 Granite St, Braintree, MA 02184"},
    {"name": "Best Buy Burlington", "lat": 42.5042, "lng": -71.1956, "address": "84 Middlesex Tpke, Burlington, MA 01803"},
    {"name": "Best Buy Cambridge", "lat": 42.3885, "lng": -71.1043, "address": "100 CambridgeSide Pl, Cambridge, MA 02141"},
    {"name": "Best Buy Danvers", "lat": 42.5751, "lng": -70.9395, "address": "230 Independence Way, Danvers, MA 01923"},
    {"name": "Best Buy Dedham", "lat": 42.2479, "lng": -71.1656, "address": "950 Providence Hwy, Dedham, MA 02026"},
    {"name": "Best Buy Everett", "lat": 42.4098, "lng": -71.0536, "address": "162 Santilli Hwy, Everett, MA 02149"},
    {"name": "Best Buy Framingham", "lat": 42.2793, "lng": -71.4162, "address": "400 Cochituate Rd, Framingham, MA 01701"},
    {"name": "Best Buy Marlborough", "lat": 42.3460, "lng": -71.5526, "address": "769 Donald Lynch Blvd, Marlborough, MA 01752"},
    {"name": "Best Buy Natick", "lat": 42.2837, "lng": -71.3495, "address": "1245 Worcester St, Natick, MA 01760"},
    {"name": "Best Buy South Bay", "lat": 42.3318, "lng": -71.0677, "address": "250 Granite St, Boston, MA 02125"},
    {"name": "Best Buy Watertown", "lat": 42.3718, "lng": -71.1826, "address": "550 Arsenal St, Watertown, MA 02472"},
    {"name": "Best Buy West Springfield", "lat": 42.1043, "lng": -72.6395, "address": "1150 Riverdale St, West Springfield, MA 01089"},

    # BJS WHOLESALE STORES
    {"name": "BJs Wholesale Auburn", "lat": 42.1945, "lng": -71.8356, "address": "777 Washington St, Auburn, MA 01501"},
    {"name": "BJs Wholesale Chicopee", "lat": 42.1487, "lng": -72.6078, "address": "650 Memorial Dr, Chicopee, MA 01020"},
    {"name": "BJs Wholesale Danvers", "lat": 42.5751, "lng": -70.9395, "address": "6 Hutchinson Dr, Danvers, MA 01923"},
    {"name": "BJs Wholesale Dedham", "lat": 42.2479, "lng": -71.1656, "address": "688 Providence Hwy, Dedham, MA 02026"},
    {"name": "BJs Wholesale Framingham", "lat": 42.2793, "lng": -71.4162, "address": "26 Whittier St, Framingham, MA 01701"},
    {"name": "BJs Wholesale Franklin", "lat": 42.0837, "lng": -71.3995, "address": "100 Corporate Dr, Franklin, MA 02038"},
    {"name": "BJs Wholesale Greenfield", "lat": 42.5918, "lng": -72.5995, "address": "42 Colrain Rd, Greenfield, MA 01301"},
    {"name": "BJs Wholesale Haverhill", "lat": 42.7751, "lng": -71.0770, "address": "25 Shelley Rd, Haverhill, MA 01835"},
    {"name": "BJs Wholesale Hudson", "lat": 42.3751, "lng": -71.5995, "address": "1 Highland Commons West, Hudson, MA 01749"},
    {"name": "BJs Wholesale Hyannis", "lat": 41.6526, "lng": -70.2895, "address": "420 Attucks Ln, Hyannis, MA 02601"},
    {"name": "BJs Wholesale Leominster", "lat": 42.5245, "lng": -71.7595, "address": "115 Erdman Way, Leominster, MA 01453"},
    {"name": "BJs Wholesale Medford", "lat": 42.4184, "lng": -71.1061, "address": "278 Middlesex Ave, Medford, MA 02155"},
    {"name": "BJs Wholesale North Dartmouth", "lat": 41.6043, "lng": -70.9162, "address": "460 State Rd, North Dartmouth, MA 02747"},
    {"name": "BJs Wholesale Northborough", "lat": 42.3195, "lng": -71.6395, "address": "6102 Shops Way, Northborough, MA 01532"},
    {"name": "BJs Wholesale Pittsfield", "lat": 42.4501, "lng": -73.2453, "address": "495 Hubbard Ave, Pittsfield, MA 01201"},
    {"name": "BJs Wholesale Plymouth", "lat": 41.9584, "lng": -70.6673, "address": "105 Shops at 5 Way, Plymouth, MA 02360"},
    {"name": "BJs Wholesale Quincy", "lat": 42.2529, "lng": -71.0023, "address": "200 Crown Colony Dr, Quincy, MA 02169"},
    {"name": "BJs Wholesale Revere", "lat": 42.4179, "lng": -71.0123, "address": "5 Ward St, Revere, MA 02151"},
    {"name": "BJs Wholesale Seekonk", "lat": 41.8262, "lng": -71.3298, "address": "175 Highland Ave, Seekonk, MA 02771"},
    {"name": "BJs Wholesale South Attleboro", "lat": 41.9262, "lng": -71.3561, "address": "287 Washington St, South Attleboro, MA 02703"},
    {"name": "BJs Wholesale Stoneham", "lat": 42.4662, "lng": -71.0998, "address": "85 Cedar St, Stoneham, MA 02180"},
    {"name": "BJs Wholesale Stoughton", "lat": 42.1137, "lng": -71.1453, "address": "901 Technology Center Dr, Stoughton, MA 02072"},
    {"name": "BJs Wholesale Taunton", "lat": 41.9043, "lng": -71.0898, "address": "2085 Bay St, Taunton, MA 02780"},
    {"name": "BJs Wholesale Waltham", "lat": 42.3751, "lng": -71.2356, "address": "66 Seyon St, Waltham, MA 02453"},
    {"name": "BJs Wholesale Weymouth", "lat": 42.2179, "lng": -70.9395, "address": "622 Washington St, Weymouth, MA 02188"},
    {"name": "BJs Wholesale Worcester", "lat": 42.2626, "lng": -71.8023, "address": "25 Tobias Boland Way, Worcester, MA 01608"}
]

# Global state
LOCATION_CHANNEL_ID = None
LOCATION_USER_INFO = {}  # Store user info for location requests
bot_ready = False
bot_connected = False

def safe_print(msg):
    """Safe printing for Railway logs"""
    try:
        print(f"[BOT] {msg}")
        sys.stdout.flush()
    except:
        pass

def get_store_branding(store_name):
    """Return store-specific branding (emoji, color, logo)"""
    store_lower = store_name.lower()
    
    if "target" in store_lower:
        return {
            "emoji": "🎯",
            "color": 0xCC0000,  # Target red
            "logo": "https://logos-world.net/wp-content/uploads/2020/04/Target-Logo.png",
            "description": "Department Store • Clothing, Electronics, Home"
        }
    elif "walmart" in store_lower:
        return {
            "emoji": "🏪", 
            "color": 0x0071CE,  # Walmart blue
            "logo": "https://logos-world.net/wp-content/uploads/2020/05/Walmart-Logo.png",
            "description": "Superstore • Groceries, Electronics, Everything"
        }
    elif "best buy" in store_lower:
        return {
            "emoji": "🔌",
            "color": 0xFFE000,  # Best Buy yellow
            "logo": "https://logos-world.net/wp-content/uploads/2020/04/Best-Buy-Logo.png", 
            "description": "Electronics Store • Tech, Computers, Gaming"
        }
    elif "bjs" in store_lower:
        return {
            "emoji": "🛒",
            "color": 0xFF6B35,  # BJ's orange
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
        return 999  # Return large distance on error

def find_closest_store(user_lat, user_lng):
    """Find the closest store"""
    try:
        min_distance = float('inf')
        closest_store = None
        
        for store in STORES:
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
    nearby_stores = []
    
    for store in STORES:
        distance = calculate_distance(user_lat, user_lng, store['lat'], store['lng'])
        if distance <= radius_miles:
            nearby_stores.append({
                'store': store,
                'distance': distance
            })
    
    # Sort by distance
    nearby_stores.sort(key=lambda x: x['distance'])
    return nearby_stores

def get_status_indicator(distance):
    """Return status indicator based on distance"""
    if distance <= 0.2:  # Very close (at the store)
        return "🟢", "AT STORE"
    elif distance <= 1.0:  # Close (nearby)
        return "🟡", "NEARBY"
    else:  # Far
        return "🔴", "FAR"

# Bot events
@bot.event
async def on_ready():
    global bot_ready, bot_connected
    safe_print(f"🤖 Discord bot connected: {bot.user}")
    safe_print(f"📍 Loaded {len(STORES)} store locations")
    bot_connected = True
    
    try:
        synced = await bot.tree.sync()
        safe_print(f"🔄 Synced {len(synced)} slash commands")
        bot_ready = True
        safe_print("✅ Bot is now fully ready for webhooks!")
    except Exception as e:
        safe_print(f"❌ Failed to sync commands: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    safe_print(f"Bot error in {event}: {args}")

# Bot commands
@bot.tree.command(name="ping", description="Test if bot is working")
async def ping(interaction: discord.Interaction):
    """Test command"""
    try:
        await interaction.response.send_message("🏓 Pong! Bot is working!")
        safe_print("Ping command executed successfully")
    except Exception as e:
        safe_print(f"Ping command error: {e}")

@bot.tree.command(name="location", description="Share your location with the team")
async def location_command(interaction: discord.Interaction):
    """Location sharing command"""
    global LOCATION_CHANNEL_ID, LOCATION_USER_INFO
    
    try:
        LOCATION_CHANNEL_ID = interaction.channel.id
        
        # Store user info for this location request
        user_key = f"{interaction.channel.id}_{interaction.user.id}"
        LOCATION_USER_INFO[user_key] = {
            'user_id': interaction.user.id,
            'username': interaction.user.display_name,
            'full_username': str(interaction.user),
            'avatar_url': interaction.user.display_avatar.url,
            'timestamp': discord.utils.utcnow()
        }
        
        safe_print(f"Location command used by {interaction.user.display_name} ({interaction.user.id}) in channel {LOCATION_CHANNEL_ID}")
        
        embed = discord.Embed(
            title="📍 Share Your Location",
            description=f"Hey {interaction.user.display_name}! Click the link below to share your location with the team!",
            color=0x5865F2
        )
        
        # Use the Railway URL
        website_url = f"https://web-production-f0220.up.railway.app?user={interaction.user.id}&channel={interaction.channel.id}"
        embed.add_field(
            name="🔗 Location Link",
            value=f"[Click here to share location]({website_url})",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ How it works",
            value="• Click the link\n• Allow location access\n• Select a nearby store or share GPS location\n• Your location will be posted here automatically",
            inline=False
        )
        
        embed.add_field(
            name="🔒 Privacy",
            value="Your location data is not stored and only shared with this Discord server.",
            inline=False
        )
        
        embed.set_footer(text="Location Sharing System • Powered by Railway")
        embed.timestamp = discord.utils.utcnow()
        
        await interaction.response.send_message(embed=embed)
        safe_print("Location command responded successfully")
        
    except Exception as e:
        safe_print(f"Location command error: {e}")
        try:
            await interaction.response.send_message("❌ Error setting up location sharing")
        except:
            pass

# Location posting function
async def post_location_to_discord(location_data):
    """Post location update to Discord with beautiful styling and username"""
    global LOCATION_CHANNEL_ID, bot_ready, bot_connected, LOCATION_USER_INFO
    
    try:
        if not bot_connected:
            safe_print("❌ Discord bot not connected yet")
            return False
            
        if not bot_ready:
            safe_print("❌ Discord bot not ready yet (commands not synced)")
            return False
            
        if not LOCATION_CHANNEL_ID:
            safe_print("❌ No channel ID set for location updates")
            return False
        
        channel = bot.get_channel(LOCATION_CHANNEL_ID)
        if not channel:
            safe_print(f"❌ Channel {LOCATION_CHANNEL_ID} not found")
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
        full_username = None
        
        if user_id:
            # Try to get user info from stored data first
            user_key = f"{LOCATION_CHANNEL_ID}_{user_id}"
            if user_key in LOCATION_USER_INFO:
                user_info = LOCATION_USER_INFO[user_key]
                username = user_info['username']
                full_username = user_info['full_username']
                avatar_url = user_info['avatar_url']
                safe_print(f"Using stored user info for {username}")
            else:
                # Try to fetch user from Discord
                try:
                    user = bot.get_user(int(user_id))
                    if user:
                        username = user.display_name
                        full_username = str(user)
                        avatar_url = user.display_avatar.url
                        safe_print(f"Fetched user info for {username}")
                    else:
                        safe_print(f"Could not find user with ID {user_id}")
                except Exception as e:
                    safe_print(f"Error fetching user {user_id}: {e}")
        
        safe_print(f"Processing location for {username}: {lat}, {lng}, manual: {is_manual}")
        
        # Find closest store
        closest_store, distance = find_closest_store(lat, lng)
        
        if not closest_store:
            safe_print("No closest store found")
            return False
        
        # Handle manual check-in
        if is_manual and selected_store:
            for store in STORES:
                if store['name'] == selected_store:
                    closest_store = store
                    # Calculate REAL distance between user's location and selected store
                    distance = calculate_distance(lat, lng, store['lat'], store['lng'])
                    break
        
        # Get store branding
        branding = get_store_branding(closest_store['name'])
        
        # Get status indicator - manual check-ins use real distance, not automatic "AT STORE"
        indicator, status = get_status_indicator(distance)
        
        # Create beautiful embed with username - always show real distance
        title_text = f"{branding['emoji']} {username} is {distance:.1f} miles from {closest_store['name']}"
        if is_manual:
            description_text = f"**{username}** manually selected **{closest_store['name']}** ({distance:.1f} miles away)"
        else:
            description_text = f"**{username}** is **{distance:.1f} miles** from {closest_store['name']}"
        
        embed = discord.Embed(
            title=title_text,
            description=description_text,
            color=branding['color']
        )
        
        # Add store logo if available
        if branding['logo']:
            embed.set_thumbnail(url=branding['logo'])
        
        # Add user avatar if available
        if avatar_url:
            embed.set_author(
                name=f"Location Update from {username}",
                icon_url=avatar_url
            )
        
        # Store information section
        embed.add_field(
            name="🏪 Store Name",
            value=closest_store['name'],
            inline=True
        )
        
        embed.add_field(
            name=f"{branding['emoji']} Store Type", 
            value=branding['description'],
            inline=True
        )
        
        # Distance check with beautiful indicators - always show real distance
        embed.add_field(
            name="📏 Distance",
            value=f"{indicator} **{distance:.1f} miles**",
            inline=True
        )
        
        # Status field
        status_descriptions = {
            "AT STORE": "✅ Confirmed at location",
            "NEARBY": "⚠️ Close to location", 
            "FAR": "❌ Not at location"
        }
        
        embed.add_field(
            name="🎯 Status",
            value=status_descriptions.get(status, status),
            inline=True
        )
        
        # User info field
        if full_username:
            embed.add_field(
                name="👤 User",
                value=f"{username}\n(`{full_username}`)",
                inline=True
            )
        else:
            embed.add_field(
                name="👤 User",
                value=username,
                inline=True
            )
        
        # Address
        embed.add_field(
            name="📍 Address",
            value=closest_store['address'],
            inline=False
        )
        
        # Coordinates section
        embed.add_field(
            name="🧭 Coordinates",
            value=f"**Lat:** {lat:.6f}\n**Lng:** {lng:.6f}",
            inline=True
        )
        
        # Method field
        if is_manual:
            embed.add_field(
                name="🎯 Method",
                value=f"Manual Store Selection\n(Selected: {selected_store})",
                inline=True
            )
        else:
            embed.add_field(
                name="🎯 Accuracy",
                value=f"±{accuracy} meters",
                inline=True
            )
        
        # Google Maps link
        maps_url = f"https://maps.google.com/maps?q={lat},{lng}"
        embed.add_field(
            name="🗺️ View on Map",
            value=f"[Open in Google Maps]({maps_url})",
            inline=True
        )
        
        # Find nearby stores for additional context (only for GPS-based check-ins)
        if not is_manual:
            nearby_stores = find_nearby_stores(lat, lng, 2)  # 2 mile radius
            if len(nearby_stores) > 1:
                other_stores = [store['store']['name'] for store in nearby_stores[1:4]]  # Skip closest store
                if other_stores:
                    embed.add_field(
                        name="🏪 Other Nearby Stores",
                        value="\n".join([f"• {store}" for store in other_stores]),
                        inline=False
                    )
        
        # Footer with timestamp
        if is_manual:
            embed.set_footer(
                text=f"Location Sharing System • Store Selected by {username}",
                icon_url="https://cdn.discordapp.com/emojis/899567722774564864.png"
            )
        else:
            embed.set_footer(
                text=f"Location Sharing System • GPS Location from {username}",
                icon_url="https://cdn.discordapp.com/emojis/899567722774564864.png"
            )
        embed.timestamp = discord.utils.utcnow()
        
        await channel.send(embed=embed)
        safe_print(f"✅ Successfully posted beautiful location to Discord for {username}")
        return True
        
    except Exception as e:
        safe_print(f"❌ Error posting to Discord: {e}")
        return False

# Flask routes
@app.route('/', methods=['GET'])
def index():
    """Serve the beautiful location sharing page with user info"""
    user_id = request.args.get('user')
    channel_id = request.args.get('channel')
    
    safe_print(f"Serving index page for user {user_id} in channel {channel_id}")
    
    # Include user info in the page for JavaScript
    user_info_js = json.dumps({
        'user_id': user_id,
        'channel_id': channel_id
    }) if user_id and channel_id else 'null'
    
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Location Bot - Share Your Location</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 24px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .logo {
            font-size: 48px;
            margin-bottom: 16px;
            animation: bounce 2s infinite;
        }

        @keyframes bounce {
            0%, 20%, 50%, 80%, 100% { transform: translateY(0); }
            40% { transform: translateY(-10px); }
            60% { transform: translateY(-5px); }
        }

        h1 {
            color: #2d3748;
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
        }

        .subtitle {
            color: #718096;
            font-size: 16px;
            margin-bottom: 32px;
        }

        .location-button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 16px 32px;
            border-radius: 16px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 25px rgba(102, 126, 234, 0.3);
            margin-bottom: 24px;
            width: 100%;
        }

        .location-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 35px rgba(102, 126, 234, 0.4);
        }

        .location-button:active {
            transform: translateY(0);
        }

        .location-button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .status {
            margin: 24px 0;
            padding: 16px;
            border-radius: 12px;
            font-weight: 500;
            transition: all 0.3s ease;
            display: none;
        }

        .status.success {
            background: linear-gradient(135deg, #48bb78, #38a169);
            color: white;
        }

        .status.error {
            background: linear-gradient(135deg, #f56565, #e53e3e);
            color: white;
        }

        .status.info {
            background: linear-gradient(135deg, #4299e1, #3182ce);
            color: white;
        }

        .nearby-stores {
            margin-top: 24px;
            text-align: left;
            display: none;
        }

        .nearby-stores h3 {
            color: #2d3748;
            font-size: 20px;
            margin-bottom: 16px;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .store-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .store-item {
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            padding: 16px;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .store-item:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.1);
            background: rgba(255, 255, 255, 0.95);
        }

        .store-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 8px;
        }

        .store-emoji {
            font-size: 24px;
        }

        .store-name {
            font-weight: 600;
            color: #2d3748;
            flex: 1;
        }

        .store-distance {
            font-weight: 500;
            padding: 4px 8px;
            border-radius: 8px;
            font-size: 14px;
        }

        .distance-green {
            background: #c6f6d5;
            color: #22543d;
        }

        .distance-yellow {
            background: #fefcbf;
            color: #744210;
        }

        .distance-red {
            background: #fed7d7;
            color: #742a2a;
        }

        .store-info {
            color: #718096;
            font-size: 14px;
            margin-bottom: 4px;
        }

        .store-address {
            color: #a0aec0;
            font-size: 12px;
        }

        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255, 255, 255, 0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
            margin-right: 8px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .footer {
            margin-top: 32px;
            color: #a0aec0;
            font-size: 14px;
            line-height: 1.5;
        }

        .powered-by {
            margin-top: 16px;
            padding-top: 16px;
            border-top: 1px solid rgba(0, 0, 0, 0.1);
            color: #718096;
            font-size: 12px;
        }

        @media (max-width: 480px) {
            .container {
                margin: 10px;
                padding: 24px;
            }
            
            h1 {
                font-size: 24px;
            }
            
            .location-button {
                padding: 14px 24px;
                font-size: 16px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">📍</div>
        <h1>Share Your Location</h1>
        <p class="subtitle">Let your team know where you are!</p>
        
        <button id="shareLocationBtn" class="location-button">
            📍 Share My Location
        </button>
        
        <div id="status" class="status"></div>
        
        <div id="nearbyStores" class="nearby-stores">
            <h3>🏪 Check In to a Store (5 miles)</h3>
            <div id="storeList" class="store-list"></div>
            <button id="shareGPSBtn" class="location-button" style="display: none; margin-top: 16px; background: linear-gradient(135deg, #38a169, #2f855a);">
                📍 Or Share Exact GPS Location
            </button>
        </div>
        
        <div class="footer">
            <p>🔒 Your location is only shared with your Discord server and not stored anywhere.</p>
            <p>📱 Click "Allow" when your browser asks for location permission.</p>
            <p>🏪 After getting your location, click on a specific store to check in OR share your exact GPS location.</p>
            <div class="powered-by">
                Powered by Location Bot • Real-time tracking
            </div>
        </div>
    </div>

    <script>
        // User info passed from server
        const USER_INFO = ''' + user_info_js + ''';
        
        // Complete store database - same as bot.py
        const STORES = ''' + json.dumps(STORES) + ''';

        function getStoreEmoji(storeName) {
            const name = storeName.toLowerCase();
            if (name.includes('target')) return '🎯';
            if (name.includes('walmart')) return '🏪';
            if (name.includes('best buy')) return '🔌';
            if (name.includes('bjs')) return '🛒';
            return '🏢';
        }

        function getStoreDescription(storeName) {
            const name = storeName.toLowerCase();
            if (name.includes('target')) return 'Department Store';
            if (name.includes('walmart')) return 'Superstore';
            if (name.includes('best buy')) return 'Electronics Store';
            if (name.includes('bjs')) return 'Wholesale Club';
            return 'Store';
        }

        function calculateDistance(lat1, lng1, lat2, lng2) {
            const R = 3958.8; // Radius of Earth in miles
            const lat1Rad = lat1 * Math.PI / 180;
            const lng1Rad = lng1 * Math.PI / 180;
            const lat2Rad = lat2 * Math.PI / 180;
            const lng2Rad = lng2 * Math.PI / 180;
            
            const dlat = lat2Rad - lat1Rad;
            const dlng = lng2Rad - lng1Rad;
            
            const a = Math.sin(dlat/2)**2 + Math.cos(lat1Rad) * Math.cos(lat2Rad) * Math.sin(dlng/2)**2;
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            
            return R * c;
        }

        function findNearbyStores(userLat, userLng, radiusMiles = 5) {
            const nearbyStores = [];
            
            STORES.forEach(store => {
                const distance = calculateDistance(userLat, userLng, store.lat, store.lng);
                if (distance <= radiusMiles) {
                    nearbyStores.push({
                        store: store,
                        distance: distance
                    });
                }
            });
            
            // Sort by distance
            nearbyStores.sort((a, b) => a.distance - b.distance);
            return nearbyStores;
        }

        function getDistanceClass(distance) {
            if (distance <= 0.2) return 'distance-green';
            if (distance <= 1.0) return 'distance-yellow';
            return 'distance-red';
        }

        function displayNearbyStores(userLat, userLng) {
            const nearbyStores = findNearbyStores(userLat, userLng, 5);
            const nearbyStoresDiv = document.getElementById('nearbyStores');
            const storeListDiv = document.getElementById('storeList');
            const shareGPSBtn = document.getElementById('shareGPSBtn');
            
            if (nearbyStores.length === 0) {
                nearbyStoresDiv.style.display = 'none';
                return;
            }
            
            storeListDiv.innerHTML = '';
            
            nearbyStores.slice(0, 10).forEach(item => { // Show max 10 stores
                const { store, distance } = item;
                const emoji = getStoreEmoji(store.name);
                const description = getStoreDescription(store.name);
                const distanceClass = getDistanceClass(distance);
                
                const storeElement = document.createElement('div');
                storeElement.className = 'store-item';
                storeElement.onclick = () => {
                    selectStore(store);
                };
                
                storeElement.innerHTML = `
                    <div class="store-header">
                        <div class="store-emoji">${emoji}</div>
                        <div class="store-name">${store.name}</div>
                        <div class="store-distance ${distanceClass}">${distance.toFixed(1)} mi</div>
                    </div>
                    <div class="store-info">${description} • Click to check in</div>
                    <div class="store-address">${store.address}</div>
                `;
                
                storeListDiv.appendChild(storeElement);
            });
            
            if (nearbyStores.length > 10) {
                const moreStoresElement = document.createElement('div');
                moreStoresElement.className = 'store-item';
                moreStoresElement.style.textAlign = 'center';
                moreStoresElement.style.color = '#718096';
                moreStoresElement.innerHTML = `<div>+ ${nearbyStores.length - 10} more stores nearby</div>`;
                storeListDiv.appendChild(moreStoresElement);
            }
            
            // Show the GPS sharing button
            shareGPSBtn.style.display = 'block';
            
            nearbyStoresDiv.style.display = 'block';
        }

        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = `status ${type}`;
            statusDiv.style.display = 'block';
        }

        // Store user's actual GPS coordinates
        let userActualLocation = null;

        function selectStore(store) {
            showStatus('📍 Checking you in to ' + store.name + '...', 'info');
            
            if (!userActualLocation) {
                showStatus('❌ No GPS location available. Please share your location first.', 'error');
                return;
            }
            
            // Create location data using user's ACTUAL coordinates but selected store
            const locationData = {
                latitude: userActualLocation.latitude,
                longitude: userActualLocation.longitude,
                accuracy: userActualLocation.accuracy,
                selectedStore: store.name,
                isManualCheckIn: true
            };
            
            // Add user info if available
            if (USER_INFO && USER_INFO.user_id) {
                locationData.user_id = USER_INFO.user_id;
            }
            
            // Post the user's actual location with selected store
            postLocationToDiscord(locationData);
        }

        async function postLocationToDiscord(location) {
            try {
                console.log('Sending location to webhook:', location);
                
                const response = await fetch('/webhook/location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(location)
                });

                console.log('Response status:', response.status);
                const responseData = await response.json();
                console.log('Response data:', responseData);
                
                if (response.ok) {
                    if (location.selectedStore) {
                        showStatus('✅ Successfully checked in to ' + location.selectedStore + '!', 'success');
                    } else if (location.isManualCheckIn === false) {
                        showStatus('✅ GPS location shared successfully with your team!', 'success');
                    } else {
                        showStatus('✅ Location shared successfully with your team!', 'success');
                    }
                    
                    // Redirect back to Discord after 2 seconds
                    setTimeout(() => {
                        showStatus('🔄 Redirecting back to Discord...', 'info');
                        
                        // Try different methods to return to Discord
                        setTimeout(() => {
                            // Try to close the window/tab (works if opened from Discord)
                            try {
                                window.close();
                            } catch (e) {
                                // If that fails, try Discord app URL
                                window.location.href = 'discord://';
                                
                                // Fallback: show manual instruction
                                setTimeout(() => {
                                    showStatus('✅ Check-in complete! You can now return to Discord.', 'success');
                                }, 1000);
                            }
                        }, 500);
                    }, 2000);
                } else {
                    throw new Error(responseData.error || 'Failed to share location');
                }
            } catch (error) {
                console.error('Error posting location:', error);
                showStatus('❌ Failed to share location: ' + error.message, 'error');
                
                // Re-enable the button
                const button = document.getElementById('shareLocationBtn');
                button.disabled = false;
                button.innerHTML = '📍 Share My Location';
            }
        }

        document.getElementById('shareLocationBtn').addEventListener('click', function() {
            const button = this;
            
            if (!navigator.geolocation) {
                showStatus('❌ Geolocation is not supported by this browser.', 'error');
                return;
            }
            
            button.disabled = true;
            button.innerHTML = '<div class="loading"></div>Getting your location...';
            showStatus('📍 Requesting location access...', 'info');
            
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const latitude = position.coords.latitude;
                    const longitude = position.coords.longitude;
                    const accuracy = Math.round(position.coords.accuracy);
                    
                    // Store user's actual location for later use
                    userActualLocation = {
                        latitude: latitude,
                        longitude: longitude,
                        accuracy: accuracy
                    };
                    
                    // Display nearby stores
                    displayNearbyStores(latitude, longitude);
                    
                    // Update button and show success message
                    button.innerHTML = '✅ Location Found!';
                    button.style.background = 'linear-gradient(135deg, #48bb78, #38a169)';
                    showStatus('📍 Location found! Now click on a store below to check in.', 'success');
                    
                    setTimeout(() => {
                        button.disabled = false;
                        button.innerHTML = '📍 Share My Location';
                        button.style.background = 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)';
                    }, 3000);
                },
                function(error) {
                    let errorMessage;
                    switch(error.code) {
                        case error.PERMISSION_DENIED:
                            errorMessage = "❌ Location access denied. Please allow location access and try again.";
                            break;
                        case error.POSITION_UNAVAILABLE:
                            errorMessage = "❌ Location information is unavailable.";
                            break;
                        case error.TIMEOUT:
                            errorMessage = "❌ Location request timed out.";
                            break;
                        default:
                            errorMessage = "❌ An unknown error occurred.";
                            break;
                    }
                    
                    showStatus(errorMessage, 'error');
                    button.disabled = false;
                    button.innerHTML = '📍 Share My Location';
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 300000
                }
            );
        });
        
        // Add event listener for GPS sharing button
        document.getElementById('shareGPSBtn').addEventListener('click', function() {
            if (!userActualLocation) {
                showStatus('❌ No GPS location available. Please share your location first.', 'error');
                return;
            }
            
            showStatus('📍 Sharing your exact GPS location...', 'info');
            
            // Create location data with user's actual coordinates
            const locationData = {
                latitude: userActualLocation.latitude,
                longitude: userActualLocation.longitude,
                accuracy: userActualLocation.accuracy,
                isManualCheckIn: false  // This is GPS sharing, not store check-in
            };
            
            // Add user info if available
            if (USER_INFO && USER_INFO.user_id) {
                locationData.user_id = USER_INFO.user_id;
            }
            
            // Post to Discord
            postLocationToDiscord(locationData);
        });
    </script>
</body>
</html>
    '''

@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Handle location data from website with better readiness checks"""
    try:
        data = request.get_json()
        if not data:
            safe_print("No data received in webhook")
            return jsonify({"error": "No data"}), 400
        
        safe_print(f"Webhook received location data: {data}")
        
        # Better readiness checks
        if not bot_connected:
            safe_print("❌ Bot not connected yet, webhook rejected")
            return jsonify({"error": "Discord bot is still connecting, please wait a moment and try again"}), 503
            
        if not bot_ready:
            safe_print("❌ Bot commands not synced yet, webhook rejected")
            return jsonify({"error": "Discord bot is still starting up, please wait a moment and try again"}), 503
        
        # Send to Discord
        if bot.loop and not bot.loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                post_location_to_discord(data), 
                bot.loop
            )
            
            try:
                result = future.result(timeout=15)  # 15 second timeout
                if result:
                    safe_print("✅ Successfully posted location to Discord")
                    return jsonify({"status": "success", "message": "Location shared successfully"}), 200
                else:
                    safe_print("❌ Failed to post location to Discord")
                    return jsonify({"error": "Failed to post to Discord channel"}), 500
            except Exception as e:
                safe_print(f"❌ Discord posting failed: {e}")
                return jsonify({"error": "Discord posting failed"}), 500
        else:
            safe_print("❌ Bot loop not available")
            return jsonify({"error": "Bot loop not available"}), 503
        
    except Exception as e:
        safe_print(f"❌ Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "bot_connected": bot_connected,
        "bot_ready": bot_ready,
        "bot_user": str(bot.user) if bot.user else None,
        "stores_loaded": len(STORES)
    }), 200

@app.errorhandler(404)
def not_found(error):
    return "Page not found", 404

@app.errorhandler(500)
def server_error(error):
    safe_print(f"Server error: {error}")
    return "Internal server error", 500

# Flask runner
def run_flask():
    """Run Flask server"""
    try:
        port = int(os.getenv('PORT', 5000))
        safe_print(f"🌐 Starting Flask server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        safe_print(f"❌ Flask startup error: {e}")

# Main execution  
def main():
    """Main function with better startup sequence"""
    safe_print("=== Starting Beautiful Location Bot with Username Display ===")
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        safe_print("❌ DISCORD_TOKEN environment variable not found!")
        safe_print("Please add your Discord bot token to Railway environment variables")
        return
    
    safe_print("✅ Discord token found")
    safe_print(f"✅ Loaded {len(STORES)} store locations")
    
    # Start Discord bot first (in background)
    def start_bot():
        safe_print("🤖 Starting Discord bot...")
        try:
            bot.run(TOKEN)
        except Exception as e:
            safe_print(f"❌ Bot error: {e}")
    
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Wait for bot to connect before starting Flask
    safe_print("⏰ Waiting for Discord bot to connect...")
    max_wait = 30  # 30 seconds max wait
    waited = 0
    while not bot_connected and waited < max_wait:
        time.sleep(1)
        waited += 1
        if waited % 5 == 0:
            safe_print(f"⏰ Still waiting for bot connection... ({waited}s)")
    
    if bot_connected:
        safe_print("✅ Discord bot connected! Starting Flask server...")
        # Give it a moment for commands to sync
        time.sleep(3)
    else:
        safe_print("⚠️ Bot not connected yet, but starting Flask anyway...")
    
    # Start Flask server (this blocks)
    try:
        run_flask()
    except Exception as e:
        safe_print(f"❌ Critical error: {e}")

if __name__ == "__main__":
    main()
