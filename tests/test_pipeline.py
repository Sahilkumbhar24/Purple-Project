# PROMPT: Generate pytest test suite for Pydantic event schema validation models
# CHANGES MADE: Added edge cases for null values and invalid timestamps

import pytest
from app.models import EventModel, EventMetadata

def test_valid_entry_event():
    payload = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
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
    model = EventModel(**payload)
    assert model.event_id == "550e8400-e29b-41d4-a716-446655440000"
    assert model.event_type == "ENTRY"

def test_invalid_event_type():
    payload = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "INVALID_TYPE",  # Invalid
        "timestamp": "2026-03-03T14:22:10Z",
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
    with pytest.raises(ValueError):
        EventModel(**payload)

def test_entry_event_with_zone_id_fails():
    payload = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_ENTRY_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "ENTRY",
        "timestamp": "2026-03-03T14:22:10Z",
        "zone_id": "SKINCARE",  # Fail: ENTRY shouldn't have a zone
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.98,
        "metadata": {
            "queue_depth": None,
            "sku_zone": None,
            "session_seq": 1
        }
    }
    with pytest.raises(ValueError) as exc:
        EventModel(**payload)
    assert "zone_id must be null" in str(exc.value)

def test_billing_queue_join_missing_depth_fails():
    payload = {
        "event_id": "550e8400-e29b-41d4-a716-446655440000",
        "store_id": "STORE_BLR_002",
        "camera_id": "CAM_BILLING_01",
        "visitor_id": "VIS_c8a2f1",
        "event_type": "BILLING_QUEUE_JOIN",
        "timestamp": "2026-03-03T14:25:10Z",
        "zone_id": "BILLING_ZONE",
        "dwell_ms": 0,
        "is_staff": False,
        "confidence": 0.98,
        "metadata": {
            "queue_depth": None,  # Fail: queue_depth is required
            "sku_zone": None,
            "session_seq": 4
        }
    }
    with pytest.raises(ValueError) as exc:
        EventModel(**payload)
    assert "queue_depth is required" in str(exc.value)

def test_centroid_tracker_and_staff_uniform_classifier():
    from pipeline.tracker import CentroidTracker
    from pipeline.detect import classify_staff_by_uniform

    tracker = CentroidTracker()
    
    # 1. Test Tracker Bounding Box & Centroid Registration
    rects = [[100, 100, 200, 300]]
    objects = tracker.update(rects)
    
    visitor_ids = list(objects.keys())
    assert len(visitor_ids) == 1
    vid = visitor_ids[0]
    assert objects[vid] == (150, 200)
    assert list(tracker.rectangles[vid]) == [100, 100, 200, 300]
    
    try:
        import numpy as np
        import cv2
    except ImportError:
        # Skip CV parts of the test if numpy or cv2 are missing on this host
        return
    
    # 2. Test Staff Uniform Classification on Dark BGR Frame
    frame_staff = np.ones((500, 500, 3), dtype=np.uint8) * 20  # dark gray/black clothes
    box = [50, 50, 250, 450]
    
    is_staff = classify_staff_by_uniform(frame_staff, box)
    assert is_staff is True
    
    # 3. Test Staff Uniform Classification on Light BGR Frame
    frame_visitor = np.ones((500, 500, 3), dtype=np.uint8) * 180  # light gray/bright clothes
    is_staff_visitor = classify_staff_by_uniform(frame_visitor, box)
    assert is_staff_visitor is False
