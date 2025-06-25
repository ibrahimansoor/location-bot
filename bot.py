import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="location", description="Get a link to share your location")
async def location(interaction: discord.Interaction):
    """Share location command"""
    location_url = "https://ibrahimansoor.github.io/location-bot"
    
    embed = discord.Embed(
        title="📍 Share Your Location", 
        description="Click the link below to share your location with the server!",
        color=0x5865F2
    )
    
    embed.add_field(
        name="🔗 Location Link", 
        value=f"[Click here to share location]({location_url})",
        inline=False
    )
    
    embed.add_field(
        name="ℹ️ How it works",
        value="• Click the link\n• Allow location access\n• Your location will be posted here automatically",
        inline=False
    )
    
    embed.set_footer(text="Your location data is not stored and only shared with this Discord server.")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Check if the bot is working")
async def ping(interaction: discord.Interaction):
    """Simple ping command to test bot"""
    await interaction.response.send_message("🏓 Pong! Bot is online and working!")

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')

if TOKEN is None:
    print("ERROR: DISCORD_TOKEN environment variable not found!")
    print("Please set your Discord bot token in the environment variables.")
else:
    bot.run(TOKEN)
