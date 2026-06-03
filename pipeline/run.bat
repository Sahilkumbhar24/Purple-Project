@echo off
echo Starting Store Intelligence Event Streaming Pipeline...
echo Replaying sample events into local FastAPI server at http://localhost:8000 (Speed: 5x)

python "%~dp0detect.py" --mode simulation --events-file "%~dp0..\sample_events.jsonl" --speed 5.0 --api-url "http://localhost:8000"
