#!/usr/bin/env python3
"""
Direct server runner for StatusTrackr
"""
import sys
import os
from pathlib import Path

# Add the backend directory to Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Set environment
os.environ.setdefault('MONGO_URL', 'mongodb://localhost:27017')
os.environ.setdefault('DB_NAME', 'statustrackr')

try:
    from server import app
    import uvicorn
    
    print("🚀 Starting StatusTrackr Backend Server...")
    print("📍 Server URL: http://localhost:8001")
    print("📚 API Docs: http://localhost:8001/docs")
    print("⚡ Interactive API: http://localhost:8001/redoc")
    print("\n⚠️  Note: MongoDB connection required for full functionality")
    print("💡 Tip: You can use MongoDB Atlas or local MongoDB")
    print("\n🔄 Starting server... (Press Ctrl+C to stop)\n")
    
    # Run server without auto-reload to avoid watchfiles dependency
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8001,  # Changed to port 8001 to avoid conflicts
        reload=False,  # Disable reload to avoid dependency issues
        access_log=True,
        log_level="info"
    )
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("\n🔧 Trying alternative startup method...")
    
    # Alternative method without uvicorn
    try:
        import asyncio
        from server import app
        
        async def run_app():
            import hypercorn.asyncio
            from hypercorn import Config
            
            config = Config()
            config.bind = ["0.0.0.0:8000"]
            config.debug = True
            
            await hypercorn.asyncio.serve(app, config)
        
        print("🚀 Starting with Hypercorn...")
        asyncio.run(run_app())
        
    except ImportError:
        print("❌ Neither uvicorn nor hypercorn available")
        print("🔧 Installing hypercorn as alternative...")
        
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'hypercorn'])
        
        print("✅ Hypercorn installed, restarting...")
        os.execv(sys.executable, [sys.executable] + sys.argv)
        
except Exception as e:
    print(f"❌ Server Error: {e}")
    print("\n🔍 Please check:")
    print("  1. MongoDB is running and accessible")
    print("  2. All dependencies are installed")
    print("  3. Environment variables are set correctly")
    sys.exit(1)