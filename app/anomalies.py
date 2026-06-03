from app.database import get_db_connection, get_store_layout, normalize_store_id
from app.metrics import get_active_date_str, parse_iso_time, get_store_metrics
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger("AnomaliesService")

def get_store_anomalies(store_id: str) -> list:
    conn = get_db_connection()
    n_store_id = normalize_store_id(store_id)
    
    active_date = get_active_date_str(conn, n_store_id)
    if not active_date:
        conn.close()
        return []
        
    date_start = f"{active_date}T00:00:00"
    date_end = f"{active_date}T23:59:59"

    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT MAX(timestamp) FROM events 
        WHERE store_id = ?
    """, (n_store_id,))
    latest_event_time_str = cursor.fetchone()[0]
    if not latest_event_time_str:
        conn.close()
        return []
        
    db_now = parse_iso_time(latest_event_time_str)
    anomalies = []

    # 1. Queue Spike Check
    fifteen_mins_ago = (db_now - timedelta(minutes=15)).isoformat() + "Z"
    cursor.execute("""
        SELECT AVG(queue_depth) FROM events
        WHERE store_id = ? AND event_type IN ('BILLING_QUEUE_JOIN', 'queue_completed')
          AND timestamp BETWEEN ? AND ?
    """, (n_store_id, fifteen_mins_ago, latest_event_time_str))
    avg_queue_depth_row = cursor.fetchone()
    avg_q_depth = avg_queue_depth_row[0] if (avg_queue_depth_row and avg_queue_depth_row[0] is not None) else 0.0

    if avg_q_depth >= 4.0:
        anomalies.append({
            "anomaly_type": "BILLING_QUEUE_SPIKE",
            "severity": "CRITICAL",
            "timestamp": latest_event_time_str,
            "description": f"Billing line buildup detected. Average queue depth is {round(avg_q_depth, 1)} in the last 15 minutes.",
            "suggested_action": "Open additional billing terminals immediately and deploy queue-busting staff."
        })
    elif avg_q_depth >= 2.5:
        anomalies.append({
            "anomaly_type": "BILLING_QUEUE_SPIKE",
            "severity": "WARN",
            "timestamp": latest_event_time_str,
            "description": f"Moderate billing queue buildup. Average depth is {round(avg_q_depth, 1)}.",
            "suggested_action": "Alert backup cashiers to stand by for checkout duty."
        })

    # 2. Dead Zone Check
    layout = get_store_layout(n_store_id)
    if layout and "zones" in layout:
        for zone_id in layout["zones"].keys():
            if "BILLING" in zone_id:
                continue
                
            cursor.execute("""
                SELECT MAX(timestamp) FROM events
                WHERE store_id = ? AND zone_id = ? AND is_staff = 0 AND timestamp BETWEEN ? AND ?
            """, (n_store_id, zone_id, date_start, date_end))
            last_visit_str = cursor.fetchone()[0]
            
            if last_visit_str:
                last_visit = parse_iso_time(last_visit_str)
                minutes_since_visit = (db_now - last_visit).total_seconds() / 60.0
                
                if minutes_since_visit >= 30.0:
                    anomalies.append({
                        "anomaly_type": "DEAD_ZONE",
                        "severity": "WARN",
                        "timestamp": latest_event_time_str,
                        "description": f"Zone '{zone_id}' has not received any customer visits for {round(minutes_since_visit, 1)} minutes.",
                        "suggested_action": "Inspect zone display lighting, check product shelf stocks, or verify planogram compliance."
                    })
            else:
                anomalies.append({
                    "anomaly_type": "DEAD_ZONE",
                    "severity": "INFO",
                    "timestamp": latest_event_time_str,
                    "description": f"Zone '{zone_id}' has received zero customer interactions today.",
                    "suggested_action": "Check if shelf signages are clear or verify display setup."
                })

    # 3. Conversion Drop Check
    day_metrics = get_store_metrics(n_store_id)
    day_conv = day_metrics.get("conversion_rate", 0.0)

    one_hour_ago = (db_now - timedelta(hours=1)).isoformat() + "Z"
    
    cursor.execute("""
        SELECT COUNT(DISTINCT visitor_id) FROM events
        WHERE store_id = ? AND is_staff = 0 AND timestamp BETWEEN ? AND ?
    """, (n_store_id, one_hour_ago, latest_event_time_str))
    recent_visitors = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT DISTINCT visitor_id FROM events
        WHERE store_id = ? AND is_staff = 0 AND event_type IN ('BILLING_QUEUE_JOIN', 'queue_completed')
          AND timestamp BETWEEN ? AND ?
    """, (n_store_id, one_hour_ago, latest_event_time_str))
    recent_billing_visitors = [row[0] for row in cursor.fetchall()]

    from app.metrics import get_pos_transaction_times
    recent_txn_times = get_pos_transaction_times(conn, n_store_id, active_date)

    recent_converted = 0
    for r_vid in recent_billing_visitors:
        cursor.execute("""
            SELECT timestamp, abandoned FROM events
            WHERE store_id = ? AND visitor_id = ? AND event_type IN ('BILLING_QUEUE_JOIN', 'queue_completed')
              AND timestamp BETWEEN ? AND ?
        """, (n_store_id, r_vid, one_hour_ago, latest_event_time_str))
        r = cursor.fetchone()
        if r:
            b_time_str = r[0]
            is_abandoned = r[1]
            b_time = parse_iso_time(b_time_str)
            
            if b_time:
                is_converted = False
                for txn_time in recent_txn_times:
                    if 0 <= (txn_time - b_time).total_seconds() <= 300:
                        is_converted = True
                        break
                if is_converted or (not is_abandoned):
                    recent_converted += 1

    recent_conv = 0.0
    if recent_visitors > 0:
        recent_conv = float(recent_converted) / float(recent_visitors)

    if recent_visitors >= 5 and recent_conv < (day_conv * 0.4):
        anomalies.append({
            "anomaly_type": "CONVERSION_DROP",
            "severity": "CRITICAL",
            "timestamp": latest_event_time_str,
            "description": f"Conversion rate dropped to {round(recent_conv * 100, 1)}% in the last hour compared to daily baseline of {round(day_conv * 100, 1)}%.",
            "suggested_action": "Check billing terminals for software lag, inspect for payment gateway outages, or deploy floor staff to assist shoppers."
        })
    elif recent_visitors >= 3 and recent_conv < (day_conv * 0.6):
        anomalies.append({
            "anomaly_type": "CONVERSION_DROP",
            "severity": "WARN",
            "timestamp": latest_event_time_str,
            "description": f"Slight conversion rate drop to {round(recent_conv * 100, 1)}% in the last hour (daily baseline: {round(day_conv * 100, 1)}%).",
            "suggested_action": "Monitor POS checkout flow for bottlenecks."
        })

    conn.close()
    return anomalies
