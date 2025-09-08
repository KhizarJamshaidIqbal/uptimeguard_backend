#!/usr/bin/env python3
"""
Test script to verify the Vercel deployment function works
"""

try:
    from index import handler
    print("✅ Successfully imported handler from index.py")
    
    # Test the handler
    from fastapi.testclient import TestClient
    client = TestClient(handler)
    
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
    
    print("\n🎉 All tests passed! Ready for Vercel deployment.")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
