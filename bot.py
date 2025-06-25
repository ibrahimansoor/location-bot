import discord
from discord.ext import commands
import os
import math
import asyncio
import json
from flask import Flask, request, jsonify, send_from_directory
import threading
import time

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Flask app
app = Flask(__name__)

# Store locations (truncated for brevity - add your full list)
STORES = [
    {"name": "Target Burlington", "lat": 42.5042, "lng": -71.1956, "address": "51 Middlesex Tpke, Burlington, MA 01803"},
    {"name": "Target Cambridge", "lat": 42.3656, "lng": -71.1043, "address": "180 Somerville Ave, Cambridge, MA 02143"},
    {"name": "Target Danvers", "lat": 42.5751, "lng": -70.9395, "address": "112 Endicott St, Danvers, MA 01923"},
    {"name": "Walmart Chelmsford", "lat": 42.5998, "lng": -71.3670, "address": "66 Parkhurst Rd, Chelmsford, MA 01824"},
    {"name": "Best Buy Burlington", "lat": 42.5042, "lng": -71.1956, "address": "84 Middlesex Tpke, Burlington, MA 01803"},
    {"name": "BJs Wholesale Danvers", "lat": 42.5751, "lng": -70.9395, "address": "6 Hutchinson Dr, Danvers, MA 01923"}
]

# Global variables
LOCATION_CHANNEL_ID = None
bot_ready = False

def get_store_branding(store_name):
    """Return store-specific branding"""
    store_lower = store_name.lower()
    
    if "target" in store_lower:
        return {"emoji": "🎯", "color": 0xCC0000, "description": "Department Store"}
    elif "walmart" in store_lower:
        return {"emoji": "🏪", "color": 0x004C91, "description": "Superstore"}
    elif "best buy" in store_lower:
        return {"emoji": "🔌", "color": 0xFFE400, "description": "Electronics Store"}
    elif "bjs" in store_lower:
        return {"emoji": "🛒", "color": 0xFF6B35, "description": "Wholesale Club"}
    else:
        return {"emoji": "🏢", "color": 0x7289DA, "description": "Store Location"}

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance using Haversine formula"""
    R = 3958.8  # Earth radius in miles
    lat1_rad, lng1_rad, lat2_rad, lng2_rad = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2_rad - lat1_rad, lng2_rad - lng1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def find_closest_store(user_lat, user_lng):
    """Find closest store"""
    min_distance = float('inf')
    closest_store = None
    
    for store in STORES:
        distance = calculate_distance(user_lat, user_lng, store['lat'], store['lng'])
        if distance < min_distance:
            min_distance = distance
            closest_store = store
    
    return closest_store, min_distance

def get_status_indicator(distance):
    """Return status indicator"""
    if distance <= 0.2:
        return "🟢", "AT STORE"
    elif distance <= 1.0:
        return "🟡", "NEARBY"
    else:
        return "🔴", "FAR"

# Bot events
@bot.event
async def on_ready():
    global bot_ready
    print(f'✅ Bot connected: {bot.user}')
    print(f'📍 Loaded {len(STORES)} store locations')
    
    try:
        synced = await bot.tree.sync()
        print(f'🔄 Synced {len(synced)} commands')
        bot_ready = True
    except Exception as e:
        print(f'❌ Failed to sync: {e}')

# Bot commands
@bot.tree.command(name="ping", description="Test bot")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! Bot is working!")

@bot.tree.command(name="location", description="Share your location")
async def location_command(interaction: discord.Interaction):
    global LOCATION_CHANNEL_ID
    LOCATION_CHANNEL_ID = interaction.channel.id
    
    embed = discord.Embed(
        title="📍 Share Your Location",
        description="Click the link below to share your location!",
        color=0x7289DA
    )
    
    website_url = "https://web-production-f0220.up.railway.app"
    embed.add_field(
        name="🔗 Location Link",
        value=f"[Click here to share location]({website_url})",
        inline=False
    )
    
    embed.add_field(
        name="ℹ️ Instructions",
        value="• Click the link\n• Allow location access\n• Your location will be posted here",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# Location posting function
async def post_location_to_discord(location_data):
    global LOCATION_CHANNEL_ID
    
    if not LOCATION_CHANNEL_ID or not bot_ready:
        print("❌ Bot not ready or no channel set")
        return
    
    try:
        channel = bot.get_channel(LOCATION_CHANNEL_ID)
        if not channel:
            print(f"❌ Channel {LOCATION_CHANNEL_ID} not found")
            return
        
        lat = float(location_data['latitude'])
        lng = float(location_data['longitude'])
        accuracy = location_data.get('accuracy', 'Unknown')
        is_manual = location_data.get('isManualCheckIn', False)
        selected_store = location_data.get('selectedStore', None)
        
        # Find closest store
        closest_store, distance = find_closest_store(lat, lng)
        
        if not closest_store:
            print("❌ No stores found")
            return
        
        # Handle manual check-in
        if is_manual and selected_store:
            for store in STORES:
                if store['name'] == selected_store:
                    closest_store = store
                    distance = 0.0
                    break
        
        branding = get_store_branding(closest_store['name'])
        indicator, status = get_status_indicator(distance) if not is_manual else ("🟢", "AT STORE")
        
        # Create embed
        embed = discord.Embed(
            title=f"{branding['emoji']} Location: {closest_store['name']}",
            description=f"Someone is **{distance:.1f} miles** from {closest_store['name']}" if distance > 0 else f"Someone checked in to **{closest_store['name']}**",
            color=branding['color']
        )
        
        embed.add_field(name="🏪 Store", value=closest_store['name'], inline=True)
        embed.add_field(name="📏 Distance", value=f"{distance:.1f} miles", inline=True)
        embed.add_field(name="🎯 Status", value=status, inline=True)
        
        embed.add_field(name="📍 Address", value=closest_store['address'], inline=False)
        
        if is_manual:
            embed.add_field(name="✅ Check-in", value="Manual store selection", inline=True)
        else:
            embed.add_field(name="🎯 Accuracy", value=f"±{accuracy} meters", inline=True)
        
        maps_url = f"https://maps.google.com/maps?q={lat},{lng}"
        embed.add_field(name="🗺️ Map", value=f"[View on Google Maps]({maps_url})", inline=True)
        
        embed.set_footer(text="Location Sharing System")
        embed.timestamp = discord.utils.utcnow()
        
        await channel.send(embed=embed)
        print("✅ Location posted to Discord")
        
    except Exception as e:
        print(f"❌ Error posting location: {e}")

# Flask routes
@app.route('/')
def index():
    """Serve the main page"""
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "Location sharing page not found", 404

@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Receive location from website"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400
        
        print(f"📍 Received location: {data}")
        
        # Schedule Discord posting
        if bot_ready and bot.loop and not bot.loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                post_location_to_discord(data), 
                bot.loop
            )
            # Wait for completion with timeout
            try:
                future.result(timeout=5)
            except Exception as e:
                print(f"❌ Discord posting failed: {e}")
                return jsonify({"error": "Discord posting failed"}), 500
        else:
            return jsonify({"error": "Bot not ready"}), 503
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "bot_ready": bot_ready,
        "bot_user": str(bot.user) if bot.user else None
    })

# Flask runner
def run_flask():
    """Run Flask server"""
    port = int(os.getenv('PORT', 5000))
    print(f"🌐 Starting Flask on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# Main execution
def main():
    """Main function"""
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        print("❌ DISCORD_TOKEN not found!")
        return
    
    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask server starting...")
    
    # Give Flask time to start
    time.sleep(2)
    
    # Run Discord bot
    print("🤖 Starting Discord bot...")
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ Bot error: {e}")

if __name__ == "__main__":
    main()
