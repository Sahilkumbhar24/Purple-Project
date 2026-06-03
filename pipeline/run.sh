#!/bin/bash
# One command to run the simulation pipeline

# Resolve script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "Starting Store Intelligence Event Streaming Pipeline..."
echo "Replaying sample events into local FastAPI server at http://localhost:8000"

python3 "$DIR/detect.py" --mode simulation --events-file "$DIR/../sample_events.jsonl" --speed 5.0 --api-url "http://localhost:8000"
