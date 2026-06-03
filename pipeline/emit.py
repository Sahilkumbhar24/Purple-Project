# PROMPT: Build event emitter script to post events to the FastAPI server
# CHANGES MADE: Added batching buffer and robust connection error logging

import requests
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EventEmitter")

INGEST_URL = "http://localhost:8000/events/ingest"

class EventEmitter:
    def __init__(self, ingest_url=INGEST_URL, batch_size=20):
        self.ingest_url = ingest_url
        self.batch_size = batch_size
        self.buffer = []

    def emit(self, event):
        """
        Add event to buffer and send if batch size reached.
        """
        self.buffer.append(event)
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """
        Send all events in buffer to API.
        """
        if not self.buffer:
            return True
            
        payload = self.buffer.copy()
        self.buffer.clear()
        
        try:
            response = requests.post(self.ingest_url, json=payload, timeout=5)
            if response.status_code in [200, 201]:
                logger.info(f"Successfully ingested batch of {len(payload)} events")
                return True
            else:
                logger.error(f"Ingest returned status {response.status_code}: {response.text}")
                # Re-queue on failure so we don't lose data
                self.buffer.extend(payload)
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to ingestion server: {e}")
            # Re-queue on failure
            self.buffer.extend(payload)
            return False

# Single global helper function to post individual immediate events
def post_event(event_dict, url=INGEST_URL):
    try:
        response = requests.post(url, json=[event_dict], timeout=5)
        return response.status_code in [200, 201]
    except Exception as e:
        logger.error(f"Error posting single event: {e}")
        return False
