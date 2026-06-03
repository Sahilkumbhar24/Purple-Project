# PROMPT: Implement dual-mode detection pipeline with YOLOv8 CV processing and real-time simulator
# CHANGES MADE: Added command-line parser, OpenCV frame processing loop stub, and interactive event simulation logic

import argparse
import time
import json
import os
import sys
import logging
import uuid
from datetime import datetime, timedelta, timezone

# Import custom modules from pipeline
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from tracker import CentroidTracker
from emit import EventEmitter, post_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("DetectionPipeline")

def run_simulation(events_file, store_id, speed_multiplier, api_url):
    """
    Simulates real-time event streaming by replaying events from a JSONL file.
    """
    logger.info(f"Starting simulation mode using events file: {events_file}")
    if not os.path.exists(events_file):
        logger.error(f"Events file not found: {events_file}")
        return

    # Read events
    events = []
    with open(events_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    e = json.loads(line)
                    # Standardize store_id and timestamp keys
                    if "store_id" not in e:
                        e["store_id"] = e.get("store_code")
                    if e.get("store_id"):
                        s = e["store_id"].strip()
                        if s.lower().startswith("store_"):
                            parts = s.split("_")
                            if len(parts) == 2 and parts[1].isdigit():
                                e["store_id"] = f"ST{parts[1]}"
                            else:
                                e["store_id"] = s
                        else:
                            e["store_id"] = s
                            
                    if "timestamp" not in e:
                        e["timestamp"] = e.get("event_timestamp") or e.get("event_time") or e.get("queue_exit_ts") or e.get("queue_join_ts")
                    events.append(e)
                except Exception as e_err:
                    logger.warning(f"Malformed event JSON: {e_err}")

    # Filter by store if requested
    if store_id:
        filter_store = store_id.strip()
        if filter_store.lower().startswith("store_"):
            parts = filter_store.split("_")
            if len(parts) == 2 and parts[1].isdigit():
                filter_store = f"ST{parts[1]}"
        events = [e for e in events if e.get("store_id") == filter_store]
        logger.info(f"Filtered to {len(events)} events for store {filter_store}")
    else:
        logger.info(f"Replaying all {len(events)} events in the file")

    if not events:
        logger.warning("No events to replay")
        return

    # Sort events by timestamp
    events.sort(key=lambda x: x.get("timestamp", ""))

    # Update event timestamps to start from NOW to simulate real-time feed activity
    now = datetime.utcnow()
    first_event_time = datetime.fromisoformat(events[0]["timestamp"].replace("Z", "+00:00"))
    time_offset = now - first_event_time.replace(tzinfo=None)

    for e in events:
        evt_time = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
        new_time = evt_time + time_offset
        e["timestamp"] = new_time.isoformat() + "Z"

    logger.info(f"Streaming events. Speed multiplier: {speed_multiplier}x")
    
    emitter = EventEmitter(ingest_url=f"{api_url}/events/ingest", batch_size=1) # Send instantly

    for i in range(len(events)):
        curr_event = events[i]
        
        # Calculate time to sleep until this event should occur
        if i > 0:
            prev_event = events[i - 1]
            t_curr = datetime.fromisoformat(curr_event["timestamp"].replace("Z", "+00:00"))
            t_prev = datetime.fromisoformat(prev_event["timestamp"].replace("Z", "+00:00"))
            sleep_sec = (t_curr - t_prev).total_seconds()
            
            # Scale down sleep time by speed multiplier
            sleep_adjusted = sleep_sec / speed_multiplier
            if sleep_adjusted > 0:
                time.sleep(sleep_adjusted)

        # Post the event
        logger.info(f"Simulating Event: {curr_event['event_type']} - Visitor: {curr_event.get('visitor_id') or curr_event.get('id_token') or curr_event.get('track_id')} - Zone: {curr_event.get('zone_id')}")
        emitter.emit(curr_event)

    logger.info("Simulation completed.")

def classify_staff_by_uniform(frame, box):
    """
    Classifies if a person is a staff member based on their uniform:
    Black shirt (upper body) and Black pants (lower body).
    """
    try:
        import numpy as np
        import cv2
    except ImportError:
        return False

    h, w, _ = frame.shape
    x1, y1, x2, y2 = box
    
    # Clip coordinates to frame boundaries
    x1 = max(0, int(x1))
    y1 = max(0, int(y1))
    x2 = min(w - 1, int(x2))
    y2 = min(h - 1, int(y2))
    
    box_w = x2 - x1
    box_h = y2 - y1
    
    if box_w <= 10 or box_h <= 10:
        return False
        
    person_crop = frame[y1:y2, x1:x2]
    
    # Upper body region: top 15% to 45% of bounding box height
    upper_y1 = int(box_h * 0.15)
    upper_y2 = int(box_h * 0.45)
    upper_crop = person_crop[upper_y1:upper_y2, :]
    
    # Lower body region: 55% to 85% of bounding box height
    lower_y1 = int(box_h * 0.55)
    lower_y2 = int(box_h * 0.85)
    lower_crop = person_crop[lower_y1:lower_y2, :]
    
    if upper_crop.size == 0 or lower_crop.size == 0:
        return False
        
    # Convert to HSV to analyze Value (brightness)
    upper_hsv = cv2.cvtColor(upper_crop, cv2.COLOR_BGR2HSV)
    lower_hsv = cv2.cvtColor(lower_crop, cv2.COLOR_BGR2HSV)
    
    avg_upper_v = np.mean(upper_hsv[:, :, 2])
    avg_lower_v = np.mean(lower_hsv[:, :, 2])
    
    # Staff uniform: Black shirt & pants -> both upper and lower should be dark (Value < 85)
    if avg_upper_v < 85 and avg_lower_v < 85:
        return True
    return False

def run_real_cv(video_path, store_id, camera_id, api_url):
    """
    Real CV mode: runs YOLOv8 and Centroid Tracking on the MP4 file
    """
    logger.info(f"Initializing YOLOv8 Computer Vision Pipeline on {video_path} for camera {camera_id}...")
    
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError:
        logger.error("Computer Vision libraries (opencv-python, ultralytics) are not installed on this host.")
        logger.error("Please run the pipeline in 'simulation' mode or install requirements: pip install opencv-python ultralytics")
        sys.exit(1)

    # Load YOLOv8 model (default nano model for speed)
    model = YOLO("yolov8n.pt")
    tracker = CentroidTracker(max_disappeared=20, min_distance=80)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video file: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    frame_count = 0
    
    emitter = EventEmitter(ingest_url=f"{api_url}/events/ingest", batch_size=5)
    
    entry_line_y = 540 # Middle of 1080p frame
    
    # Store-specific local track history for state transitions
    visitor_zones = {}      # visitor_id -> current_zone
    zone_enter_times = {}   # visitor_id -> datetime
    last_dwell_time = {}    # visitor_id -> datetime
    visitor_billing = {}    # visitor_id -> bool
    session_seqs = {}       # visitor_id -> int
    
    logger.info("Processing frames... (Press Ctrl+C to stop)")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_count += 1
            # Process every 5th frame to run faster than real-time
            if frame_count % 5 != 0:
                continue

            # Run detection on person class (class 0)
            results = model(frame, classes=[0], verbose=False)
            rects = []
            
            for result in results:
                boxes = result.boxes.xyxy.cpu().numpy()
                for box in boxes:
                    rects.append(box.astype(int))

            # Update tracker
            objects = tracker.update(rects)
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            
            # Check for camera type specific processing
            if "ENTRY" in camera_id.upper() or "CAM 1" in video_path.upper() or "CAM_ENTRY" in camera_id.upper():
                # --- ENTRY / EXIT CAMERA ---
                for visitor_id, centroid in objects.items():
                    crossing = tracker.check_crossing(visitor_id, threshold_y=entry_line_y)
                    if crossing:
                        # Dynamically classify staff based on uniform colors
                        box = tracker.rectangles.get(visitor_id)
                        is_staff = False
                        if box is not None:
                            is_staff = classify_staff_by_uniform(frame, box)
                            if is_staff:
                                logger.info(f"Detected employee uniform (black shirt/pants) for {visitor_id}. Classifying as staff.")
                        
                        seq = session_seqs.get(visitor_id, 0) + 1
                        session_seqs[visitor_id] = seq
                        
                        event = {
                            "event_id": str(uuid.uuid4()),
                            "store_id": store_id,
                            "camera_id": camera_id,
                            "visitor_id": visitor_id,
                            "event_type": crossing,
                            "timestamp": timestamp,
                            "zone_id": None,
                            "dwell_ms": 0,
                            "is_staff": is_staff,
                            "confidence": 0.95,
                            "metadata": {
                                "queue_depth": None,
                                "sku_zone": None,
                                "session_seq": seq
                            }
                        }
                        emitter.emit(event)
                        
            elif "FLOOR" in camera_id.upper() or "CAM 2" in video_path.upper() or "CAM_FLOOR" in camera_id.upper():
                # --- MAIN FLOOR ZONE CAMERA ---
                for visitor_id, centroid in objects.items():
                    cx, cy = centroid
                    
                    # ROI-based zone definitions (width: 1920 pixels)
                    if cx < 640:
                        zone_id = "SKINCARE"
                        sku_zone = "MOISTURISER"
                    elif cx >= 1280:
                        zone_id = "HAIRCARE"
                        sku_zone = "SHAMPOO"
                    else:
                        zone_id = "COSMETICS"
                        sku_zone = "LIPSTICK"
                        
                    box = tracker.rectangles.get(visitor_id)
                    is_staff = False
                    if box is not None:
                        is_staff = classify_staff_by_uniform(frame, box)
                        
                    now_time = datetime.now(timezone.utc)
                    seq = session_seqs.get(visitor_id, 0)
                    
                    # 1. ZONE ENTER
                    if visitor_id not in visitor_zones:
                        visitor_zones[visitor_id] = zone_id
                        zone_enter_times[visitor_id] = now_time
                        last_dwell_time[visitor_id] = now_time
                        
                        seq += 1
                        session_seqs[visitor_id] = seq
                        
                        event = {
                            "event_id": str(uuid.uuid4()),
                            "store_id": store_id,
                            "camera_id": camera_id,
                            "visitor_id": visitor_id,
                            "event_type": "ZONE_ENTER",
                            "timestamp": timestamp,
                            "zone_id": zone_id,
                            "dwell_ms": 0,
                            "is_staff": is_staff,
                            "confidence": 0.95,
                            "metadata": {
                                "queue_depth": None,
                                "sku_zone": sku_zone,
                                "session_seq": seq
                            }
                        }
                        emitter.emit(event)
                        
                    # 2. ZONE CHANGE
                    elif visitor_zones[visitor_id] != zone_id:
                        prev_zone = visitor_zones[visitor_id]
                        dwell_ms = int((now_time - zone_enter_times[visitor_id]).total_seconds() * 1000)
                        
                        seq += 1
                        event_exit = {
                            "event_id": str(uuid.uuid4()),
                            "store_id": store_id,
                            "camera_id": camera_id,
                            "visitor_id": visitor_id,
                            "event_type": "ZONE_EXIT",
                            "timestamp": timestamp,
                            "zone_id": prev_zone,
                            "dwell_ms": max(0, dwell_ms),
                            "is_staff": is_staff,
                            "confidence": 0.95,
                            "metadata": {
                                "queue_depth": None,
                                "sku_zone": None,
                                "session_seq": seq
                            }
                        }
                        emitter.emit(event_exit)
                        
                        visitor_zones[visitor_id] = zone_id
                        zone_enter_times[visitor_id] = now_time
                        last_dwell_time[visitor_id] = now_time
                        
                        seq += 1
                        event_enter = {
                            "event_id": str(uuid.uuid4()),
                            "store_id": store_id,
                            "camera_id": camera_id,
                            "visitor_id": visitor_id,
                            "event_type": "ZONE_ENTER",
                            "timestamp": timestamp,
                            "zone_id": zone_id,
                            "dwell_ms": 0,
                            "is_staff": is_staff,
                            "confidence": 0.95,
                            "metadata": {
                                "queue_depth": None,
                                "sku_zone": sku_zone,
                                "session_seq": seq
                            }
                        }
                        emitter.emit(event_enter)
                        session_seqs[visitor_id] = seq
                        
                    # 3. ZONE DWELL
                    else:
                        elapsed_dwell = (now_time - last_dwell_time[visitor_id]).total_seconds()
                        if elapsed_dwell >= 10.0: # Emit every 10s of processing time for testing
                            last_dwell_time[visitor_id] = now_time
                            total_dwell = int((now_time - zone_enter_times[visitor_id]).total_seconds() * 1000)
                            
                            seq += 1
                            session_seqs[visitor_id] = seq
                            
                            event_dwell = {
                                "event_id": str(uuid.uuid4()),
                                "store_id": store_id,
                                "camera_id": camera_id,
                                "visitor_id": visitor_id,
                                "event_type": "ZONE_DWELL",
                                "timestamp": timestamp,
                                "zone_id": zone_id,
                                "dwell_ms": max(0, total_dwell),
                                "is_staff": is_staff,
                                "confidence": 0.95,
                                "metadata": {
                                    "queue_depth": None,
                                    "sku_zone": sku_zone,
                                    "session_seq": seq
                                }
                            }
                            emitter.emit(event_dwell)
                            
            elif "BILLING" in camera_id.upper() or "CAM 3" in video_path.upper() or "CAM_BILLING" in camera_id.upper():
                # --- BILLING CAMERA ---
                for visitor_id, centroid in objects.items():
                    cx, cy = centroid
                    now_time = datetime.now(timezone.utc)
                    seq = session_seqs.get(visitor_id, 0)
                    
                    box = tracker.rectangles.get(visitor_id)
                    is_staff = False
                    if box is not None:
                        is_staff = classify_staff_by_uniform(frame, box)
                    
                    if cy > 400: # Counter queue zone
                        if not visitor_billing.get(visitor_id):
                            visitor_billing[visitor_id] = True
                            q_depth = sum([1 for vid, cent in objects.items() if cent[1] > 400])
                            
                            seq += 1
                            session_seqs[visitor_id] = seq
                            
                            event = {
                                "event_id": str(uuid.uuid4()),
                                "store_id": store_id,
                                "camera_id": camera_id,
                                "visitor_id": visitor_id,
                                "event_type": "BILLING_QUEUE_JOIN",
                                "timestamp": timestamp,
                                "zone_id": "BILLING_ZONE",
                                "dwell_ms": 0,
                                "is_staff": is_staff,
                                "confidence": 0.95,
                                "metadata": {
                                    "queue_depth": q_depth,
                                    "sku_zone": None,
                                    "session_seq": seq
                                }
                            }
                            emitter.emit(event)
                    else:
                        if visitor_billing.get(visitor_id):
                            visitor_billing[visitor_id] = False
                            
                            seq += 1
                            session_seqs[visitor_id] = seq
                            
                            event = {
                                "event_id": str(uuid.uuid4()),
                                "store_id": store_id,
                                "camera_id": camera_id,
                                "visitor_id": visitor_id,
                                "event_type": "ZONE_EXIT",
                                "timestamp": timestamp,
                                "zone_id": "BILLING_ZONE",
                                "dwell_ms": 10000,
                                "is_staff": is_staff,
                                "confidence": 0.95,
                                "metadata": {
                                    "queue_depth": None,
                                    "sku_zone": None,
                                    "session_seq": seq
                                }
                            }
                            emitter.emit(event)
                            
    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user.")
    finally:
        cap.release()
        emitter.flush()
        logger.info("Finished CV video processing.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apex Retail Store Intelligence CCTV Processing Pipeline")
    parser.add_argument("--mode", type=str, choices=["real", "simulation"], default="simulation",
                        help="Pipeline run mode (real CV processing or event replay simulation)")
    parser.add_argument("--video", type=str, default="", help="Path to raw CCTV mp4 video (for real mode)")
    parser.add_argument("--store-id", type=str, default="ST1076", help="Target Store ID")
    parser.add_argument("--camera-id", type=str, default="", help="Target Camera ID (e.g. CAM_ENTRY_01, CAM_FLOOR_01)")
    parser.add_argument("--events-file", type=str, default="sample_events.jsonl", help="JSONL events dataset path")
    parser.add_argument("--speed", type=float, default=1.0, help="Simulation speed-up factor (e.g. 5.0 for 5x fast-forward)")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="FastAPI Server base URL")
    
    args = parser.parse_args()
    
    if args.mode == "simulation":
        # Resolve absolute paths in workspace
        events_path = args.events_file
        if not os.path.isabs(events_path):
            # Try to resolve relative to workspace
            events_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), args.events_file)
        
        run_simulation(events_path, args.store_id, args.speed, args.api_url)
    else:
        if not args.video:
            logger.error("Error: --video path must be specified when using --mode real")
            sys.exit(1)
            
        camera_id = args.camera_id
        if not camera_id:
            filename = os.path.basename(args.video).lower()
            if "entry" in filename:
                camera_id = "CAM_ENTRY_01"
            elif "billing" in filename:
                camera_id = "CAM_BILLING_01"
            elif "zone" in filename or "floor" in filename:
                camera_id = "CAM_FLOOR_01"
            elif "cam 1" in filename:
                camera_id = "CAM_FLOOR_01"
            elif "cam 2" in filename:
                camera_id = "CAM_FLOOR_02"
            elif "cam 3" in filename:
                camera_id = "CAM_ENTRY_01"
            elif "cam 5" in filename:
                camera_id = "CAM_BILLING_01"
            else:
                camera_id = "CAM_ENTRY_01"
                
        run_real_cv(args.video, args.store_id, camera_id, args.api_url)
