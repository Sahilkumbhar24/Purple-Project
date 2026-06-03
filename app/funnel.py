from app.database import get_db_connection, normalize_store_id
from app.metrics import get_active_date_str, parse_iso_time, resolve_visitor_ids, get_pos_transaction_times
import logging

logger = logging.getLogger("FunnelService")

def get_store_funnel(store_id: str) -> list:
    conn = get_db_connection()
    n_store_id = normalize_store_id(store_id)
    
    active_date = get_active_date_str(conn, n_store_id)
    if not active_date:
        conn.close()
        return [
            {"stage": "Entry", "count": 0, "drop_off_pct": 0.0},
            {"stage": "Zone Visit", "count": 0, "drop_off_pct": 0.0},
            {"stage": "Billing Queue", "count": 0, "drop_off_pct": 0.0},
            {"stage": "Purchase", "count": 0, "drop_off_pct": 0.0}
        ]
        
    date_start = f"{active_date}T00:00:00"
    date_end = f"{active_date}T23:59:59"

    cursor = conn.cursor()

    # Query all events for the active date
    cursor.execute("""
        SELECT * FROM events
        WHERE store_id = ? AND timestamp BETWEEN ? AND ?
    """, (n_store_id, date_start, date_end))
    raw_rows = [dict(r) for r in cursor.fetchall()]
    
    # Resolve local tracks to global Re-ID tokens
    rows = resolve_visitor_ids(raw_rows)

    # Fetch POS transaction times mapped to active date
    txn_times = get_pos_transaction_times(conn, n_store_id, active_date)

    conn.close()

    # Group visitor history
    visitor_journeys = {}
    for r in rows:
        if r.get("is_staff"):
            continue # Skip staff
            
        vid = r["visitor_id"]
        if not vid:
            continue
            
        if vid not in visitor_journeys:
            visitor_journeys[vid] = {
                "entered_store": False,
                "visited_product_zone": False,
                "joined_billing_queue": False,
                "billing_times": [],
                "explicit_completed": False,
                "has_abandon_event": False
            }
            
        evt_type = r["event_type"]
        zone_id = r["zone_id"]
        
        # 1. Entry check
        if evt_type in ["ENTRY", "REENTRY", "entry"] or r["visitor_id"]:
            visitor_journeys[vid]["entered_store"] = True
            
        # 2. Product zone check (excluding billing counter)
        if zone_id and zone_id != "BILLING_ZONE" and "BILLING" not in zone_id:
            visitor_journeys[vid]["visited_product_zone"] = True
            
        # 3. Billing counter check
        if evt_type in ["BILLING_QUEUE_JOIN", "queue_completed"] or (evt_type == "ZONE_ENTER" and zone_id == "BILLING_ZONE") or (zone_id and "BILLING" in zone_id):
            visitor_journeys[vid]["joined_billing_queue"] = True
            t_bill = parse_iso_time(r["timestamp"])
            if t_bill:
                visitor_journeys[vid]["billing_times"].append(t_bill)
            if evt_type == "queue_completed" or (evt_type == "BILLING_QUEUE_JOIN" and not r.get("abandoned")):
                if r.get("abandoned") == 0 or r.get("abandoned") is False:
                    visitor_journeys[vid]["explicit_completed"] = True
                    
        if evt_type == "BILLING_QUEUE_ABANDON" or r.get("abandoned"):
            visitor_journeys[vid]["has_abandon_event"] = True

    # Count visitors in each funnel stage
    entry_count = 0
    zone_visit_count = 0
    billing_queue_count = 0
    purchase_count = 0

    for vid, journey in visitor_journeys.items():
        if journey["entered_store"]:
            entry_count += 1
            
            if journey["visited_product_zone"]:
                zone_visit_count += 1
                
            if journey["joined_billing_queue"]:
                billing_queue_count += 1
                
                # Check for conversion via POS timestamp correlation
                is_converted = False
                for b_time in journey["billing_times"]:
                    for txn_time in txn_times:
                        time_diff = (txn_time - b_time).total_seconds()
                        if 0 <= time_diff <= 300: # 5 minutes
                            is_converted = True
                            break
                    if is_converted:
                        break
                        
                # Or fallback to explicit completed status
                if is_converted or (journey["explicit_completed"] and not journey["has_abandon_event"]):
                    purchase_count += 1

    # Enforce strict hierarchy: Entry >= Zone Visit >= Billing Queue >= Purchase
    zone_visit_count = min(zone_visit_count, entry_count)
    billing_queue_count = min(billing_queue_count, zone_visit_count)
    purchase_count = min(purchase_count, billing_queue_count)

    # Compute drop-off percentages
    drop_off_zone = 0.0
    if entry_count > 0:
        drop_off_zone = ((entry_count - zone_visit_count) / entry_count) * 100
        
    drop_off_billing = 0.0
    if zone_visit_count > 0:
        drop_off_billing = ((zone_visit_count - billing_queue_count) / zone_visit_count) * 100
        
    drop_off_purchase = 0.0
    if billing_queue_count > 0:
        drop_off_purchase = ((billing_queue_count - purchase_count) / billing_queue_count) * 100

    return [
        {
            "stage": "Entry",
            "count": entry_count,
            "drop_off_pct": 0.0
        },
        {
            "stage": "Zone Visit",
            "count": zone_visit_count,
            "drop_off_pct": round(drop_off_zone, 1)
        },
        {
            "stage": "Billing Queue",
            "count": billing_queue_count,
            "drop_off_pct": round(drop_off_billing, 1)
        },
        {
            "stage": "Purchase",
            "count": purchase_count,
            "drop_off_pct": round(drop_off_purchase, 1)
        }
    ]
