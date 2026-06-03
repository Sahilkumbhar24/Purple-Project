from pydantic import BaseModel, Field, model_validator
from typing import Optional, Union, Literal, Dict, Any
from datetime import datetime

class EventMetadata(BaseModel):
    queue_depth: Optional[int] = Field(None, description="Current queue depth, required for BILLING_QUEUE_JOIN")
    sku_zone: Optional[str] = Field(None, description="Sub-zone name representing SKU category")
    session_seq: Optional[int] = Field(1, description="1-indexed sequence order of this event in the visitor session")

class EventModel(BaseModel):
    event_id: Optional[str] = None
    store_id: Optional[str] = None
    camera_id: Optional[str] = None
    visitor_id: Optional[str] = None
    event_type: str = Field(..., description="Behavioral event category classification")
    timestamp: Optional[str] = None
    zone_id: Optional[str] = None
    dwell_ms: Optional[int] = 0
    is_staff: Optional[bool] = False
    confidence: Optional[float] = 1.0
    metadata: Optional[EventMetadata] = None

    # Demographics & groups
    gender: Optional[str] = None
    gender_pred: Optional[str] = None
    age: Optional[int] = None
    age_pred: Optional[int] = None
    age_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_size: Optional[int] = None
    is_face_hidden: Optional[bool] = False
    zone_type: Optional[str] = None
    is_revenue_zone: Optional[str] = None

    # Queue specific
    queue_join_ts: Optional[str] = None
    queue_served_ts: Optional[str] = None
    queue_exit_ts: Optional[str] = None
    wait_seconds: Optional[int] = None
    queue_position_at_join: Optional[int] = None
    abandoned: Optional[bool] = False

    @model_validator(mode='before')
    @classmethod
    def pre_validate(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize event_type
            etype = data.get("event_type")
            if etype:
                mapping = {
                    "entry": "ENTRY",
                    "exit": "EXIT",
                    "zone_entered": "ZONE_ENTER",
                    "zone_exited": "ZONE_EXIT",
                    "queue_completed": "BILLING_QUEUE_JOIN",
                    "queue_abandoned": "BILLING_QUEUE_ABANDON"
                }
                if etype in mapping:
                    data["event_type"] = mapping[etype]
                else:
                    data["event_type"] = etype.upper()

            # Map queue_event_id to event_id
            if not data.get("event_id") and data.get("queue_event_id"):
                data["event_id"] = data["queue_event_id"]

            # Map store_code to store_id
            if not data.get("store_id") and data.get("store_code"):
                data["store_id"] = data["store_code"]

            # Map demographics pred
            if not data.get("gender_pred") and data.get("gender"):
                data["gender_pred"] = data["gender"]
            if not data.get("gender") and data.get("gender_pred"):
                data["gender"] = data["gender_pred"]
            if not data.get("age_pred") and data.get("age"):
                data["age_pred"] = data["age"]
            if not data.get("age") and data.get("age_pred"):
                data["age"] = data["age_pred"]

            # Map timestamp
            if not data.get("timestamp"):
                data["timestamp"] = data.get("event_timestamp") or data.get("event_time") or data.get("queue_exit_ts") or data.get("queue_join_ts")

            # Map visitor_id
            if not data.get("visitor_id"):
                data["visitor_id"] = data.get("id_token") or (f"TRACK_{data.get('track_id')}" if data.get("track_id") is not None else "UNKNOWN")

            # Ensure metadata exists
            if not data.get("metadata"):
                data["metadata"] = {
                    "queue_depth": data.get("queue_position_at_join") or data.get("queue_depth"),
                    "sku_zone": data.get("sku_zone") or data.get("zone_type"),
                    "session_seq": data.get("session_seq") or 1
                }
        return data

    @model_validator(mode='after')
    def validate_event_logic(self) -> 'EventModel':
        valid_types = {
            "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", 
            "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY"
        }
        if self.event_type not in valid_types:
            raise ValueError(f"event_type must be one of {valid_types}")
            
        # 1. ENTRY/EXIT should not have a zone_id
        if self.event_type in ["ENTRY", "EXIT"] and self.zone_id is not None:
            raise ValueError(f"zone_id must be null for {self.event_type} event type")
            
        # 2. ZONE_* and BILLING_* should have a zone_id
        if self.event_type in ["ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"] and self.zone_id is None:
            raise ValueError(f"zone_id is required for {self.event_type} event type")
            
        # 3. BILLING_QUEUE_JOIN must have a valid queue_depth
        if self.event_type == "BILLING_QUEUE_JOIN" and (self.metadata is None or self.metadata.queue_depth is None):
            raise ValueError("queue_depth is required in metadata for BILLING_QUEUE_JOIN events")

        # 4. Check timestamp format
        if self.timestamp:
            try:
                ts_str = self.timestamp.replace("Z", "+00:00")
                datetime.fromisoformat(ts_str)
            except Exception:
                raise ValueError("timestamp must be a valid ISO-8601 string")
        else:
            raise ValueError("timestamp is required")
            
        return self
