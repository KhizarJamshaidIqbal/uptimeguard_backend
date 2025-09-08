#!/usr/bin/env python3
"""
Mock StatusTrackr Backend Server for Demo
This version works without MongoDB and provides sample data
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import time
import random

# Create the app
app = FastAPI(title="StatusTrackr Mock API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mock data storage
monitors_db = {}
uptime_logs_db = {}
alert_settings_db = {}

# Models
class MonitorCreate(BaseModel):
    name: str
    url: Optional[str] = None
    check_interval: int = 300
    monitor_type: str = "https"
    timeout: int = 10

class Monitor(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    url: Optional[str] = None
    check_interval: int
    monitor_type: str
    timeout: int
    status: str = "up"
    last_checked: Optional[datetime] = None
    response_time: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    uptime_percentage: float = 99.5

class DashboardStats(BaseModel):
    total_monitors: int
    monitors_up: int
    monitors_down: int
    overall_uptime: float

class UptimeLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    monitor_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str
    response_time: Optional[float] = None
    error_message: Optional[str] = None

class AlertSettings(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    monitor_id: str
    email_enabled: bool = True
    email_address: str
    alert_on_down: bool = True
    alert_on_up: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AlertSettingsCreate(BaseModel):
    monitor_id: str
    email_address: str
    alert_on_down: bool = True
    alert_on_up: bool = True

# Initialize some sample data
def init_sample_data():
    sample_monitors = [
        {
            "name": "Google Search",
            "url": "https://www.google.com",
            "monitor_type": "https",
            "check_interval": 300,
            "timeout": 10,
            "status": "up",
            "response_time": 0.123,
            "uptime_percentage": 99.9
        },
        {
            "name": "GitHub",
            "url": "https://github.com",
            "monitor_type": "https",
            "check_interval": 300,
            "timeout": 10,
            "status": "up",
            "response_time": 0.456,
            "uptime_percentage": 99.8
        },
        {
            "name": "Example API",
            "url": "https://jsonplaceholder.typicode.com/posts/1",
            "monitor_type": "api",
            "check_interval": 300,
            "timeout": 10,
            "status": "down",
            "response_time": None,
            "uptime_percentage": 85.2
        }
    ]
    
    for monitor_data in sample_monitors:
        monitor = Monitor(**monitor_data)
        monitor.last_checked = datetime.utcnow()
        monitors_db[monitor.id] = monitor.dict()
        
        # Create sample logs
        for i in range(24):
            log = UptimeLog(
                monitor_id=monitor.id,
                status=random.choice(["up", "up", "up", "down"]) if monitor_data["status"] == "down" else "up",
                response_time=random.uniform(0.1, 2.0) if monitor_data["status"] == "up" else None,
                timestamp=datetime.utcnow() - timedelta(hours=i)
            )
            uptime_logs_db[log.id] = log.dict()

# API Routes
@app.get("/api/")
async def root():
    return {"message": "StatusTrackr Mock API - Running successfully!"}

@app.post("/api/monitors", response_model=Monitor)
async def create_monitor(monitor_data: MonitorCreate):
    monitor = Monitor(**monitor_data.dict())
    monitor.last_checked = datetime.utcnow()
    monitor.response_time = random.uniform(0.1, 1.0)
    monitor.status = random.choice(["up", "up", "up", "down"])
    monitors_db[monitor.id] = monitor.dict()
    return monitor

@app.get("/api/monitors", response_model=List[Monitor])
async def get_monitors():
    return [Monitor(**monitor) for monitor in monitors_db.values()]

@app.get("/api/monitors/{monitor_id}", response_model=Monitor)
async def get_monitor(monitor_id: str):
    if monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return Monitor(**monitors_db[monitor_id])

@app.delete("/api/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str):
    if monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    del monitors_db[monitor_id]
    # Delete related logs
    to_delete = [log_id for log_id, log in uptime_logs_db.items() if log["monitor_id"] == monitor_id]
    for log_id in to_delete:
        del uptime_logs_db[log_id]
    return {"message": "Monitor deleted successfully"}

@app.post("/api/monitors/{monitor_id}/check")
async def manual_check_monitor(monitor_id: str):
    if monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Simulate check
    status = random.choice(["up", "up", "up", "down"])
    response_time = random.uniform(0.1, 2.0) if status == "up" else None
    error = None if status == "up" else "Connection timeout"
    
    # Update monitor
    monitors_db[monitor_id]["status"] = status
    monitors_db[monitor_id]["response_time"] = response_time
    monitors_db[monitor_id]["last_checked"] = datetime.utcnow()
    
    return {
        "status": status,
        "response_time": response_time,
        "error": error,
        "additional_data": {}
    }

@app.get("/api/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    monitors = list(monitors_db.values())
    total_monitors = len(monitors)
    monitors_up = sum(1 for m in monitors if m.get("status") == "up")
    monitors_down = sum(1 for m in monitors if m.get("status") == "down")
    
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

@app.get("/api/monitors/{monitor_id}/history")
async def get_monitor_history(monitor_id: str, hours: int = 24):
    if monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Generate mock history data
    history = []
    for i in range(hours):
        timestamp = datetime.utcnow() - timedelta(hours=i)
        uptime_percentage = random.uniform(85, 100)
        avg_response_time = random.uniform(100, 1000)  # in ms
        
        history.append({
            "timestamp": timestamp,
            "uptime_percentage": uptime_percentage,
            "avg_response_time": avg_response_time,
            "total_checks": random.randint(10, 20)
        })
    
    return list(reversed(history))

@app.get("/api/monitors/{monitor_id}/logs")
async def get_monitor_logs(monitor_id: str, hours: int = 24):
    if monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Filter logs for this monitor
    logs = [UptimeLog(**log) for log in uptime_logs_db.values() 
            if log["monitor_id"] == monitor_id]
    
    # Sort by timestamp
    logs.sort(key=lambda x: x.timestamp, reverse=True)
    
    return logs[:100]  # Return latest 100 logs

@app.post("/api/alerts", response_model=AlertSettings)
async def create_alert_settings(alert_data: AlertSettingsCreate):
    if alert_data.monitor_id not in monitors_db:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Check if alert settings already exist
    existing = next((alert for alert in alert_settings_db.values() 
                    if alert["monitor_id"] == alert_data.monitor_id), None)
    if existing:
        raise HTTPException(status_code=400, detail="Alert settings already exist for this monitor")
    
    alert_settings = AlertSettings(**alert_data.dict())
    alert_settings_db[alert_settings.id] = alert_settings.dict()
    return alert_settings

@app.get("/api/alerts/{monitor_id}", response_model=AlertSettings)
async def get_alert_settings(monitor_id: str):
    alert_settings = next((alert for alert in alert_settings_db.values() 
                          if alert["monitor_id"] == monitor_id), None)
    if not alert_settings:
        raise HTTPException(status_code=404, detail="Alert settings not found")
    
    return AlertSettings(**alert_settings)

@app.delete("/api/alerts/{monitor_id}")
async def delete_alert_settings(monitor_id: str):
    to_delete = None
    for alert_id, alert in alert_settings_db.items():
        if alert["monitor_id"] == monitor_id:
            to_delete = alert_id
            break
    
    if not to_delete:
        raise HTTPException(status_code=404, detail="Alert settings not found")
    
    del alert_settings_db[to_delete]
    return {"message": "Alert settings deleted successfully"}

# Initialize sample data when server starts
@app.on_event("startup")
async def startup_event():
    init_sample_data()
    print("🚀 StatusTrackr Mock Server started!")
    print("📍 Server URL: http://localhost:8000")
    print("📚 API Docs: http://localhost:8000/docs")
    print("📊 Sample monitors loaded")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)