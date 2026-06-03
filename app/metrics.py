from datetime import datetime, timedelta
from app.database import get_db_connection, normalize_store_id
import logging

logger = logging.getLogger("MetricsService")

def parse_iso_time(ts_str):
    if not ts_str:
        return None
    ts_str = ts_str.replace("Z", "")
    if "+" in ts_str:
        ts_str = ts_str.split("+")[0]
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None

def get_active_date_str(conn, store_id):
    """
    Finds the date of the latest event in the database to establish 'today' dynamically.
    """
    n_store_id = normalize_store_id(store_id)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MAX(timestamp) FROM events 
        WHERE store_id = ? AND is_staff = 0
    """, (n_store_id,))
    row = cursor.fetchone()
    if row and row[0]:
        latest_ts = parse_iso_time(row[0])
        if latest_ts:
            return latest_ts.strftime("%Y-%m-%d")
    return None

def resolve_visitor_ids(events_list):
    """
    Dynamically aligns local camera track_id Centroids to Re-ID entry id_tokens
    by matching demographics (gender, age_bucket) and timestamps.
    """
    entries = []
    for ev in events_list:
        if ev['event_type'] in ('entry', 'ENTRY', 'exit', 'EXIT'):
            entries.append(ev)
            
    resolved = []
    for ev in events_list:
        ev_dict = dict(ev)
        
        # Determine current id token
        if ev_dict.get('id_token'):
            ev_dict['visitor_id'] = ev_dict['id_token']
        elif ev_dict.get('visitor_id') and not ev_dict['visitor_id'].startswith("TRACK_"):
            pass
        elif ev_dict.get('track_id') is not None:
            track_id = ev_dict['track_id']
            egender = ev_dict.get('gender') or ev_dict.get('gender_pred')
            eage_bucket = ev_dict.get('age_bucket')
            etime_str = ev_dict.get('timestamp')
            etime = parse_iso_time(etime_str)
            
            best_vid = None
            min_time_diff = float('inf')
            
            for ent in entries:
                ent_vid = ent.get('id_token') or ent.get('visitor_id')
                ent_gender = ent.get('gender_pred') or ent.get('gender')
                ent_age_bucket = ent.get('age_bucket')
                ent_time_str = ent.get('timestamp')
                ent_time = parse_iso_time(ent_time_str)
                
                # Check for demographics matches (gender & age_bucket)
                if ent_gender == egender and ent_age_bucket == eage_bucket:
                    if ent_time and etime:
                        diff = (etime - ent_time).total_seconds()
                        if diff >= -30 and diff < min_time_diff:
                            min_time_diff = diff
                            best_vid = ent_vid
            
            if best_vid:
                ev_dict['visitor_id'] = best_vid
            else:
                ev_dict['visitor_id'] = f"TRACK_{track_id}"
                
        resolved.append(ev_dict)
    return resolved

def get_pos_transaction_times(conn, store_id, active_date):
    cursor = conn.cursor()
    n_store_id = normalize_store_id(store_id)
    cursor.execute("""
        SELECT timestamp FROM pos_transactions
        WHERE store_id = ?
    """, (n_store_id,))
    txn_rows = cursor.fetchall()
    
    txn_times = []
    for r in txn_rows:
        dt = parse_iso_time(r["timestamp"])
        if dt:
            # Map time portion to active_date
            time_str = dt.strftime("%H:%M:%S")
            combined_dt = parse_iso_time(f"{active_date}T{time_str}")
            if combined_dt:
                txn_times.append(combined_dt)
    return txn_times

def get_store_metrics(store_id: str) -> dict:
    conn = get_db_connection()
    n_store_id = normalize_store_id(store_id)
    
    active_date = get_active_date_str(conn, n_store_id)
    if not active_date:
        conn.close()
        return {
            "unique_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_per_zone": {},
            "queue_depth": 0,
            "abandonment_rate": 0.0
        }
        
    date_start = f"{active_date}T00:00:00"
    date_end = f"{active_date}T23:59:59"

    cursor = conn.cursor()

    # Retrieve all events for this store on active date
    cursor.execute("""
        SELECT * FROM events
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
    """, (n_store_id, date_start, date_end))
    raw_rows = [dict(r) for r in cursor.fetchall()]
    
    # Resolve local tracks to global Re-ID tokens
    rows = resolve_visitor_ids(raw_rows)

    # Exclude staff from metrics calculations
    customer_rows = [r for r in rows if not r.get("is_staff")]
    
    # Unique Visitors Count
    unique_visitors_set = set(r["visitor_id"] for r in customer_rows if r["visitor_id"])
    unique_visitors = len(unique_visitors_set)

    if unique_visitors == 0:
        conn.close()
        return {
            "unique_visitors": 0,
            "conversion_rate": 0.0,
            "avg_dwell_per_zone": {},
            "queue_depth": 0,
            "abandonment_rate": 0.0
        }

    # Group events by visitor session
    sessions = {}
    for r in customer_rows:
        vid = r["visitor_id"]
        if vid not in sessions:
            sessions[vid] = []
        sessions[vid].append(r)

    # Fetch POS transaction times mapped to active date
    txn_times = get_pos_transaction_times(conn, n_store_id, active_date)

    converted_sessions_count = 0
    billing_total_sessions = 0
    abandoned_sessions_count = 0

    for vid, evts in sessions.items():
        billing_enter_time = None
        has_abandon_event = False
        explicit_completed = False
        
        for evt in evts:
            etype = evt["event_type"]
            zone = evt.get("zone_id")
            
            # Check if visitor joined queue or entered billing zone
            if etype in ["BILLING_QUEUE_JOIN", "queue_completed"] or (etype == "ZONE_ENTER" and zone == "BILLING_ZONE") or (zone and "BILLING" in zone):
                billing_enter_time = parse_iso_time(evt["timestamp"])
            if etype == "BILLING_QUEUE_ABANDON" or evt.get("abandoned"):
                has_abandon_event = True
            if etype == "queue_completed" or (etype == "BILLING_QUEUE_JOIN" and not evt.get("abandoned")):
                if evt.get("abandoned") == 0 or evt.get("abandoned") is False:
                    explicit_completed = True

        if billing_enter_time:
            billing_total_sessions += 1
            
            # 1. Correlate with POS
            is_converted = False
            for txn_time in txn_times:
                time_diff = (txn_time - billing_enter_time).total_seconds()
                if 0 <= time_diff <= 300: # 5 minutes window
                    is_converted = True
                    break
            
            # 2. Or fallback to explicit completed status
            if is_converted or (explicit_completed and not has_abandon_event):
                converted_sessions_count += 1
            else:
                abandoned_sessions_count += 1
        elif has_abandon_event:
            billing_total_sessions += 1
            abandoned_sessions_count += 1

    conversion_rate = float(converted_sessions_count) / float(unique_visitors)
    
    abandonment_rate = 0.0
    if billing_total_sessions > 0:
        abandonment_rate = float(abandoned_sessions_count) / float(billing_total_sessions)

    # Average Dwell per Zone (ignoring staff)
    dwell_map = {}
    for r in customer_rows:
        zone = r.get("zone_id")
        dwell = r.get("dwell_ms", 0)
        if zone and dwell > 0:
            if zone not in dwell_map:
                dwell_map[zone] = []
            dwell_map[zone].append(dwell)
            
    avg_dwell_per_zone = {
        zone: round(sum(dwells) / len(dwells), 1)
        for zone, dwells in dwell_map.items()
    }

    # Queue Depth (avg reported queue depths on the active day)
    cursor.execute("""
        SELECT AVG(queue_depth) FROM events
        WHERE store_id = ? AND is_staff = 0 AND event_type IN ('BILLING_QUEUE_JOIN', 'queue_completed')
          AND timestamp BETWEEN ? AND ?
    """, (n_store_id, date_start, date_end))
    avg_queue_depth_row = cursor.fetchone()
    queue_depth = round(avg_queue_depth_row[0], 1) if (avg_queue_depth_row and avg_queue_depth_row[0] is not None) else 0.0

    conn.close()

    return {
        "unique_visitors": unique_visitors,
        "conversion_rate": round(conversion_rate, 4),
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "queue_depth": queue_depth,
        "abandonment_rate": round(abandonment_rate, 4)
    }
