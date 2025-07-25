# Location Bot - Simple Store Check-ins

A simplified Discord bot for real-time store check-ins with minimal, essential information.

## Features

- **📍 Real-time Location**: Get your current location instantly
- **🏪 Store Check-ins**: Find and check in to nearby stores
- **📱 Simple & Fast**: Quick and easy check-in process
- **💬 Discord Integration**: Posts directly to your Discord channel
- **🗑️ Auto-cleanup**: Removes previous check-in embeds automatically

## What the Bot Shows

The bot creates simple embeds with only the essential information:
- **Store name**
- **Store address**
- **Distance from the person checking in**
- **Real-time location data**

## Commands

- `/location` - Start a location sharing session
- `/ping` - Check bot status
- `/search [category] [radius]` - Search for specific store types
- `/favorites [action]` - Manage favorite locations
- `/stats [scope]` - View usage statistics
- `/setperm [user] [role]` - Set user permissions (Admin only)

## Setup

1. **Environment Variables**:
   ```
   DISCORD_TOKEN=your_discord_bot_token
   GOOGLE_MAPS_API_KEY=your_google_maps_api_key
   RAILWAY_URL=your_railway_url (optional)
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the Bot**:
   ```bash
   python bot.py
   ```

## How It Works

1. User runs `/location` in Discord
2. Bot provides a link to the location portal
3. User clicks the link and allows location access
4. User selects a store from the nearby options
5. Bot posts a simple embed with store name, address, and distance
6. Previous check-in embed is automatically deleted

## Database

The bot uses SQLite to store:
- User locations and check-ins
- User permissions
- Favorite locations
- Usage analytics

## API Endpoints

- `GET /` - Location sharing portal
- `POST /api/search-stores` - Search for nearby stores
- `POST /webhook/location` - Process location check-ins
- `GET /health` - Health check endpoint

## Simplified Design

This bot focuses on simplicity and speed:
- ✅ Essential information only
- ✅ Fast loading times
- ✅ Mobile-friendly interface
- ✅ Automatic cleanup of old embeds
- ❌ No weather data
- ❌ No complex analytics
- ❌ No group sharing features
- ❌ No detailed store ratings

Perfect for teams that just need to know where their members are checking in without overwhelming information.