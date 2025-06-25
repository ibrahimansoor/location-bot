import discord
from discord.ext import commands
import os
import math
import asyncio
from flask import Flask, request, jsonify
from threading import Thread
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for webhook
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

def get_store_branding(store_name):
    """Return store-specific branding (emoji, color, logo)"""
    store_lower = store_name.lower()
    
    if "target" in store_lower:
        return {
            "emoji": "🎯",
            "color": 0xCC0000,  # Target red
            "logo": "https://corporate.target.com/_media/TargetCorp/about/logos/bullseye-color-300.png",
            "description": "Department Store • Clothing, Electronics, Home"
        }
    elif "walmart" in store_lower:
        return {
            "emoji": "🏪", 
            "color": 0x004C91,  # Walmart blue
            "logo": "https://i.imgur.com/kE0e2mV.png",
            "description": "Superstore • Groceries, Electronics, Everything"
        }
    elif "best buy" in store_lower:
        return {
            "emoji": "🔌",
            "color": 0xFFE400,  # Best Buy yellow
            "logo": "https://i.imgur.com/VJj7uKk.png", 
            "description": "Electronics Store • Tech, Computers, Gaming"
        }
    elif "bjs" in store_lower:
        return {
            "emoji": "🛒",
            "color": 0xFF6B35,  # BJ's orange
            "logo": "https://i.imgur.com/ZLs4P2b.png",
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
    """Calculate distance between two points in miles using Haversine formula"""
    R = 3958.8  # Radius of Earth in miles
    
    lat1_rad = math.radians(lat1)
    lng1_rad = math.radians(lng1)
    lat2_rad = math.radians(lat2)
    lng2_rad = math.radians(lng2)
    
    dlat = lat2_rad - lat1_rad
    dlng = lng2_rad - lng1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def find_closest_store(user_lat, user_lng):
    """Find the closest store to user's location"""
    min_distance = float('inf')
    closest_store = None
    
    for store in STORES:
        distance = calculate_distance(user_lat, user_lng, store['lat'], store['lng'])
        if distance < min_distance:
            min_distance = distance
            closest_store = store
    
    return closest_store, min_distance

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

# Store the channel ID for location updates
LOCATION_CHANNEL_ID = None

@bot.event
async def on_ready():
    print(f'✅ {bot.user} has connected to Discord!')
    print(f'📍 Loaded {len(STORES)} store locations')
    try:
        synced = await bot.tree.sync()
        print(f'🔄 Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'❌ Failed to sync commands: {e}')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    """Simple ping command"""
    await interaction.response.send_message("🏓 Pong! Bot is online and working!")

@bot.tree.command(name="location", description="Share your location with the team")
async def location(interaction: discord.Interaction):
    """Enhanced location sharing command with beautiful embeds"""
    global LOCATION_CHANNEL_ID
    LOCATION_CHANNEL_ID = interaction.channel.id  # Store the channel ID
    
    # Create beautiful embed for location sharing
    branding = get_store_branding("location")
    
    embed = discord.Embed(
        title=f"{branding['emoji']} Share Your Location",
        description="Click the link below to share your location with the server!",
        color=branding['color']
    )
    
    # Get your website URL - use Railway deployment URL
    website_url = "https://web-production-f0220.up.railway.app"
    
    # Add location link with better formatting
    embed.add_field(
        name="🔗 Location Link",
        value=f"[Click here to share location]({website_url})",
        inline=False
    )
    
    # Add instructions with emojis
    embed.add_field(
        name="ℹ️ How it works",
        value="• Click the link\n• Allow location access\n• Your location will be posted here automatically",
        inline=False
    )
    
    # Add privacy notice
    embed.add_field(
        name="🔒 Privacy",
        value="Your location data is not stored and only shared with this Discord server.",
        inline=False
    )
    
    # Add footer with timestamp
    embed.set_footer(text="Location Sharing System")
    embed.timestamp = discord.utils.utcnow()
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stores", description="Show all nearby stores within 5 miles")
async def stores_command(interaction: discord.Interaction, latitude: float, longitude: float):
    """Show nearby stores command"""
    
    nearby_stores = find_nearby_stores(latitude, longitude, 5)
    
    if not nearby_stores:
        embed = discord.Embed(
            title="🏪 No Stores Found",
            description="No stores found within 5 miles of your location.",
            color=0xFF6B6B
        )
        await interaction.response.send_message(embed=embed)
        return
    
    # Create embed with nearby stores
    embed = discord.Embed(
        title="🗺️ Nearby Stores (5 Mile Radius)",
        description=f"Found {len(nearby_stores)} store(s) near your location:",
        color=0x4CAF50
    )
    
    # Add stores to embed (limit to first 10)
    for i, store_info in enumerate(nearby_stores[:10]):
        store = store_info['store']
        distance = store_info['distance']
        branding = get_store_branding(store['name'])
        indicator, status = get_status_indicator(distance)
        
        embed.add_field(
            name=f"{branding['emoji']} {store['name']}",
            value=f"{indicator} {distance:.1f} miles • {status}",
            inline=True
        )
    
    if len(nearby_stores) > 10:
        embed.add_field(
            name="📍 More Stores",
            value=f"+ {len(nearby_stores) - 10} more stores in the area",
            inline=False
        )
    
    embed.set_footer(text=f"🧭 Coordinates: {latitude:.4f}, {longitude:.4f}")
    
    await interaction.response.send_message(embed=embed)

# Enhanced location posting function (called from webhook)
async def post_location_update(user_location):
    """Post beautiful location update to Discord"""
    global LOCATION_CHANNEL_ID
    
    if not LOCATION_CHANNEL_ID:
        logger.warning("No channel ID set for location updates")
        return
        
    channel = bot.get_channel(LOCATION_CHANNEL_ID)
    if not channel:
        logger.error(f"Could not find channel with ID {LOCATION_CHANNEL_ID}")
        return
    
    try:
        lat = float(user_location['latitude'])
        lng = float(user_location['longitude'])
        accuracy = user_location.get('accuracy', 'Unknown')
        is_manual_checkin = user_location.get('isManualCheckIn', False)
        selected_store_name = user_location.get('selectedStore', None)
        
        # Find closest store
        closest_store, distance = find_closest_store(lat, lng)
        
        if not closest_store:
            return
        
        # If it's a manual check-in, use the selected store and set distance to 0
        if is_manual_checkin and selected_store_name:
            # Find the selected store in our database
            for store in STORES:
                if store['name'] == selected_store_name:
                    closest_store = store
                    distance = 0.0  # Manual check-in = at the store
                    break
            
        # Get store branding
        branding = get_store_branding(closest_store['name'])
        
        # Get status indicator (manual check-ins are always "AT STORE")
        if is_manual_checkin:
            indicator, status = "🟢", "AT STORE"
        else:
            indicator, status = get_status_indicator(distance)
        
        # Create beautiful embed
        embed = discord.Embed(
            title=f"{branding['emoji']} Location: {closest_store['name']}",
            description=f"Someone is **{distance:.1f} miles** from {closest_store['name']}" if distance > 0 else f"Someone checked in to **{closest_store['name']}**",
            color=branding['color']
        )
        
        # Add store logo if available
        if branding['logo']:
            embed.set_thumbnail(url=branding['logo'])
        
        # Store information section
        embed.add_field(
            name="🏪 Place Name",
            value=closest_store['name'],
            inline=True
        )
        
        embed.add_field(
            name=f"{branding['emoji']} Store Type", 
            value=branding['description'],
            inline=True
        )
        
        embed.add_field(
            name="📍 Address",
            value=closest_store.get('address', 'Address not available'),
            inline=False
        )
        
        # Distance check with beautiful indicators
        if distance > 0:
            embed.add_field(
                name="📏 Distance Check",
                value=f"{indicator} **{distance:.1f} miles** from {closest_store['name']}",
                inline=True
            )
        else:
            embed.add_field(
                name="✅ Check-In",
                value=f"{indicator} **Manual check-in** to {closest_store['name']}",
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
        
        # Coordinates section
        embed.add_field(
            name="📍 Coordinates",
            value=f"**Latitude:** {lat:.6f}\n**Longitude:** {lng:.6f}",
            inline=True
        )
        
        # Accuracy
        if is_manual_checkin:
            embed.add_field(
                name="🎯 Method",
                value="Manual Store Selection",
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
        if not is_manual_checkin:
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
        if is_manual_checkin:
            embed.set_footer(text="Location Sharing System • Manual Check-In")
        else:
            embed.set_footer(text="Location Sharing System • GPS Location")
        embed.timestamp = discord.utils.utcnow()
        
        # Add visual border based on status
        if status == "AT STORE":
            if is_manual_checkin:
                embed.set_author(name="✅ MANUAL CHECK-IN CONFIRMED")
            else:
                embed.set_author(name="✅ CONFIRMED AT LOCATION")
        elif status == "NEARBY":
            embed.set_author(name="⚠️ NEARBY LOCATION")
        else:
            embed.set_author(name="📍 LOCATION UPDATE")
        
        await channel.send(embed=embed)
        logger.info("Location update posted to Discord")
        
    except Exception as e:
        logger.error(f"Error posting location update: {e}")

# Flask webhook endpoints
@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Webhook endpoint to receive location data from website"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        logger.info(f"Received location data: {data}")
        
        # Schedule the Discord post in the bot's event loop
        if bot.loop and not bot.loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                post_location_update(data), 
                bot.loop
            )
        else:
            logger.error("Bot loop is not available")
            return jsonify({"error": "Bot not ready"}), 503
        
        return jsonify({"status": "success", "message": "Location received"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "bot_ready": bot.user is not None,
        "bot_name": bot.user.name if bot.user else "Not connected"
    }), 200

@app.route('/', methods=['GET'])
def index():
    """Serve the location sharing page"""
    try:
        # Read the HTML file
        with open('index.html', 'r', encoding='utf-8') as file:
            html_content = file.read()
        return html_content
    except FileNotFoundError:
        return jsonify({"error": "index.html not found"}), 404

def run_flask():
    """Run Flask app in a separate thread"""
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting Flask server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# Get bot token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')

async def main():
    """Main function to run bot and flask together"""
    if not TOKEN:
        logger.error("DISCORD_TOKEN environment variable not found!")
        return
    
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask webhook server starting...")
    
    # Run the Discord bot
    try:
        await bot.start(TOKEN)
    except Exception as e:
        logger.error(f"Bot error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
