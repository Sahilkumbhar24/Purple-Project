import sqlite3
import os
import json
import csv
import logging

logger = logging.getLogger("Database")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../store_intelligence.db")
STORE_LAYOUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../store_layout.json")
POS_TRANSACTIONS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../pos_transactions.csv")

def normalize_store_id(store_id: str) -> str:
    if not store_id:
        return store_id
    s = store_id.strip()
    if s.lower().startswith("store_"):
        parts = s.split("_")
        if len(parts) == 2 and parts[1].isdigit():
            return f"ST{parts[1]}"
    return s

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    logger.info(f"Initializing SQLite database at: {DB_PATH}")
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create events table with upgraded fields
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
    
    # Create indexes for fast analytical queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_store_visitor ON events (store_id, visitor_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type)")

    # 2. Create pos_transactions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pos_transactions (
        store_id TEXT,
        transaction_id TEXT PRIMARY KEY,
        timestamp TEXT,
        basket_value_inr REAL
    )
    """)
    
    # 3. Create store_layouts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS store_layouts (
        store_id TEXT PRIMARY KEY,
        layout_json TEXT
    )
    """)
    
    conn.commit()
    
    # Load store_layout.json into database if layout table is empty
    cursor.execute("SELECT COUNT(*) FROM store_layouts")
    if cursor.fetchone()[0] == 0 and os.path.exists(STORE_LAYOUT_PATH):
        logger.info(f"Loading store layout configuration from {STORE_LAYOUT_PATH}")
        try:
            with open(STORE_LAYOUT_PATH, 'r', encoding='utf-8') as f:
                layouts = json.load(f)
                for store_id, layout_data in layouts.items():
                    cursor.execute(
                        "INSERT OR REPLACE INTO store_layouts (store_id, layout_json) VALUES (?, ?)",
                        (normalize_store_id(store_id), json.dumps(layout_data))
                    )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to load store layout JSON: {e}")

    # Load pos_transactions.csv into database if transaction table is empty
    cursor.execute("SELECT COUNT(*) FROM pos_transactions")
    if cursor.fetchone()[0] == 0 and os.path.exists(POS_TRANSACTIONS_PATH):
        logger.info(f"Loading POS transactions from {POS_TRANSACTIONS_PATH}")
        try:
            with open(POS_TRANSACTIONS_PATH, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                orders = {}
                for row in reader:
                    order_id = row['order_id']
                    # Parse date & time to ISO format
                    order_date = row['order_date'] # DD-MM-YYYY
                    order_time = row['order_time'] # HH:MM:SS
                    parts = order_date.split('-')
                    if len(parts) == 3:
                        day, month, year = parts
                        iso_ts = f"{year}-{month}-{day}T{order_time}"
                    else:
                        iso_ts = f"2026-04-10T{order_time}"
                    
                    store_id = normalize_store_id(row['store_id'])
                    amount = float(row['total_amount'])
                    
                    if order_id not in orders:
                        orders[order_id] = {
                            "store_id": store_id,
                            "timestamp": iso_ts,
                            "basket_value": 0.0
                        }
                    orders[order_id]["basket_value"] += amount
                
                for order_id, info in orders.items():
                    # Insert for original store
                    cursor.execute(
                        "INSERT OR REPLACE INTO pos_transactions (store_id, transaction_id, timestamp, basket_value_inr) VALUES (?, ?, ?, ?)",
                        (info["store_id"], order_id, info["timestamp"], info["basket_value"])
                    )
                    # Duplicate to ST1076 for seamless demo/simulation POS correlation
                    if info["store_id"] == "ST1008":
                        cursor.execute(
                            "INSERT OR REPLACE INTO pos_transactions (store_id, transaction_id, timestamp, basket_value_inr) VALUES (?, ?, ?, ?)",
                            ("ST1076", f"{order_id}_copy", info["timestamp"], info["basket_value"])
                        )
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to load POS transactions CSV: {e}")
            
    conn.close()

def save_event(event_dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    event_id = event_dict.get("event_id")
    store_id = normalize_store_id(event_dict.get("store_id") or event_dict.get("store_code"))
    camera_id = event_dict.get("camera_id")
    
    id_token = event_dict.get("id_token")
    track_id = event_dict.get("track_id")
    visitor_id = event_dict.get("visitor_id") or id_token or (f"TRACK_{track_id}" if track_id else "UNKNOWN")
    
    event_type = event_dict.get("event_type")
    
    timestamp = event_dict.get("timestamp") or event_dict.get("event_timestamp") or event_dict.get("event_time") or event_dict.get("queue_exit_ts") or event_dict.get("queue_join_ts")
    
    zone_id = event_dict.get("zone_id")
    
    metadata = event_dict.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
        
    queue_depth = event_dict.get("queue_depth") or metadata.get("queue_depth") or event_dict.get("queue_position_at_join")
    sku_zone = event_dict.get("sku_zone") or metadata.get("sku_zone") or event_dict.get("zone_type")
    session_seq = event_dict.get("session_seq") or metadata.get("session_seq") or 1
    
    wait_sec = event_dict.get("wait_seconds")
    wait_ms = wait_sec * 1000 if wait_sec is not None else 0
    dwell_ms = event_dict.get("dwell_ms") or wait_ms or 0
    is_staff = 1 if event_dict.get("is_staff", False) else 0
    confidence = event_dict.get("confidence") if event_dict.get("confidence") is not None else 1.0
    
    gender = event_dict.get("gender") or event_dict.get("gender_pred")
    age = event_dict.get("age") or event_dict.get("age_pred")
    age_bucket = event_dict.get("age_bucket")
    group_id = event_dict.get("group_id")
    group_size = event_dict.get("group_size")
    is_face_hidden = 1 if event_dict.get("is_face_hidden") else 0
    zone_type = event_dict.get("zone_type")
    is_revenue_zone = event_dict.get("is_revenue_zone")
    queue_join_ts = event_dict.get("queue_join_ts")
    queue_served_ts = event_dict.get("queue_served_ts")
    queue_exit_ts = event_dict.get("queue_exit_ts")
    wait_seconds = event_dict.get("wait_seconds")
    queue_position_at_join = event_dict.get("queue_position_at_join")
    abandoned = 1 if event_dict.get("abandoned") else 0

    try:
        cursor.execute("""
        INSERT OR IGNORE INTO events (
            event_id, store_id, camera_id, visitor_id, event_type, timestamp,
            zone_id, dwell_ms, is_staff, confidence, queue_depth, sku_zone, session_seq,
            id_token, track_id, gender, age, age_bucket, group_id, group_size,
            is_face_hidden, zone_type, is_revenue_zone, queue_join_ts, queue_served_ts,
            queue_exit_ts, wait_seconds, queue_position_at_join, abandoned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id, store_id, camera_id, visitor_id, event_type, timestamp,
            zone_id, dwell_ms, is_staff, confidence, queue_depth, sku_zone, session_seq,
            id_token, track_id, gender, age, age_bucket, group_id, group_size,
            is_face_hidden, zone_type, is_revenue_zone, queue_join_ts, queue_served_ts,
            queue_exit_ts, wait_seconds, queue_position_at_join, abandoned
        ))
        conn.commit()
        is_inserted = conn.total_changes > 0
        return is_inserted
    except Exception as e:
        logger.error(f"Database error saving event: {e}")
        raise e
    finally:
        conn.close()

def get_store_layout(store_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT layout_json FROM store_layouts WHERE store_id = ?", (normalize_store_id(store_id),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None
