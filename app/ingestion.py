# PROMPT: Implement de-duplicating event batch ingestion service with partial success handler
# CHANGES MADE: Enforced robust validation logic loop, error logging, and JSON serialization format

import logging
from typing import List, Dict, Any
from app.models import EventModel
from app.database import save_event

logger = logging.getLogger("IngestionService")

def ingest_events_batch(raw_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validates, deduplicates, and ingests a batch of event payloads.
    Enforces partial success: returns list of validation errors while saving correct events.
    """
    logger.info(f"Received batch of {len(raw_events)} events for ingestion.")
    
    success_count = 0
    duplicate_count = 0
    errors = []

    for index, event_data in enumerate(raw_events):
        event_id = event_data.get("event_id", f"UNKNOWN_INDEX_{index}")
        
        try:
            # 1. Pydantic schema validation
            validated_event = EventModel(**event_data)
            
            # 2. Database save with idempotency handling
            is_inserted = save_event(validated_event.dict())
            
            if is_inserted:
                success_count += 1
            else:
                duplicate_count += 1
                
        except ValueError as e:
            logger.warning(f"Validation error at batch index {index} (ID: {event_id}): {e}")
            errors.append({
                "index": index,
                "event_id": event_id,
                "reason": str(e)
            })
        except Exception as e:
            logger.error(f"System ingestion failure at batch index {index}: {e}")
            errors.append({
                "index": index,
                "event_id": event_id,
                "reason": f"Internal system database error: {e}"
            })

    response = {
        "status": "partial_success" if errors and success_count > 0 else ("success" if success_count > 0 or not errors else "failed"),
        "ingested": success_count,
        "duplicates_ignored": duplicate_count,
        "failed": len(errors),
        "errors": errors
    }
    
    logger.info(f"Ingest complete. Ingested: {success_count}, Ignored Duplicates: {duplicate_count}, Failed: {len(errors)}")
    return response
