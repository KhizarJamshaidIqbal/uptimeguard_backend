#!/usr/bin/env python3
"""
StatusTrackr Setup and Startup Script
"""
import subprocess
import sys
import os

def install_dependencies():
    """Install Python dependencies"""
    required_packages = [
        'fastapi==0.110.1',
        'uvicorn==0.25.0',
        'python-dotenv>=1.0.1',
        'pymongo==4.5.0',
        'motor==3.3.1',
        'pydantic>=2.6.4',
        'aiohttp>=3.9.0',
        'dnspython'
    ]
    
    for package in required_packages:
        try:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
            print(f"✓ {package} installed successfully")
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install {package}: {e}")
            return False
    return True

def start_server():
    """Start the FastAPI server"""
    try:
        # Change to backend directory
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(backend_dir)
        
        print("Starting StatusTrackr backend server...")
        print("Server will be available at: http://localhost:8000")
        print("API documentation: http://localhost:8000/docs")
        print("\nPress Ctrl+C to stop the server\n")
        
        # Start uvicorn server
        subprocess.run([
            sys.executable, '-m', 'uvicorn', 
            'server:app', 
            '--host', '0.0.0.0', 
            '--port', '8000', 
            '--reload'
        ])
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"Error starting server: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        if install_dependencies():
            print("\n✅ All dependencies installed successfully!")
        else:
            print("\n❌ Some dependencies failed to install")
            sys.exit(1)
    else:
        start_server()