from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timedelta
import asyncio
import aiohttp
import time
from enum import Enum
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import ssl
import socket
import dns.resolver
import subprocess
import json
import re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Enums
class MonitorStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    WARNING = "warning"  # For SSL expiry warnings, etc.

class MonitorType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    SSL = "ssl"
    DNS = "dns"
    PORT = "port"
    PING = "ping"
    KEYWORD = "keyword"
    API = "api"

class PortProtocol(str, Enum):
    TCP = "tcp"
    UDP = "udp"

class DNSRecordType(str, Enum):
    A = "A"
    AAAA = "AAAA"
    CNAME = "CNAME"
    MX = "MX"
    NS = "NS"
    TXT = "TXT"

# Models
class MonitorCreate(BaseModel):
    name: str
    url: Optional[HttpUrl] = None  # Optional for non-HTTP monitors
    check_interval: int = 300  # 5 minutes default
    monitor_type: MonitorType = MonitorType.HTTPS
    timeout: int = 10  # 10 seconds default
    
    # SSL monitoring fields
    ssl_domain: Optional[str] = None
    ssl_expiry_threshold: Optional[int] = 30  # Days before expiry to warn
    
    # DNS monitoring fields
    dns_hostname: Optional[str] = None
    dns_server: Optional[str] = "8.8.8.8"  # Default to Google DNS
    dns_record_type: Optional[DNSRecordType] = DNSRecordType.A
    expected_dns_result: Optional[str] = None
    
    # Port monitoring fields
    port_host: Optional[str] = None
    port_number: Optional[int] = None
    port_protocol: Optional[PortProtocol] = PortProtocol.TCP
    
    # Ping monitoring fields
    ping_host: Optional[str] = None
    ping_count: Optional[int] = 4
    ping_packet_size: Optional[int] = 32
    
    # Keyword monitoring fields
    keyword_url: Optional[HttpUrl] = None
    keyword_text: Optional[str] = None
    keyword_match_type: Optional[str] = "contains"  # contains, exact, regex
    
    # API endpoint monitoring fields
    api_url: Optional[HttpUrl] = None
    api_method: Optional[str] = "GET"
    api_headers: Optional[Dict[str, str]] = None
    api_body: Optional[str] = None
    expected_status_code: Optional[int] = 200
    expected_response_time: Optional[float] = None  # Max response time in seconds
    json_path: Optional[str] = None  # JSONPath for response validation
    expected_json_value: Optional[str] = None

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
    
    # Additional monitoring fields
    ssl_domain: Optional[str] = None
    ssl_expiry_threshold: Optional[int] = None
    ssl_expires_at: Optional[datetime] = None
    
    dns_hostname: Optional[str] = None
    dns_server: Optional[str] = None
    dns_record_type: Optional[DNSRecordType] = None
    expected_dns_result: Optional[str] = None
    
    port_host: Optional[str] = None
    port_number: Optional[int] = None
    port_protocol: Optional[PortProtocol] = None
    
    ping_host: Optional[str] = None
    ping_count: Optional[int] = None
    ping_packet_size: Optional[int] = None
    ping_packet_loss: Optional[float] = None
    
    keyword_url: Optional[str] = None
    keyword_text: Optional[str] = None
    keyword_match_type: Optional[str] = None
    keyword_found: Optional[bool] = None
    
    api_url: Optional[str] = None
    api_method: Optional[str] = None
    api_headers: Optional[Dict[str, str]] = None
    api_body: Optional[str] = None
    expected_status_code: Optional[int] = None
    expected_response_time: Optional[float] = None
    json_path: Optional[str] = None
    expected_json_value: Optional[str] = None
    actual_status_code: Optional[int] = None
    json_validation_result: Optional[bool] = None

class UptimeLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    monitor_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: MonitorStatus
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    
    # Additional monitoring data
    ssl_expires_at: Optional[datetime] = None
    ssl_days_until_expiry: Optional[int] = None
    dns_resolution_time: Optional[float] = None
    dns_result: Optional[str] = None
    port_open: Optional[bool] = None
    ping_packet_loss: Optional[float] = None
    ping_min_time: Optional[float] = None
    ping_max_time: Optional[float] = None
    ping_avg_time: Optional[float] = None
    keyword_found: Optional[bool] = None
    keyword_match_count: Optional[int] = None
    api_status_code: Optional[int] = None
    api_response_size: Optional[int] = None
    json_validation_passed: Optional[bool] = None
    additional_data: Optional[Dict[str, Any]] = None

class DashboardStats(BaseModel):
    total_monitors: int
    monitors_up: int
    monitors_down: int
    overall_uptime: float

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

# Global monitoring state
monitoring_active = False
monitoring_task = None

# Monitoring service functions
async def check_url(url: str, timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str]]:
    """Check if a URL is accessible and return status, response time, and error message"""
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(str(url)) as response:
                response_time = time.time() - start_time
                
                if response.status == 200:
                    return MonitorStatus.UP, response_time, None
                else:
                    return MonitorStatus.DOWN, response_time, f"HTTP {response.status}"
                    
    except asyncio.TimeoutError:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "Timeout"
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e)

async def check_ssl_certificate(domain: str, timeout: int = 10, expiry_threshold: int = 30) -> tuple[MonitorStatus, Optional[float], Optional[str], Optional[datetime], Optional[int]]:
    """Check SSL certificate expiry and return status, response time, error, expiry date, and days until expiry"""
    start_time = time.time()
    
    try:
        # Remove protocol if present
        domain = domain.replace('https://', '').replace('http://', '').split('/')[0].split(':')[0]
        
        context = ssl.create_default_context()
        
        with socket.create_connection((domain, 443), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                response_time = time.time() - start_time
                cert = ssock.getpeercert()
                
                # Parse the certificate expiry date
                expiry_date_str = cert['notAfter']
                expiry_date = datetime.strptime(expiry_date_str, '%b %d %H:%M:%S %Y %Z')
                
                # Calculate days until expiry
                days_until_expiry = (expiry_date - datetime.utcnow()).days
                
                if days_until_expiry < 0:
                    return MonitorStatus.DOWN, response_time, f"Certificate expired {abs(days_until_expiry)} days ago", expiry_date, days_until_expiry
                elif days_until_expiry <= expiry_threshold:
                    return MonitorStatus.WARNING, response_time, f"Certificate expires in {days_until_expiry} days", expiry_date, days_until_expiry
                else:
                    return MonitorStatus.UP, response_time, None, expiry_date, days_until_expiry
                    
    except socket.timeout:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "Connection timeout", None, None
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e), None, None

async def check_dns_resolution(hostname: str, dns_server: str = "8.8.8.8", record_type: str = "A", expected_result: Optional[str] = None, timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str], Optional[str]]:
    """Check DNS resolution and return status, response time, error, and resolved result"""
    start_time = time.time()
    
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [dns_server]
        resolver.timeout = timeout
        resolver.lifetime = timeout
        
        answers = resolver.resolve(hostname, record_type)
        response_time = time.time() - start_time
        
        # Get the resolved result
        resolved_results = [str(answer) for answer in answers]
        resolved_result = ', '.join(resolved_results)
        
        # Check if result matches expected (if provided)
        if expected_result:
            if expected_result in resolved_result:
                return MonitorStatus.UP, response_time, None, resolved_result
            else:
                return MonitorStatus.DOWN, response_time, f"Expected '{expected_result}' but got '{resolved_result}'", resolved_result
        else:
            return MonitorStatus.UP, response_time, None, resolved_result
            
    except dns.resolver.NXDOMAIN:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "Domain does not exist", None
    except dns.resolver.Timeout:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "DNS resolution timeout", None
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e), None

async def check_port_connectivity(host: str, port: int, protocol: str = "tcp", timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str], bool]:
    """Check port connectivity and return status, response time, error, and port open status"""
    start_time = time.time()
    
    try:
        if protocol.lower() == "tcp":
            # TCP port check
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=timeout
                )
                writer.close()
                await writer.wait_closed()
                response_time = time.time() - start_time
                return MonitorStatus.UP, response_time, None, True
            except Exception as e:
                response_time = time.time() - start_time
                return MonitorStatus.DOWN, response_time, str(e), False
        
        elif protocol.lower() == "udp":
            # UDP port check (basic connectivity test)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            try:
                sock.connect((host, port))
                response_time = time.time() - start_time
                return MonitorStatus.UP, response_time, None, True
            except Exception as e:
                response_time = time.time() - start_time
                return MonitorStatus.DOWN, response_time, str(e), False
            finally:
                sock.close()
        
        else:
            response_time = time.time() - start_time
            return MonitorStatus.DOWN, response_time, f"Unsupported protocol: {protocol}", False
            
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e), False

async def check_ping(host: str, count: int = 4, packet_size: int = 32, timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Check ping connectivity and return status, avg response time, error, packet loss, min, max, avg times"""
    try:
        # Use system ping command
        cmd = ["ping", "-c", str(count), "-s", str(packet_size), "-W", str(timeout*1000), host]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            output = stdout.decode()
            
            # Parse ping statistics
            lines = output.split('\n')
            
            # Find packet loss
            packet_loss = 0.0
            for line in lines:
                if 'packet loss' in line:
                    packet_loss_match = re.search(r'(\d+(?:\.\d+)?)%', line)
                    if packet_loss_match:
                        packet_loss = float(packet_loss_match.group(1))
                    break
            
            # Find round-trip times (min/avg/max)
            min_time = max_time = avg_time = None
            for line in lines:
                if 'min/avg/max' in line:
                    time_match = re.search(r'(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)', line)
                    if time_match:
                        min_time = float(time_match.group(1))
                        avg_time = float(time_match.group(2))
                        max_time = float(time_match.group(3))
                    break
            
            if packet_loss < 100:
                status = MonitorStatus.UP if packet_loss == 0 else MonitorStatus.WARNING
                return status, avg_time/1000 if avg_time else None, None, packet_loss, min_time/1000 if min_time else None, max_time/1000 if max_time else None, avg_time/1000 if avg_time else None
            else:
                return MonitorStatus.DOWN, None, "100% packet loss", packet_loss, None, None, None
        else:
            error_output = stderr.decode()
            return MonitorStatus.DOWN, None, f"Ping failed: {error_output}", None, None, None, None
            
    except Exception as e:
        return MonitorStatus.DOWN, None, str(e), None, None, None, None

async def check_keyword(url: str, keyword: str, match_type: str = "contains", timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str], bool, int]:
    """Check if keyword exists on webpage and return status, response time, error, found status, and match count"""
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(str(url)) as response:
                response_time = time.time() - start_time
                
                if response.status == 200:
                    content = await response.text()
                    
                    match_count = 0
                    found = False
                    
                    if match_type == "contains":
                        found = keyword in content
                        match_count = content.count(keyword)
                    elif match_type == "exact":
                        found = keyword == content.strip()
                        match_count = 1 if found else 0
                    elif match_type == "regex":
                        import re
                        matches = re.findall(keyword, content)
                        match_count = len(matches)
                        found = match_count > 0
                    
                    if found:
                        return MonitorStatus.UP, response_time, None, found, match_count
                    else:
                        return MonitorStatus.DOWN, response_time, f"Keyword '{keyword}' not found", found, match_count
                else:
                    response_time = time.time() - start_time
                    return MonitorStatus.DOWN, response_time, f"HTTP {response.status}", False, 0
                    
    except asyncio.TimeoutError:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "Timeout", False, 0
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e), False, 0

async def check_api_endpoint(url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None, body: Optional[str] = None, expected_status_code: int = 200, expected_response_time: Optional[float] = None, json_path: Optional[str] = None, expected_json_value: Optional[str] = None, timeout: int = 10) -> tuple[MonitorStatus, Optional[float], Optional[str], int, bool, Optional[int]]:
    """Check API endpoint and return status, response time, error, status code, json validation result, and response size"""
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            kwargs = {}
            if headers:
                kwargs['headers'] = headers
            if body and method.upper() in ['POST', 'PUT', 'PATCH']:
                kwargs['data'] = body
                
            async with session.request(method.upper(), str(url), **kwargs) as response:
                response_time = time.time() - start_time
                response_text = await response.text()
                response_size = len(response_text.encode('utf-8'))
                
                # Check status code
                if response.status != expected_status_code:
                    return MonitorStatus.DOWN, response_time, f"Expected status {expected_status_code}, got {response.status}", response.status, False, response_size
                
                # Check response time
                if expected_response_time and response_time > expected_response_time:
                    return MonitorStatus.WARNING, response_time, f"Response time {response_time:.2f}s exceeds limit {expected_response_time}s", response.status, False, response_size
                
                # Check JSON path validation
                json_validation_passed = True
                if json_path and expected_json_value:
                    try:
                        response_json = json.loads(response_text)
                        # Simple JSONPath implementation for basic paths like "data.status" or "status"
                        keys = json_path.split('.')
                        value = response_json
                        for key in keys:
                            value = value[key]
                        
                        if str(value) != expected_json_value:
                            json_validation_passed = False
                            return MonitorStatus.DOWN, response_time, f"JSON validation failed: expected '{expected_json_value}', got '{value}'", response.status, json_validation_passed, response_size
                            
                    except (json.JSONDecodeError, KeyError, TypeError) as e:
                        json_validation_passed = False
                        return MonitorStatus.DOWN, response_time, f"JSON validation error: {e}", response.status, json_validation_passed, response_size
                
                return MonitorStatus.UP, response_time, None, response.status, json_validation_passed, response_size
                    
    except asyncio.TimeoutError:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, "Timeout", 0, False, None
    except Exception as e:
        response_time = time.time() - start_time
        return MonitorStatus.DOWN, response_time, str(e), 0, False, None

async def send_alert_email(monitor_name: str, monitor_url: str, status: MonitorStatus, email_address: str):
    """Send email alert when monitor status changes using custom SMTP"""
    try:
        # Get email configuration from environment variables
        email_host = os.environ.get('EMAIL_HOST', 'mail.moracity.com')
        email_port = int(os.environ.get('EMAIL_PORT', 465))
        email_user = os.environ.get('EMAIL_USER', 'info@moracity.com')
        email_password = os.environ.get('EMAIL_PASSWORD', 'SecurePassword123')
        email_from = os.environ.get('EMAIL_FROM', 'info@moracity.com')
        email_from_name = os.environ.get('EMAIL_FROM_NAME', 'Moracity Car-Rental')
        
        # Create message
        message = MIMEMultipart("alternative")
        message["From"] = f"{email_from_name} <{email_from}>"
        message["To"] = email_address
        message["Reply-To"] = email_from
        
        if status == MonitorStatus.DOWN:
            message["Subject"] = f"🔴 ALERT: {monitor_name} is DOWN - Moracity Monitoring"
            
            # HTML version
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 8px 8px; }}
                    .alert-box {{ background: white; padding: 15px; border-left: 4px solid #dc3545; margin: 15px 0; }}
                    .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #666; }}
                    .status-down {{ color: #dc3545; font-weight: bold; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔴 Monitor Alert</h1>
                        <h2>{monitor_name} is DOWN</h2>
                    </div>
                    <div class="content">
                        <div class="alert-box">
                            <h3>Alert Details:</h3>
                            <p><strong>Monitor Name:</strong> {monitor_name}</p>
                            <p><strong>URL:</strong> <a href="{monitor_url}">{monitor_url}</a></p>
                            <p><strong>Status:</strong> <span class="status-down">DOWN</span></p>
                            <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                        </div>
                        <p><strong>Action Required:</strong></p>
                        <ul>
                            <li>Check your server status</li>
                            <li>Verify your website is accessible</li>
                            <li>Review server logs for errors</li>
                            <li>Contact your hosting provider if needed</li>
                        </ul>
                        <p>We'll continue monitoring and notify you when the service is restored.</p>
                    </div>
                    <div class="footer">
                        <p>This alert was sent by Moracity Uptime Monitoring Service</p>
                        <p>© 2024 Moracity Car-Rental. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Plain text version
            text_body = f"""
🔴 MONITOR ALERT: {monitor_name} is DOWN

Monitor Details:
- Name: {monitor_name}
- URL: {monitor_url}
- Status: DOWN
- Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

Your website is currently not responding. Please check your server.

Action Required:
- Check your server status
- Verify your website is accessible  
- Review server logs for errors
- Contact your hosting provider if needed

We'll continue monitoring and notify you when the service is restored.

---
This alert was sent by Moracity Uptime Monitoring Service
© 2024 Moracity Car-Rental. All rights reserved.
            """
            
        else:  # Status UP (Recovery)
            message["Subject"] = f"🟢 RECOVERY: {monitor_name} is back UP - Moracity Monitoring"
            
            # HTML version
            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: #28a745; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background: #f8f9fa; padding: 20px; border-radius: 0 0 8px 8px; }}
                    .success-box {{ background: white; padding: 15px; border-left: 4px solid #28a745; margin: 15px 0; }}
                    .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #666; }}
                    .status-up {{ color: #28a745; font-weight: bold; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🟢 Monitor Recovery</h1>
                        <h2>{monitor_name} is back UP</h2>
                    </div>
                    <div class="content">
                        <div class="success-box">
                            <h3>Recovery Details:</h3>
                            <p><strong>Monitor Name:</strong> {monitor_name}</p>
                            <p><strong>URL:</strong> <a href="{monitor_url}">{monitor_url}</a></p>
                            <p><strong>Status:</strong> <span class="status-up">UP</span></p>
                            <p><strong>Recovery Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                        </div>
                        <p><strong>Good News!</strong> Your website is now responding normally.</p>
                        <p>We'll continue monitoring your service 24/7 to ensure optimal uptime.</p>
                    </div>
                    <div class="footer">
                        <p>This recovery notification was sent by Moracity Uptime Monitoring Service</p>
                        <p>© 2024 Moracity Car-Rental. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Plain text version
            text_body = f"""
🟢 MONITOR RECOVERY: {monitor_name} is back UP

Recovery Details:
- Name: {monitor_name}
- URL: {monitor_url}
- Status: UP
- Recovery Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

Good News! Your website is now responding normally.

We'll continue monitoring your service 24/7 to ensure optimal uptime.

---
This recovery notification was sent by Moracity Uptime Monitoring Service
© 2024 Moracity Car-Rental. All rights reserved.
            """
        
        # Attach both versions
        part1 = MIMEText(text_body, "plain")
        part2 = MIMEText(html_body, "html")
        message.attach(part1)
        message.attach(part2)
        
        # Send email using your SMTP server
        with smtplib.SMTP_SSL(email_host, email_port) as server:
            server.login(email_user, email_password)
            server.send_message(message)
            
        logger.info(f"✅ EMAIL SENT: {message['Subject']} to {email_address}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send email alert: {e}")
        return False

# Enhanced monitoring service with alerts
async def monitor_check_cycle():
    """Background task that checks all monitors periodically"""
    while monitoring_active:
        try:
            # Get all monitors
            monitors = await db.monitors.find().to_list(1000)
            
            for monitor_doc in monitors:
                monitor = Monitor(**monitor_doc)
                
                # Check if it's time to check this monitor
                if (monitor.last_checked is None or 
                    datetime.utcnow() - monitor.last_checked >= timedelta(seconds=monitor.check_interval)):
                    
                    # Store previous status for alert comparison
                    previous_status = monitor.status
                    
                    # Perform the check based on monitor type
                    status = MonitorStatus.DOWN
                    response_time = None
                    error_msg = None
                    log_data = {}
                    update_data = {"last_checked": datetime.utcnow()}
                    
                    try:
                        if monitor.monitor_type in [MonitorType.HTTP, MonitorType.HTTPS]:
                            status, response_time, error_msg = await check_url(monitor.url, monitor.timeout)
                            
                        elif monitor.monitor_type == MonitorType.SSL:
                            status, response_time, error_msg, expiry_date, days_until_expiry = await check_ssl_certificate(
                                monitor.ssl_domain, monitor.timeout, monitor.ssl_expiry_threshold or 30
                            )
                            if expiry_date:
                                update_data["ssl_expires_at"] = expiry_date
                                log_data["ssl_expires_at"] = expiry_date
                                log_data["ssl_days_until_expiry"] = days_until_expiry
                                
                        elif monitor.monitor_type == MonitorType.DNS:
                            status, response_time, error_msg, dns_result = await check_dns_resolution(
                                monitor.dns_hostname, monitor.dns_server or "8.8.8.8", 
                                monitor.dns_record_type or "A", monitor.expected_dns_result, monitor.timeout
                            )
                            log_data["dns_resolution_time"] = response_time
                            log_data["dns_result"] = dns_result
                            
                        elif monitor.monitor_type == MonitorType.PORT:
                            status, response_time, error_msg, port_open = await check_port_connectivity(
                                monitor.port_host, monitor.port_number, monitor.port_protocol or "tcp", monitor.timeout
                            )
                            log_data["port_open"] = port_open
                            
                        elif monitor.monitor_type == MonitorType.PING:
                            status, avg_time, error_msg, packet_loss, min_time, max_time, avg_time_detailed = await check_ping(
                                monitor.ping_host, monitor.ping_count or 4, monitor.ping_packet_size or 32, monitor.timeout
                            )
                            response_time = avg_time
                            if packet_loss is not None:
                                update_data["ping_packet_loss"] = packet_loss
                                log_data["ping_packet_loss"] = packet_loss
                                log_data["ping_min_time"] = min_time
                                log_data["ping_max_time"] = max_time
                                log_data["ping_avg_time"] = avg_time_detailed
                                
                        elif monitor.monitor_type == MonitorType.KEYWORD:
                            status, response_time, error_msg, keyword_found, match_count = await check_keyword(
                                monitor.keyword_url, monitor.keyword_text, monitor.keyword_match_type or "contains", monitor.timeout
                            )
                            update_data["keyword_found"] = keyword_found
                            log_data["keyword_found"] = keyword_found
                            log_data["keyword_match_count"] = match_count
                            
                        elif monitor.monitor_type == MonitorType.API:
                            status, response_time, error_msg, status_code, json_valid, response_size = await check_api_endpoint(
                                monitor.api_url, monitor.api_method or "GET", monitor.api_headers, monitor.api_body,
                                monitor.expected_status_code or 200, monitor.expected_response_time, 
                                monitor.json_path, monitor.expected_json_value, monitor.timeout
                            )
                            update_data["actual_status_code"] = status_code
                            update_data["json_validation_result"] = json_valid
                            log_data["api_status_code"] = status_code
                            log_data["api_response_size"] = response_size
                            log_data["json_validation_passed"] = json_valid
                            
                    except Exception as e:
                        logger.error(f"Error checking monitor {monitor.name}: {e}")
                        status = MonitorStatus.DOWN
                        error_msg = str(e)
                    
                    # Update monitor with common fields
                    update_data.update({
                        "status": status,
                        "response_time": response_time
                    })
                    
                    await db.monitors.update_one(
                        {"id": monitor.id}, 
                        {"$set": update_data}
                    )
                    
                    # Log the check with additional data
                    log_dict = {
                        "monitor_id": monitor.id,
                        "status": status,
                        "response_time": response_time,
                        "error_message": error_msg
                    }
                    log_dict.update(log_data)
                    
                    uptime_log = UptimeLog(**log_dict)
                    await db.uptime_logs.insert_one(uptime_log.dict())
                    
                    # Update uptime percentage
                    await update_uptime_percentage(monitor.id)
                    
                    # Check for status changes and send alerts
                    if previous_status != status and previous_status != MonitorStatus.UNKNOWN:
                        # Get alert settings for this monitor
                        alert_settings = await db.alert_settings.find({"monitor_id": monitor.id}).to_list(100)
                        
                        for alert_setting in alert_settings:
                            alert = AlertSettings(**alert_setting)
                            should_alert = (
                                (status == MonitorStatus.DOWN and alert.alert_on_down) or
                                (status == MonitorStatus.UP and alert.alert_on_up) or
                                (status == MonitorStatus.WARNING and alert.alert_on_down)  # Treat warnings as alerts
                            )
                            
                            if should_alert and alert.email_enabled:
                                # Use appropriate URL for email based on monitor type
                                monitor_url = monitor.url or monitor.ssl_domain or monitor.dns_hostname or monitor.port_host or monitor.ping_host or monitor.keyword_url or monitor.api_url or "N/A"
                                await send_alert_email(
                                    monitor.name, 
                                    str(monitor_url), 
                                    status, 
                                    alert.email_address
                                )
                    
                    logger.info(f"Checked monitor {monitor.name} ({monitor.monitor_type}) - Status: {status}, Response Time: {response_time}")
            
            # Wait before next cycle
            await asyncio.sleep(30)  # Check every 30 seconds
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}")
            await asyncio.sleep(30)

async def update_uptime_percentage(monitor_id: str):
    """Calculate and update uptime percentage for a monitor"""
    try:
        # Get logs from last 24 hours
        twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
        logs = await db.uptime_logs.find({
            "monitor_id": monitor_id,
            "timestamp": {"$gte": twenty_four_hours_ago}
        }).to_list(1000)
        
        if not logs:
            return
            
        up_count = sum(1 for log in logs if log["status"] == MonitorStatus.UP)
        total_count = len(logs)
        uptime_percentage = (up_count / total_count) * 100 if total_count > 0 else 0
        
        await db.monitors.update_one(
            {"id": monitor_id},
            {"$set": {"uptime_percentage": uptime_percentage}}
        )
        
    except Exception as e:
        logger.error(f"Error updating uptime percentage: {e}")

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Uptime Monitoring API"}

@api_router.post("/monitors", response_model=Monitor)
async def create_monitor(monitor_data: MonitorCreate):
    """Create a new monitor"""
    # Convert to dict and handle optional HttpUrl fields
    monitor_dict = monitor_data.dict()
    
    # Convert HttpUrl fields to strings if they exist
    if monitor_dict.get('url'):
        monitor_dict['url'] = str(monitor_dict['url'])
    if monitor_dict.get('keyword_url'):
        monitor_dict['keyword_url'] = str(monitor_dict['keyword_url'])
    if monitor_dict.get('api_url'):
        monitor_dict['api_url'] = str(monitor_dict['api_url'])
    
    # Validate required fields based on monitor type
    monitor_type = monitor_dict.get('monitor_type')
    
    if monitor_type in [MonitorType.HTTP, MonitorType.HTTPS]:
        if not monitor_dict.get('url'):
            raise HTTPException(status_code=400, detail="URL is required for HTTP/HTTPS monitors")
    elif monitor_type == MonitorType.SSL:
        if not monitor_dict.get('ssl_domain'):
            raise HTTPException(status_code=400, detail="SSL domain is required for SSL monitors")
    elif monitor_type == MonitorType.DNS:
        if not monitor_dict.get('dns_hostname'):
            raise HTTPException(status_code=400, detail="DNS hostname is required for DNS monitors")
    elif monitor_type == MonitorType.PORT:
        if not monitor_dict.get('port_host') or not monitor_dict.get('port_number'):
            raise HTTPException(status_code=400, detail="Port host and number are required for port monitors")
    elif monitor_type == MonitorType.PING:
        if not monitor_dict.get('ping_host'):
            raise HTTPException(status_code=400, detail="Ping host is required for ping monitors")
    elif monitor_type == MonitorType.KEYWORD:
        if not monitor_dict.get('keyword_url') or not monitor_dict.get('keyword_text'):
            raise HTTPException(status_code=400, detail="Keyword URL and text are required for keyword monitors")
    elif monitor_type == MonitorType.API:
        if not monitor_dict.get('api_url'):
            raise HTTPException(status_code=400, detail="API URL is required for API monitors")
    
    monitor = Monitor(**monitor_dict)
    
    # Insert into database
    await db.monitors.insert_one(monitor.dict())
    
    # Start monitoring service if not already running
    await start_monitoring_service()
    
    return monitor

@api_router.get("/monitors", response_model=List[Monitor])
async def get_monitors():
    """Get all monitors"""
    monitors = await db.monitors.find().to_list(1000)
    return [Monitor(**monitor) for monitor in monitors]

@api_router.get("/monitors/{monitor_id}", response_model=Monitor)
async def get_monitor(monitor_id: str):
    """Get a specific monitor"""
    monitor = await db.monitors.find_one({"id": monitor_id})
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return Monitor(**monitor)

@api_router.delete("/monitors/{monitor_id}")
async def delete_monitor(monitor_id: str):
    """Delete a monitor"""
    result = await db.monitors.delete_one({"id": monitor_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Also delete associated logs
    await db.uptime_logs.delete_many({"monitor_id": monitor_id})
    
    return {"message": "Monitor deleted successfully"}

@api_router.post("/monitors/{monitor_id}/check")
async def manual_check_monitor(monitor_id: str):
    """Manually trigger a check for a specific monitor"""
    monitor = await db.monitors.find_one({"id": monitor_id})
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    monitor_obj = Monitor(**monitor)
    
    # Perform the check based on monitor type
    status = MonitorStatus.DOWN
    response_time = None
    error_msg = None
    log_data = {}
    update_data = {"last_checked": datetime.utcnow()}
    
    try:
        if monitor_obj.monitor_type in [MonitorType.HTTP, MonitorType.HTTPS]:
            status, response_time, error_msg = await check_url(monitor_obj.url, monitor_obj.timeout)
            
        elif monitor_obj.monitor_type == MonitorType.SSL:
            status, response_time, error_msg, expiry_date, days_until_expiry = await check_ssl_certificate(
                monitor_obj.ssl_domain, monitor_obj.timeout, monitor_obj.ssl_expiry_threshold or 30
            )
            if expiry_date:
                update_data["ssl_expires_at"] = expiry_date
                log_data["ssl_expires_at"] = expiry_date
                log_data["ssl_days_until_expiry"] = days_until_expiry
                
        elif monitor_obj.monitor_type == MonitorType.DNS:
            status, response_time, error_msg, dns_result = await check_dns_resolution(
                monitor_obj.dns_hostname, monitor_obj.dns_server or "8.8.8.8", 
                monitor_obj.dns_record_type or "A", monitor_obj.expected_dns_result, monitor_obj.timeout
            )
            log_data["dns_resolution_time"] = response_time
            log_data["dns_result"] = dns_result
            
        elif monitor_obj.monitor_type == MonitorType.PORT:
            status, response_time, error_msg, port_open = await check_port_connectivity(
                monitor_obj.port_host, monitor_obj.port_number, monitor_obj.port_protocol or "tcp", monitor_obj.timeout
            )
            log_data["port_open"] = port_open
            
        elif monitor_obj.monitor_type == MonitorType.PING:
            status, avg_time, error_msg, packet_loss, min_time, max_time, avg_time_detailed = await check_ping(
                monitor_obj.ping_host, monitor_obj.ping_count or 4, monitor_obj.ping_packet_size or 32, monitor_obj.timeout
            )
            response_time = avg_time
            if packet_loss is not None:
                update_data["ping_packet_loss"] = packet_loss
                log_data["ping_packet_loss"] = packet_loss
                log_data["ping_min_time"] = min_time
                log_data["ping_max_time"] = max_time
                log_data["ping_avg_time"] = avg_time_detailed
                
        elif monitor_obj.monitor_type == MonitorType.KEYWORD:
            status, response_time, error_msg, keyword_found, match_count = await check_keyword(
                monitor_obj.keyword_url, monitor_obj.keyword_text, monitor_obj.keyword_match_type or "contains", monitor_obj.timeout
            )
            update_data["keyword_found"] = keyword_found
            log_data["keyword_found"] = keyword_found
            log_data["keyword_match_count"] = match_count
            
        elif monitor_obj.monitor_type == MonitorType.API:
            status, response_time, error_msg, status_code, json_valid, response_size = await check_api_endpoint(
                monitor_obj.api_url, monitor_obj.api_method or "GET", monitor_obj.api_headers, monitor_obj.api_body,
                monitor_obj.expected_status_code or 200, monitor_obj.expected_response_time, 
                monitor_obj.json_path, monitor_obj.expected_json_value, monitor_obj.timeout
            )
            update_data["actual_status_code"] = status_code
            update_data["json_validation_result"] = json_valid
            log_data["api_status_code"] = status_code
            log_data["api_response_size"] = response_size
            log_data["json_validation_passed"] = json_valid
            
    except Exception as e:
        logger.error(f"Error manually checking monitor {monitor_obj.name}: {e}")
        status = MonitorStatus.DOWN
        error_msg = str(e)
    
    # Update monitor with common fields
    update_data.update({
        "status": status,
        "response_time": response_time
    })
    
    await db.monitors.update_one(
        {"id": monitor_id}, 
        {"$set": update_data}
    )
    
    # Log the check with additional data
    log_dict = {
        "monitor_id": monitor_id,
        "status": status,
        "response_time": response_time,
        "error_message": error_msg
    }
    log_dict.update(log_data)
    
    uptime_log = UptimeLog(**log_dict)
    await db.uptime_logs.insert_one(uptime_log.dict())
    
    return {
        "status": status, 
        "response_time": response_time, 
        "error": error_msg,
        "additional_data": log_data
    }



@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats():
    """Get dashboard statistics"""
    monitors = await db.monitors.find().to_list(1000)
    
    total_monitors = len(monitors)
    monitors_up = sum(1 for m in monitors if m.get("status") == MonitorStatus.UP)
    monitors_down = sum(1 for m in monitors if m.get("status") == MonitorStatus.DOWN)
    
    # Calculate overall uptime
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

@api_router.post("/alerts", response_model=AlertSettings)
async def create_alert_settings(alert_data: AlertSettingsCreate):
    """Create alert settings for a monitor"""
    # Check if monitor exists
    monitor = await db.monitors.find_one({"id": alert_data.monitor_id})
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    
    # Check if alert settings already exist for this monitor
    existing = await db.alert_settings.find_one({"monitor_id": alert_data.monitor_id})
    if existing:
        raise HTTPException(status_code=400, detail="Alert settings already exist for this monitor")
    
    alert_settings = AlertSettings(**alert_data.dict())
    await db.alert_settings.insert_one(alert_settings.dict())
    
    return alert_settings

@api_router.get("/alerts/{monitor_id}", response_model=AlertSettings)
async def get_alert_settings(monitor_id: str):
    """Get alert settings for a monitor"""
    alert_settings = await db.alert_settings.find_one({"monitor_id": monitor_id})
    if not alert_settings:
        raise HTTPException(status_code=404, detail="Alert settings not found")
    
    return AlertSettings(**alert_settings)

@api_router.delete("/alerts/{monitor_id}")
async def delete_alert_settings(monitor_id: str):
    """Delete alert settings for a monitor"""
    result = await db.alert_settings.delete_one({"monitor_id": monitor_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alert settings not found")
    
    return {"message": "Alert settings deleted successfully"}

@api_router.get("/monitors/{monitor_id}/history")
async def get_monitor_history(monitor_id: str, hours: int = 24):
    """Get historical uptime data for charts"""
    try:
        time_ago = datetime.utcnow() - timedelta(hours=hours)
        logs = await db.uptime_logs.find({
            "monitor_id": monitor_id,
            "timestamp": {"$gte": time_ago}
        }).sort("timestamp", 1).to_list(1000)
        
        # Group data by hour for better visualization
        hourly_data = {}
        for log in logs:
            hour_key = log["timestamp"].replace(minute=0, second=0, microsecond=0)
            if hour_key not in hourly_data:
                hourly_data[hour_key] = {
                    "timestamp": hour_key,
                    "up_count": 0,
                    "down_count": 0,
                    "total_response_time": 0,
                    "response_count": 0
                }
            
            if log["status"] == MonitorStatus.UP:
                hourly_data[hour_key]["up_count"] += 1
                if log.get("response_time"):
                    hourly_data[hour_key]["total_response_time"] += log["response_time"]
                    hourly_data[hour_key]["response_count"] += 1
            else:
                hourly_data[hour_key]["down_count"] += 1
        
        # Calculate averages and percentages
        history = []
        for hour_key in sorted(hourly_data.keys()):
            data = hourly_data[hour_key]
            total_checks = data["up_count"] + data["down_count"]
            uptime_percentage = (data["up_count"] / total_checks) * 100 if total_checks > 0 else 0
            avg_response_time = (data["total_response_time"] / data["response_count"]) if data["response_count"] > 0 else 0
            
            history.append({
                "timestamp": hour_key,
                "uptime_percentage": uptime_percentage,
                "avg_response_time": avg_response_time * 1000,  # Convert to ms
                "total_checks": total_checks
            })
        
        return history
    except Exception as e:
        logger.error(f"Error getting monitor history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get monitor history")

@api_router.get("/monitors/{monitor_id}/logs")
async def get_monitor_logs(monitor_id: str, hours: int = 24):
    """Get uptime logs for a specific monitor"""
    time_ago = datetime.utcnow() - timedelta(hours=hours)
    logs = await db.uptime_logs.find({
        "monitor_id": monitor_id,
        "timestamp": {"$gte": time_ago}
    }).sort("timestamp", -1).to_list(1000)
    
    return [UptimeLog(**log) for log in logs]

async def start_monitoring_service():
    """Start the background monitoring service"""
    global monitoring_active, monitoring_task
    
    if not monitoring_active:
        monitoring_active = True
        monitoring_task = asyncio.create_task(monitor_check_cycle())
        logger.info("Monitoring service started")

async def stop_monitoring_service():
    """Stop the background monitoring service"""
    global monitoring_active, monitoring_task
    
    monitoring_active = False
    if monitoring_task:
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
        monitoring_task = None
        logger.info("Monitoring service stopped")

# Root endpoint for the main app
@app.get("/")
async def main_root():
    return {
        "message": "StatusTrackr Backend API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "api_root": "/api/",
            "api_docs": "/docs",
            "monitors": "/api/monitors",
            "dashboard": "/api/dashboard/stats"
        }
    }

# Include the router in the main app
app.include_router(api_router)

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

@app.on_event("startup")
async def startup_event():
    """Start monitoring service on app startup"""
    await start_monitoring_service()

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on app shutdown"""
    await stop_monitoring_service()
    client.close()