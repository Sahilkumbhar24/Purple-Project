# PROMPT: Generate pytest test suite for store metrics and POS correlation calculations
# CHANGES MADE: Mocked database paths to in-memory SQLite and populated mock POS transactions

import pytest
import sqlite3
import json
from unittest.mock import patch

# Mock database module variables before imports
import app.database
import app.metrics

# We will create an in-memory database shared for tests
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
    # Return a new connection or return the existing one.
    # Note: :memory: connection is closed if we close it, so we mock it to remain open
    return NonClosingConnection(TEST_CONN)

@patch("app.database.get_db_connection", mock_get_db_connection)
@patch("app.metrics.get_db_connection", mock_get_db_connection)
def test_metrics_calculation_and_pos_correlation():
    # Clear tables
    cursor.execute("DELETE FROM events")
    cursor.execute("DELETE FROM pos_transactions")
    TEST_CONN.commit()

    # 1. Ingest events for visitor 1 (Purchases/Converts)
    cursor.executemany("""
    INSERT INTO events (
        event_id, store_id, camera_id, visitor_id, event_type, timestamp,
        zone_id, dwell_ms, is_staff, confidence, queue_depth, sku_zone, session_seq
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        # Visitor 1: enters, goes to skincare, joins queue, exits
        ("e1", "STORE_TEST", "CAM1", "VIS_001", "ENTRY", "2026-03-03T14:00:00Z", None, 0, 0, 0.9, None, None, 1),
        ("e2", "STORE_TEST", "CAM2", "VIS_001", "ZONE_ENTER", "2026-03-03T14:01:00Z", "SKINCARE", 0, 0, 0.9, None, "MOISTURISER", 2),
        ("e3", "STORE_TEST", "CAM2", "VIS_001", "ZONE_EXIT", "2026-03-03T14:02:00Z", "SKINCARE", 60000, 0, 0.9, None, "MOISTURISER", 3),
        ("e4", "STORE_TEST", "CAM3", "VIS_001", "BILLING_QUEUE_JOIN", "2026-03-03T14:03:00Z", "BILLING_ZONE", 0, 0, 0.9, 2, None, 4),
        ("e5", "STORE_TEST", "CAM3", "VIS_001", "ZONE_EXIT", "2026-03-03T14:04:00Z", "BILLING_ZONE", 60000, 0, 0.9, None, None, 5),
        ("e6", "STORE_TEST", "CAM1", "VIS_001", "EXIT", "2026-03-03T14:05:00Z", None, 0, 0, 0.9, None, None, 6),
        
        # Visitor 2: Staff member (Should be excluded from metrics!)
        ("e7", "STORE_TEST", "CAM1", "VIS_STAFF", "ENTRY", "2026-03-03T14:00:10Z", None, 0, 1, 0.9, None, None, 1),
        ("e8", "STORE_TEST", "CAM1", "VIS_STAFF", "EXIT", "2026-03-03T14:04:10Z", None, 0, 1, 0.9, None, None, 2),
        
        # Visitor 3: enters, goes to skincare, joins queue, leaves without purchase (Abandons)
        ("e9", "STORE_TEST", "CAM1", "VIS_002", "ENTRY", "2026-03-03T14:10:00Z", None, 0, 0, 0.9, None, None, 1),
        ("e10", "STORE_TEST", "CAM3", "VIS_002", "BILLING_QUEUE_JOIN", "2026-03-03T14:12:00Z", "BILLING_ZONE", 0, 0, 0.9, 1, None, 2),
        ("e11", "STORE_TEST", "CAM3", "VIS_002", "BILLING_QUEUE_ABANDON", "2026-03-03T14:15:00Z", "BILLING_ZONE", 180000, 0, 0.9, None, None, 3)
    ])
    
    # Ingest POS transaction for Visitor 1
    # Visitor 1 joined queue at 14:03:00. Transaction happens at 14:04:30 (within 5 minutes window!)
    cursor.execute("""
    INSERT INTO pos_transactions VALUES (?, ?, ?, ?)
    """, ("STORE_TEST", "TXN_TEST_01", "2026-03-03T14:04:30Z", 1500.00))
    TEST_CONN.commit()

    # Call metrics computation
    metrics = app.metrics.get_store_metrics("STORE_TEST")
    
    # Assertions
    assert metrics["unique_visitors"] == 2 # 2 customers, 1 staff excluded
    assert metrics["conversion_rate"] == 0.5 # 1 of 2 converted
    assert metrics["abandonment_rate"] == 0.5 # 1 of 2 joined queue and abandoned (VIS_002)
    assert metrics["queue_depth"] == 1.5 # Average of (2, 1)
    assert "SKINCARE" in metrics["avg_dwell_per_zone"]
    assert metrics["avg_dwell_per_zone"]["SKINCARE"] == 60000.0
