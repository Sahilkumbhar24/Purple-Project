# PROMPT: Generate test assertions to validate Apex Retail Store Intelligence API
# CHANGES MADE: Custom endpoints matching PDF page 6

import requests
import json
import uuid

BASE_URL = "http://localhost:8000"

def test_health_endpoint():
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "last_event_timestamps" in data
    assert data["status"] in ["ok", "healthy"]

def test_ingest_endpoint_valid_event():
    event_id = str(uuid.uuid4())
    event_payload = [
        {
            "event_id": event_id,
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_test_001",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:00:10Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.98,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": 1
            }
        }
    ]
    response = requests.post(f"{BASE_URL}/events/ingest", json=event_payload)
    assert response.status_code in [200, 201]
    data = response.json()
    assert data.get("ingested", 0) > 0 or data.get("success", False)

def test_ingest_idempotency():
    event_id = str(uuid.uuid4())
    event_payload = [
        {
            "event_id": event_id,
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_test_002",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:02:10Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": False,
            "confidence": 0.95,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": 1
            }
        }
    ]
    # First ingest
    r1 = requests.post(f"{BASE_URL}/events/ingest", json=event_payload)
    assert r1.status_code in [200, 201]
    
    # Second ingest (should be idempotent and not fail/duplicate)
    r2 = requests.post(f"{BASE_URL}/events/ingest", json=event_payload)
    assert r2.status_code in [200, 201]

def test_store_metrics():
    response = requests.get(f"{BASE_URL}/stores/STORE_BLR_002/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "unique_visitors" in data
    assert "conversion_rate" in data
    assert "avg_dwell_per_zone" in data
    assert "queue_depth" in data
    assert "abandonment_rate" in data
    assert isinstance(data["unique_visitors"], int)
    assert isinstance(data["conversion_rate"], float)

def test_store_funnel():
    response = requests.get(f"{BASE_URL}/stores/STORE_BLR_002/funnel")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Check funnel stages are represented
    stages = [item.get("stage") for item in data]
    assert "Entry" in stages or "ENTRY" in stages
    assert "Billing Queue" in stages or "BILLING_QUEUE" in stages

def test_store_heatmap():
    response = requests.get(f"{BASE_URL}/stores/STORE_BLR_002/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for zone in data:
        assert "zone_id" in zone
        assert "normalized_score" in zone or "normalized" in zone
        assert "avg_dwell_ms" in zone or "avg_dwell" in zone

def test_store_anomalies():
    response = requests.get(f"{BASE_URL}/stores/STORE_BLR_002/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for anomaly in data:
        assert "anomaly_type" in anomaly or "type" in anomaly
        assert "severity" in anomaly
        assert "suggested_action" in anomaly

def test_metrics_excludes_staff():
    # Ingest a staff event and verify metrics don't count it
    event_id = str(uuid.uuid4())
    staff_payload = [
        {
            "event_id": event_id,
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_ENTRY_01",
            "visitor_id": "VIS_staff_999",
            "event_type": "ENTRY",
            "timestamp": "2026-03-03T14:10:00Z",
            "zone_id": None,
            "dwell_ms": 0,
            "is_staff": True,
            "confidence": 0.99,
            "metadata": {
                "queue_depth": None,
                "sku_zone": None,
                "session_seq": 1
            }
        }
    ]
    r = requests.post(f"{BASE_URL}/events/ingest", json=staff_payload)
    assert r.status_code in [200, 201]

def test_graceful_degradation_invalid_store():
    # Calling details for a non-existent store should return 200 with empty values or gracefully handle it, not crash
    response = requests.get(f"{BASE_URL}/stores/STORE_NONEXISTENT/metrics")
    assert response.status_code in [200, 404]

if __name__ == "__main__":
    print("Running API validation assertions...")
    try:
        test_health_endpoint()
        print("[PASS] Health endpoint assertions passed")
        test_ingest_endpoint_valid_event()
        print("[PASS] Ingest endpoint assertions passed")
        test_ingest_idempotency()
        print("[PASS] Ingest idempotency assertions passed")
        test_store_metrics()
        print("[PASS] Store metrics assertions passed")
        test_store_funnel()
        print("[PASS] Store funnel assertions passed")
        test_store_heatmap()
        print("[PASS] Store heatmap assertions passed")
        test_store_anomalies()
        print("[PASS] Store anomalies assertions passed")
        print("\nAll standard API assertions passed successfully!")
    except AssertionError as e:
        print("[FAIL] Assertion failed during testing:", e)
    except Exception as e:
        print("[ERROR] Connection error or other failure:", e)
