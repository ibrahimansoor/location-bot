#!/usr/bin/env python3
"""
Script to find the correct Railway URL
"""

import requests
import os

def test_railway_urls():
    """Test different Railway URL patterns"""
    print("=== Testing Railway URLs ===")
    
    # Get environment variables
    railway_url = os.getenv('RAILWAY_URL')
    railway_static_url = os.getenv('RAILWAY_STATIC_URL')
    port = os.getenv('PORT')
    railway_project_name = os.getenv('RAILWAY_PROJECT_NAME')
    railway_service_name = os.getenv('RAILWAY_SERVICE_NAME')
    
    print(f"Environment Variables:")
    print(f"  RAILWAY_URL: {railway_url}")
    print(f"  RAILWAY_STATIC_URL: {railway_static_url}")
    print(f"  PORT: {port}")
    print(f"  RAILWAY_PROJECT_NAME: {railway_project_name}")
    print(f"  RAILWAY_SERVICE_NAME: {railway_service_name}")
    
    # Test different URL patterns
    test_urls = [
        railway_url,
        railway_static_url,
        'https://terrific-trust-web.up.railway.app',
        'https://chic-miracle-web.up.railway.app',
        'https://location-bot-production.up.railway.app',
        'https://web-production-f0220.up.railway.app'
    ]
    
    if railway_project_name and railway_service_name:
        test_urls.append(f"https://{railway_project_name}-{railway_service_name}.up.railway.app")
    
    print(f"\nTesting URLs:")
    for url in test_urls:
        if not url:
            continue
            
        if not url.startswith('http'):
            continue
            
        print(f"  Testing {url}...")
        try:
            response = requests.get(url, timeout=5)
            print(f"    Status: {response.status_code}")
            if response.status_code == 200:
                print(f"    ✅ WORKING! This is the correct URL")
                return url
            elif response.status_code == 404:
                print(f"    ❌ 404 - Application not found")
            else:
                print(f"    ⚠️ {response.status_code} - {response.text[:100]}...")
        except Exception as e:
            print(f"    ❌ Error: {e}")
    
    print(f"\n❌ No working URLs found")
    return None

if __name__ == "__main__":
    working_url = test_railway_urls()
    if working_url:
        print(f"\n🎉 Found working Railway URL: {working_url}")
    else:
        print(f"\n💡 You may need to check your Railway dashboard for the correct URL") 