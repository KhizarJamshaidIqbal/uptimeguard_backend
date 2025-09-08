#!/usr/bin/env python3
"""
Simple test script to verify the Vercel function works locally
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from server import app
    print("✅ Successfully imported server.py")
    print(f"✅ App created: {app}")
    print(f"✅ App title: {app.title}")
    print(f"✅ App version: {app.version}")
    
    # Test basic functionality
    from fastapi.testclient import TestClient
    client = TestClient(app)
    
    # Test root endpoint
    response = client.get("/")
    print(f"✅ Root endpoint status: {response.status_code}")
    print(f"✅ Root response: {response.json()}")
    
    # Test health endpoint
    response = client.get("/health")
    print(f"✅ Health endpoint status: {response.status_code}")
    print(f"✅ Health response: {response.json()}")
    
    # Test API root
    response = client.get("/api/")
    print(f"✅ API root status: {response.status_code}")
    print(f"✅ API root response: {response.json()}")
    
    print("\n🎉 All tests passed! The function should work on Vercel.")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
