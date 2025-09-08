from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime
from enum import Enum

# MongoDB connection (simplified for Vercel)
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get('MONGO_URL', 'mongodb+srv://khizarjamshaidiqbal_db_user:urCSH7kRPKhlqbdd@cluster0.no5fwid.mongodb.net/')
    db_name = os.environ.get('DB_NAME', 'statustrackr')
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    MONGO_AVAILABLE = True
except Exception as e:
    print(f"MongoDB connection failed: {e}")
    client = None
    db = None
    MONGO_AVAILABLE = False

# Create the main app
app = FastAPI(title="StatusTrackr API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Enums
class MonitorStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    WARNING = "warning"

class MonitorType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    SSL = "ssl"
    DNS = "dns"
    PORT = "port"
    PING = "ping"
    KEYWORD = "keyword"
    API = "api"

# Models
class MonitorCreate(BaseModel):
    name: str
    url: Optional[str] = None
    check_interval: int = 300
    monitor_type: MonitorType = MonitorType.HTTPS
    timeout: int = 10

class Monitor(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: Optional[str] = None
    check_interval: int
    monitor_type: MonitorType
    timeout: int
    status: MonitorStatus = MonitorStatus.UNKNOWN
    last_checked: Optional[datetime] = None
    response_time: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    uptime_percentage: float = 0.0

class DashboardStats(BaseModel):
    total_monitors: int
    monitors_up: int
    monitors_down: int
    overall_uptime: float

# API Routes
@api_router.get("/")
async def api_root():
    return {"message": "Uptime Monitoring API", "status": "running"}

@api_router.post("/monitors", response_model=Monitor)
async def create_monitor(monitor_data: MonitorCreate):
    """Create a new monitor"""
    if not MONGO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    monitor = Monitor(**monitor_data.dict())
    await db.monitors.insert_one(monitor.dict())
    return monitor

@api_router.get("/monitors", response_model=List[Monitor])
async def get_monitors():
    """Get all monitors"""
    if not MONGO_AVAILABLE:
        return []
    
    monitors = await db.monitors.find().to_list(1000)
    return [Monitor(**monitor) for monitor in monitors]

@api_router.get("/monitors/{monitor_id}", response_model=Monitor)
async def get_monitor(monitor_id: str):
    """Get a specific monitor"""
    if not MONGO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    monitor = await db.monitors.find_one({"id": monitor_id})
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return Monitor(**monitor)

@api_router.delete("/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str):
    """Delete a monitor"""
    if not MONGO_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    
    result = await db.monitors.delete_one({"id": monitor_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    return {"message": "Monitor deleted successfully"}

@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    if not MONGO_AVAILABLE:
        return DashboardStats(
            total_monitors=0,
            monitors_up=0,
            monitors_down=0,
            overall_uptime=0.0
        )
    
    monitors = await db.monitors.find().to_list(1000)
    
    total_monitors = len(monitors)
    monitors_up = sum(1 for m in monitors if m.get("status") == MonitorStatus.UP)
    monitors_down = sum(1 for m in monitors if m.get("status") == MonitorStatus.DOWN)
    
    if total_monitors > 0:
        total_uptime = sum(m.get("uptime_percentage", 0) for m in monitors)
        overall_uptime = total_uptime / total_monitors
    else:
        overall_uptime = 0.0
    
    return DashboardStats(
        total_monitors=total_monitors,
        monitors_up=monitors_up,
        monitors_down=monitors_down,
        overall_uptime=overall_uptime
    )

# Root endpoint for the main app
@app.get("/")
async def main_root():
    return {
        "message": "StatusTrackr Backend API",
        "version": "1.0.0",
        "status": "running",
        "deployment": "vercel",
        "database": "connected" if MONGO_AVAILABLE else "disconnected",
        "endpoints": {
            "api_root": "/api/",
            "api_docs": "/docs",
            "monitors": "/api/monitors",
            "dashboard": "/api/dashboard/stats"
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected" if MONGO_AVAILABLE else "disconnected",
        "mongo_url_configured": bool(os.environ.get('MONGO_URL'))
    }

# Include the router in the main app
app.include_router(api_router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Vercel handler
handler = app
