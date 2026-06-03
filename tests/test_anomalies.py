# PROMPT: Generate pytest test suite for real-time retail anomalies checks
# CHANGES MADE: Mocked database connection and populated abnormal events sequence to trigger warnings

import pytest
import sqlite3
import json
from unittest.mock import patch

# Mock database module variables before imports
import app.database
import app.anomalies

# Reuse the same shared connection from test_metrics or a new local test connection
TEST_CONN = sqlite3.connect(":memory:")
TEST_CONN.row_factory = sqlite3.Row

# Initialize mock schema
cursor = TEST_CONN.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    store_id TEXT,
    camera_id TEXT,
    visitor_id TEXT,
    event_type TEXT,
    timestamp TEXT,
    zone_id TEXT,
    dwell_ms INTEGER,
    is_staff INTEGER,
    confidence REAL,
    queue_depth INTEGER,
    sku_zone TEXT,
    session_seq INTEGER,
    id_token TEXT,
    track_id INTEGER,
    gender TEXT,
    age INTEGER,
    age_bucket TEXT,
    group_id TEXT,
    group_size INTEGER,
    is_face_hidden INTEGER,
    zone_type TEXT,
    is_revenue_zone TEXT,
    queue_join_ts TEXT,
    queue_served_ts TEXT,
    queue_exit_ts TEXT,
    wait_seconds INTEGER,
    queue_position_at_join INTEGER,
    abandoned INTEGER
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS pos_transactions (
    store_id TEXT,
    transaction_id TEXT PRIMARY KEY,
    timestamp TEXT,
    basket_value_inr REAL
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS store_layouts (
    store_id TEXT PRIMARY KEY,
    layout_json TEXT
)
""")
TEST_CONN.commit()

class NonClosingConnection:
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)
    def commit(self, *args, **kwargs):
        return self._conn.commit(*args, **kwargs)
    def rollback(self, *args, **kwargs):
        return self._conn.rollback(*args, **kwargs)
    def close(self):
        pass

# Mock get_db_connection
def mock_get_db_connection():
    return NonClosingConnection(TEST_CONN)

@patch("app.database.get_db_connection", mock_get_db_connection)
@patch("app.anomalies.get_db_connection", mock_get_db_connection)
@patch("app.metrics.get_db_connection", mock_get_db_connection)
def test_anomalies_detection():
    # Clear tables
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM pos_transactions")
    cursor.execute("DELETE FROM store_layouts")
    TEST_CONN.commit()

    # 1. Setup layout (so we can check dead zones)
    layout = {
        "zones": {
            "SKINCARE": {"name": "Skincare Products"},
            "HAIRCARE": {"name": "Haircare Products"}
        }
    }
    cursor.execute("INSERT INTO store_layouts VALUES (?, ?)", ("STORE_TEST", json.dumps(layout)))

    # 2. Ingest abnormal events
    # Event timestamps spanning across current active day
    # We will trigger a BILLING_QUEUE_SPIKE (high queue depth values)
    cursor.executemany("""
    INSERT INTO events (
        event_id, store_id, camera_id, visitor_id, event_type, timestamp,
        zone_id, dwell_ms, is_staff, confidence, queue_depth, sku_zone, session_seq
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        # In-store activity in the last 5 minutes
        ("e1", "STORE_TEST", "CAM1", "VIS_001", "ENTRY", "2026-03-03T14:40:00Z", None, 0, 0, 0.9, None, None, 1),
        ("e2", "STORE_TEST", "CAM3", "VIS_001", "BILLING_QUEUE_JOIN", "2026-03-03T14:42:00Z", "BILLING_ZONE", 0, 0, 0.9, 5, None, 2), # Critical queue depth 5!
        
        ("e3", "STORE_TEST", "CAM1", "VIS_002", "ENTRY", "2026-03-03T14:41:00Z", None, 0, 0, 0.9, None, None, 1),
        ("e4", "STORE_TEST", "CAM3", "VIS_002", "BILLING_QUEUE_JOIN", "2026-03-03T14:43:00Z", "BILLING_ZONE", 0, 0, 0.9, 4, None, 2), # High queue depth 4!
        
        # Only Skincare zone visited. HAIRCARE zone is left completely unvisited (dead zone!)
        ("e5", "STORE_TEST", "CAM2", "VIS_001", "ZONE_ENTER", "2026-03-03T14:40:30Z", "SKINCARE", 0, 0, 0.9, None, None, 3)
    ])
    TEST_CONN.commit()

    # Call anomalies detection
    anomalies = app.anomalies.get_store_anomalies("STORE_TEST")
    
    # Assertions
    anomaly_types = [a["anomaly_type"] for a in anomalies]
    
    # Assert Queue Spike is detected
    assert "BILLING_QUEUE_SPIKE" in anomaly_types
    # Find the specific anomaly details
    spike = [a for a in anomalies if a["anomaly_type"] == "BILLING_QUEUE_SPIKE"][0]
    assert spike["severity"] == "CRITICAL"
    
    # Assert Dead Zone is detected for HAIRCARE
    assert "DEAD_ZONE" in anomaly_types
    dead_zones = [a for a in anomalies if a["anomaly_type"] == "DEAD_ZONE"]
    assert any("HAIRCARE" in d["description"] for d in dead_zones)
