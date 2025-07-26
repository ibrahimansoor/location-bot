#!/usr/bin/env python3
"""
Simple test script for the Location Bot
Tests basic functionality and helps identify issues
"""

import requests
import json
import time
import os

def test_railway_url():
    """Test the Railway URL to make sure it's accessible"""
    print("🔗 Testing Railway URL...")
    
    # Try to get the Railway URL from environment
    railway_url = os.getenv('RAILWAY_URL', 'https://web-production-f0220.up.railway.app')
    
    if 'your-app' in railway_url:
        railway_url = 'https://web-production-f0220.up.railway.app'
    
    print(f"Testing URL: {railway_url}")
    
    try:
        # Test basic connectivity
        response = requests.get(f"{railway_url}/health", timeout=10)
        print(f"✅ Health check: {response.status_code}")
        
        if response.status_code == 200:
            health_data = response.json()
            print(f"Bot connected: {health_data.get('bot_connected', False)}")
            print(f"Bot ready: {health_data.get('bot_ready', False)}")
            print(f"Google Maps: {health_data.get('google_maps_available', False)}")
        
        # Test the main page
        response = requests.get(railway_url, timeout=10)
        print(f"✅ Main page: {response.status_code}")
        
        # Test the test endpoint
        response = requests.get(f"{railway_url}/test", timeout=10)
        print(f"✅ Test endpoint: {response.status_code}")
        
        if response.status_code == 200:
            test_data = response.json()
            print(f"Test data: {json.dumps(test_data, indent=2)}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        return False

def test_store_search():
    """Test the store search functionality"""
    print("\n🔍 Testing store search...")
    
    railway_url = os.getenv('RAILWAY_URL', 'https://web-production-f0220.up.railway.app')
    if 'your-app' in railway_url:
        railway_url = 'https://web-production-f0220.up.railway.app'
    
    # Test coordinates near Medford, MA
    test_data = {
        'latitude': 42.4184,
        'longitude': -71.1062,
        'radius': 5
    }
    
    try:
        response = requests.post(
            f"{railway_url}/api/search-stores",
            json=test_data,
            timeout=30
        )
        
        print(f"Search response: {response.status_code}")
        
        if response.status_code == 200:
            stores = response.json().get('stores', [])
            print(f"✅ Found {len(stores)} stores")
            
            for store in stores[:3]:  # Show first 3 stores
                print(f"  - {store.get('name', 'Unknown')}: {store.get('address', 'No address')}")
        else:
            print(f"❌ Search failed: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Search request failed: {e}")

def test_webhook():
    """Test the webhook endpoint"""
    print("\n📨 Testing webhook...")
    
    railway_url = os.getenv('RAILWAY_URL', 'https://web-production-f0220.up.railway.app')
    if 'your-app' in railway_url:
        railway_url = 'https://web-production-f0220.up.railway.app'
    
    # Test webhook with sample data
    test_data = {
        'latitude': 42.4184,
        'longitude': -71.1062,
        'user_id': '123456789',
        'channel_id': '987654321',
        'selectedStore': {
            'name': 'Target',
            'address': '471 Salem St, Medford, MA 02155, USA',
            'distance': 0.1,
            'place_id': 'test_target'
        },
        'session_id': 'test_session_123'
    }
    
    try:
        response = requests.post(
            f"{railway_url}/webhook/location",
            json=test_data,
            timeout=30
        )
        
        print(f"Webhook response: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Webhook test successful")
        else:
            print(f"❌ Webhook failed: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Webhook request failed: {e}")

def main():
    """Run all tests"""
    print("🧪 Location Bot Test Suite")
    print("=" * 40)
    
    # Test 1: Railway URL connectivity
    if test_railway_url():
        print("\n✅ Railway URL is accessible")
    else:
        print("\n❌ Railway URL is not accessible")
        return
    
    # Test 2: Store search
    test_store_search()
    
    # Test 3: Webhook
    test_webhook()
    
    print("\n🎉 Test suite completed!")

if __name__ == "__main__":
    main() 