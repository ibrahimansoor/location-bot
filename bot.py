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

# Simplified store list for testing
STORES = [
    {"name": "Target Burlington", "lat": 42.5042, "lng": -71.1956, "address": "51 Middlesex Tpke, Burlington, MA 01803"},
    {"name": "Target Cambridge", "lat": 42.3656, "lng": -71.1043, "address": "180 Somerville Ave, Cambridge, MA 02143"},
    {"name": "Walmart Chelmsford", "lat": 42.5998, "lng": -71.3670, "address": "66 Parkhurst Rd, Chelmsford, MA 01824"},
    {"name": "Best Buy Burlington", "lat": 42.5042, "lng": -71.1956, "address": "84 Middlesex Tpke, Burlington, MA 01803"}
]

# Global state
LOCATION_CHANNEL_ID = None
bot_ready = False

def safe_print(msg):
    """Safe printing for Railway logs"""
    try:
        print(f"[BOT] {msg}")
        sys.stdout.flush()
    except:
        pass

def get_store_branding(store_name):
    """Get store emoji and color"""
    if "target" in store_name.lower():
        return {"emoji": "🎯", "color": 0xCC0000}
    elif "walmart" in store_name.lower():
        return {"emoji": "🏪", "color": 0x004C91}
    elif "best buy" in store_name.lower():
        return {"emoji": "🔌", "color": 0xFFE400}
    else:
        return {"emoji": "🏢", "color": 0x7289DA}

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calculate distance between two points"""
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

# Bot events
@bot.event
async def on_ready():
    global bot_ready
    safe_print(f"Discord bot connected: {bot.user}")
    safe_print(f"Loaded {len(STORES)} store locations")
    
    try:
        synced = await bot.tree.sync()
        safe_print(f"Synced {len(synced)} slash commands")
        bot_ready = True
    except Exception as e:
        safe_print(f"Failed to sync commands: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    safe_print(f"Bot error in {event}: {args}")

# Bot commands
@bot.tree.command(name="ping", description="Test if bot is working")
async def ping(interaction: discord.Interaction):
    """Test command"""
    try:
        await interaction.response.send_message("🏓 Pong! Bot is working!")
    except Exception as e:
        safe_print(f"Ping command error: {e}")

@bot.tree.command(name="location", description="Share your location with the team")
async def location_command(interaction: discord.Interaction):
    """Location sharing command"""
    global LOCATION_CHANNEL_ID
    
    try:
        LOCATION_CHANNEL_ID = interaction.channel.id
        safe_print(f"Location command used in channel {LOCATION_CHANNEL_ID}")
        
        embed = discord.Embed(
            title="📍 Share Your Location",
            description="Click the link below to share your location with the team!",
            color=0x7289DA
        )
        
        # Use the Railway URL
        website_url = "https://web-production-f0220.up.railway.app"
        embed.add_field(
            name="🔗 Location Link",
            value=f"[Click here to share location]({website_url})",
            inline=False
        )
        
        embed.add_field(
            name="ℹ️ How it works",
            value="• Click the link\n• Allow location access\n• Your location will be posted here automatically",
            inline=False
        )
        
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
    """Post location update to Discord"""
    global LOCATION_CHANNEL_ID, bot_ready
    
    try:
        if not LOCATION_CHANNEL_ID or not bot_ready:
            safe_print("Bot not ready or no channel set")
            return False
        
        channel = bot.get_channel(LOCATION_CHANNEL_ID)
        if not channel:
            safe_print(f"Channel {LOCATION_CHANNEL_ID} not found")
            return False
        
        lat = float(location_data['latitude'])
        lng = float(location_data['longitude'])
        accuracy = location_data.get('accuracy', 'Unknown')
        is_manual = location_data.get('isManualCheckIn', False)
        selected_store = location_data.get('selectedStore', None)
        
        safe_print(f"Processing location: {lat}, {lng}, manual: {is_manual}")
        
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
                    distance = 0.0
                    break
        
        branding = get_store_branding(closest_store['name'])
        
        # Create embed
        embed = discord.Embed(
            title=f"{branding['emoji']} Location Update",
            description=f"Someone is **{distance:.1f} miles** from {closest_store['name']}" if distance > 0 else f"Someone checked in to **{closest_store['name']}**",
            color=branding['color']
        )
        
        embed.add_field(name="🏪 Store", value=closest_store['name'], inline=True)
        embed.add_field(name="📏 Distance", value=f"{distance:.1f} miles", inline=True)
        
        if is_manual:
            embed.add_field(name="✅ Method", value="Manual Check-in", inline=True)
        else:
            embed.add_field(name="🎯 Accuracy", value=f"±{accuracy}m", inline=True)
        
        embed.add_field(name="📍 Address", value=closest_store['address'], inline=False)
        
        maps_url = f"https://maps.google.com/maps?q={lat},{lng}"
        embed.add_field(name="🗺️ View on Map", value=f"[Google Maps]({maps_url})", inline=False)
        
        embed.set_footer(text="Location Sharing System")
        embed.timestamp = discord.utils.utcnow()
        
        await channel.send(embed=embed)
        safe_print("Successfully posted location to Discord")
        return True
        
    except Exception as e:
        safe_print(f"Error posting to Discord: {e}")
        return False

# Flask routes
@app.route('/', methods=['GET'])
def index():
    """Serve the location sharing page"""
    safe_print("Serving index page")
    return '''
<!DOCTYPE html>
<html>
<head>
    <title>Location Sharing</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
               min-height: 100vh; display: flex; justify-content: center; align-items: center; margin: 0; padding: 20px; }
        .container { background: white; border-radius: 20px; padding: 40px; max-width: 400px; width: 100%; 
                    box-shadow: 0 10px 30px rgba(0,0,0,0.2); text-align: center; }
        h1 { color: #333; margin-bottom: 20px; }
        .btn { background: #667eea; color: white; border: none; padding: 15px 30px; border-radius: 10px; 
               font-size: 16px; cursor: pointer; width: 100%; margin: 10px 0; }
        .btn:hover { background: #5a6fd8; }
        .btn:disabled { opacity: 0.6; cursor: not-allowed; }
        .status { padding: 15px; border-radius: 10px; margin: 20px 0; display: none; }
        .success { background: #d4edda; color: #155724; }
        .error { background: #f8d7da; color: #721c24; }
        .info { background: #d1ecf1; color: #0c5460; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📍 Share Your Location</h1>
        <p>Let your team know where you are!</p>
        
        <button id="shareBtn" class="btn">📍 Share My Location</button>
        <div id="status" class="status"></div>
        
        <script>
        function showStatus(msg, type) {
            const status = document.getElementById('status');
            status.textContent = msg;
            status.className = 'status ' + type;
            status.style.display = 'block';
        }
        
        async function sendLocation(data) {
            try {
                console.log('Sending location:', data);
                const response = await fetch('/webhook/location', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (response.ok) {
                    showStatus('✅ Location shared successfully!', 'success');
                    setTimeout(() => {
                        showStatus('🔄 Returning to Discord...', 'info');
                        setTimeout(() => {
                            try { window.close(); } 
                            catch(e) { 
                                window.location.href = 'discord://';
                                setTimeout(() => showStatus('✅ You can return to Discord now.', 'success'), 1000);
                            }
                        }, 1000);
                    }, 2000);
                } else {
                    throw new Error('Failed to send location');
                }
            } catch (error) {
                console.error('Error:', error);
                showStatus('❌ Failed to share location: ' + error.message, 'error');
                document.getElementById('shareBtn').disabled = false;
                document.getElementById('shareBtn').textContent = '📍 Share My Location';
            }
        }
        
        document.getElementById('shareBtn').addEventListener('click', function() {
            if (!navigator.geolocation) {
                showStatus('❌ Geolocation not supported', 'error');
                return;
            }
            
            this.disabled = true;
            this.textContent = '⏳ Getting location...';
            showStatus('📍 Requesting location access...', 'info');
            
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    sendLocation({
                        latitude: position.coords.latitude,
                        longitude: position.coords.longitude,
                        accuracy: Math.round(position.coords.accuracy)
                    });
                },
                function(error) {
                    let msg = '❌ ';
                    switch(error.code) {
                        case error.PERMISSION_DENIED: msg += 'Location access denied'; break;
                        case error.POSITION_UNAVAILABLE: msg += 'Location unavailable'; break;
                        case error.TIMEOUT: msg += 'Location request timed out'; break;
                        default: msg += 'Unknown error'; break;
                    }
                    showStatus(msg, 'error');
                    document.getElementById('shareBtn').disabled = false;
                    document.getElementById('shareBtn').textContent = '📍 Share My Location';
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
            );
        });
        </script>
    </div>
</body>
</html>
    '''

@app.route('/webhook/location', methods=['POST'])
def location_webhook():
    """Handle location data from website"""
    try:
        data = request.get_json()
        if not data:
            safe_print("No data received in webhook")
            return jsonify({"error": "No data"}), 400
        
        safe_print(f"Webhook received location data: {data}")
        
        # Send to Discord
        if bot_ready and bot.loop and not bot.loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(
                post_location_to_discord(data), 
                bot.loop
            )
            
            try:
                result = future.result(timeout=10)  # 10 second timeout
                if result:
                    return jsonify({"status": "success"}), 200
                else:
                    return jsonify({"error": "Failed to post to Discord"}), 500
            except Exception as e:
                safe_print(f"Discord posting failed: {e}")
                return jsonify({"error": "Discord posting failed"}), 500
        else:
            safe_print("Bot not ready for webhook")
            return jsonify({"error": "Bot not ready"}), 503
        
    except Exception as e:
        safe_print(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
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
        safe_print(f"Starting Flask server on port {port}")
        app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        safe_print(f"Flask startup error: {e}")

# Main execution
def main():
    """Main function"""
    safe_print("=== Starting Location Bot ===")
    
    TOKEN = os.getenv('DISCORD_TOKEN')
    if not TOKEN:
        safe_print("❌ DISCORD_TOKEN environment variable not found!")
        safe_print("Please add your Discord bot token to Railway environment variables")
        return
    
    safe_print("✅ Discord token found")
    
    # Start Flask server in background
    try:
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        safe_print("🌐 Flask server thread started")
        
        # Give Flask time to start
        time.sleep(3)
        safe_print("⏰ Starting Discord bot...")
        
        # Run Discord bot (this blocks)
        bot.run(TOKEN)
        
    except Exception as e:
        safe_print(f"❌ Critical error: {e}")

if __name__ == "__main__":
    main()
