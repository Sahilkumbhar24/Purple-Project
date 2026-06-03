# PROMPT: Implement FastAPI router with JSON structured logging middleware, heatmap analytics, and static dashboard hosting
# CHANGES MADE: Added trace_id logging middleware, mounted static folder, and implemented normalized heatmap algorithm

import os
import time
import uuid
import json
import logging
from typing import List
from fastapi import FastAPI, Request, Response, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db, get_db_connection, normalize_store_id
from app.models import EventModel
from app.ingestion import ingest_events_batch
from app.metrics import get_store_metrics, get_active_date_str
from app.funnel import get_store_funnel
from app.anomalies import get_store_anomalies
from app.health import get_health_status, register_ingest

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

app = FastAPI(
    title="Apex Retail Store Intelligence API",
    description="Real-time in-store behavior analytics pipeline",
    version="1.0.0"
)

# Enable CORS for local testing and Web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization on startup
@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("Application startup: Database initialized successfully.")

# Custom Middleware for Structured JSON Logging
@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
    start_time = time.time()
    
    # Read body for event count in ingestion
    event_count = 0
    if request.url.path == "/events/ingest" and request.method == "POST":
        try:
            # We clone the request body stream so the route handler can still read it
            body = await request.body()
            payload = json.loads(body)
            if isinstance(payload, list):
                event_count = len(payload)
            elif isinstance(payload, dict):
                event_count = 1
        except Exception:
            pass

    response = Response("Internal Server Error", status_code=500)
    try:
        response = await call_next(request)
    finally:
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Determine store_id from path if available
        store_id = "N/A"
        path_parts = request.url.path.split("/")
        if "stores" in path_parts and len(path_parts) > path_parts.index("stores") + 1:
            store_id = normalize_store_id(path_parts[path_parts.index("stores") + 1])

        # Structure the log record
        log_record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trace_id": trace_id,
            "store_id": store_id,
            "endpoint": request.url.path,
            "method": request.method,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "event_count": event_count
        }
        print(json.dumps(log_record)) # Print as a single structured JSON line
        
    return response

# GET /health
@app.get("/health")
def healthcheck():
    try:
        health_data = get_health_status()
        return health_data
    except Exception as e:
        logger.error(f"Healthcheck failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": f"Database unavailable: {str(e)}"}
        )

# POST /events/ingest
@app.post("/events/ingest")
async def ingest_events(events: List[dict]):
    if len(events) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch size exceeds maximum limit of 500 events"
        )
    
    try:
        result = ingest_events_batch(events)
        if result["ingested"] > 0:
            register_ingest() # Update wall-clock active stream feed tracker
        return result
    except Exception as e:
        logger.error(f"Ingestion batch error: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "error": f"Database unavailable: {str(e)}"}
        )

# GET /stores/{id}/metrics
@app.get("/stores/{id}/metrics")
def get_metrics(id: str):
    try:
        metrics = get_store_metrics(id)
        return metrics
    except Exception as e:
        logger.error(f"Failed to fetch store metrics: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Database unavailable: {str(e)}"}
        )

# GET /stores/{id}/funnel
@app.get("/stores/{id}/funnel")
def get_funnel(id: str):
    try:
        funnel = get_store_funnel(id)
        return funnel
    except Exception as e:
        logger.error(f"Failed to fetch store funnel: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Database unavailable: {str(e)}"}
        )

# GET /stores/{id}/heatmap
@app.get("/stores/{id}/heatmap")
def get_heatmap(id: str):
    try:
        conn = get_db_connection()
        n_id = normalize_store_id(id)
        active_date = get_active_date_str(conn, n_id)
        if not active_date:
            conn.close()
            return []
            
        date_start = f"{active_date}T00:00:00"
        date_end = f"{active_date}T23:59:59"
        
        cursor = conn.cursor()
        
        # Count total sessions for data confidence flag
        cursor.execute("""
            SELECT COUNT(DISTINCT visitor_id) FROM events
            WHERE store_id = ? AND is_staff = 0 AND timestamp BETWEEN ? AND ?
        """, (n_id, date_start, date_end))
        total_sessions = cursor.fetchone()[0] or 0
        data_confidence = total_sessions >= 20

        # Fetch visit frequency and avg dwell per zone
        cursor.execute("""
            SELECT zone_id, 
                   COUNT(CASE WHEN event_type IN ('ZONE_ENTER', 'ZONE_DWELL', 'ZONE_EXIT') THEN 1 END) as visit_count,
                   AVG(dwell_ms) as avg_dwell
            FROM events
            WHERE store_id = ? AND is_staff = 0 AND zone_id IS NOT NULL AND timestamp BETWEEN ? AND ?
            GROUP BY zone_id
        """, (n_id, date_start, date_end))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        # Find max visits for normalization
        max_visits = max([row["visit_count"] for row in rows]) if rows else 1

        heatmap = []
        for row in rows:
            # Simple normalization formula: (visits / max_visits) * 100
            norm_score = round((row["visit_count"] / max_visits) * 100, 1) if max_visits > 0 else 0.0
            heatmap.append({
                "zone_id": row["zone_id"],
                "visit_count": row["visit_count"],
                "avg_dwell_ms": round(row["avg_dwell"] or 0, 1),
                "normalized_score": norm_score,
                "data_confidence": data_confidence
            })

        return heatmap
    except Exception as e:
        logger.error(f"Failed to fetch store heatmap: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Database unavailable: {str(e)}"}
        )

# GET /stores/{id}/anomalies
@app.get("/stores/{id}/anomalies")
def get_anomalies(id: str):
    try:
        anomalies = get_store_anomalies(id)
        return anomalies
    except Exception as e:
        logger.error(f"Failed to fetch store anomalies: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Database unavailable: {str(e)}"}
        )

# GET /stores/{id}/events
@app.get("/stores/{id}/events")
def get_recent_events(id: str, limit: int = 8):
    try:
        conn = get_db_connection()
        n_id = normalize_store_id(id)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM events
            WHERE store_id = ? AND is_staff = 0
            ORDER BY timestamp DESC
            LIMIT ?
        """, (n_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for r in rows:
            events.append({
                "event_id": r["event_id"],
                "store_id": r["store_id"],
                "camera_id": r["camera_id"],
                "visitor_id": r["visitor_id"],
                "event_type": r["event_type"],
                "timestamp": r["timestamp"],
                "zone_id": r["zone_id"],
                "dwell_ms": r["dwell_ms"],
                "is_staff": bool(r["is_staff"]),
                "confidence": r["confidence"],
                "metadata": {
                    "queue_depth": r["queue_depth"],
                    "sku_zone": r["sku_zone"],
                    "session_seq": r["session_seq"]
                }
            })
        return events
    except Exception as e:
        logger.error(f"Failed to fetch recent events: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": f"Database unavailable: {str(e)}"}
        )

# Static Dashboard Hosting
# Mount the static directory to serve HTML dashboard files on /dashboard or /
# Note: Mount at / is fine but we put it after API endpoints so they take priority
try:
    app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), html=True), name="static")
except Exception as e:
    logger.warning(f"Could not mount static dashboard files: {e}. Dashboard won't be hosted.")
