#!/usr/bin/env python3
"""
Simple test script to check Railway environment and URLs
"""

import os
import requests
import json

def test_railway_environment():
    """Test Railway environment variables"""
    print("=== Railway Environment Test ===")
    
    # Check environment variables
    env_vars = {
        'RAILWAY_URL': os.getenv('RAILWAY_URL'),
        'RAILWAY_STATIC_URL': os.getenv('RAILWAY_STATIC_URL'),
        'PORT': os.getenv('PORT'),
        'DISCORD_TOKEN': 'SET' if os.getenv('DISCORD_TOKEN') else 'NOT SET',
        'GOOGLE_MAPS_API_KEY': 'SET' if os.getenv('GOOGLE_MAPS_API_KEY') else 'NOT SET'
    }
    
    print("Environment Variables:")
    for key, value in env_vars.items():
        print(f"  {key}: {value}")
    
    # Determine Railway URL
    railway_url = os.getenv('RAILWAY_URL')
    if not railway_url:
        railway_url = os.getenv('RAILWAY_STATIC_URL') or os.getenv('PORT') or 'https://location-bot-production.up.railway.app'
        if railway_url and not railway_url.startswith('http'):
            railway_url = f"https://location-bot-production.up.railway.app"
    
    print(f"\nDetermined Railway URL: {railway_url}")
    
    # Test endpoints
    endpoints = [
        '/',
        '/test',
        '/debug',
        '/health'
    ]
    
    print(f"\nTesting endpoints on {railway_url}:")
    for endpoint in endpoints:
        try:
            url = f"{railway_url}{endpoint}"
            print(f"  Testing {url}...")
            response = requests.get(url, timeout=10)
            print(f"    Status: {response.status_code}")
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"    Response: {json.dumps(data, indent=2)[:200]}...")
                except:
                    print(f"    Response: {response.text[:100]}...")
            else:
                print(f"    Error: {response.text[:100]}...")
        except Exception as e:
            print(f"    Error: {e}")
        print()

if __name__ == "__main__":
    test_railway_environment() 