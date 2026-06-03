# Store Intelligence System — Apex Retail

An AI-powered Store Intelligence System that processes raw CCTV footage, tracks customer journeys, calculates real-time conversion rates, detects operational anomalies, and serves a live dashboard interface.

---

## 1. Project Features

* **Real-time Event Ingestion & Deduplication**: Batch-validated `/events/ingest` endpoint using FastAPI + Pydantic.
* **Conversion Rate POS Correlation**: Correlates shelf dwell times and billing queues with POS sales timestamps using a 5-minute rolling window.
* **Anomaly Detection Engine**: Real-time alerting for queue spikes, conversion rate drops, and dead product zones.
* **Premium Web Dashboard**: A glassmorphic dark-theme Web UI updating in real-time as events are streamed.
* **Dual-mode Detection Pipeline**: Supports real YOLOv8/OpenCV video clip processing and simulated real-time event playback.

---

## 2. Quick Start (Run in 3 Commands)

Follow these steps to run the complete containerized system:

### Step 1: Start the API & Dashboard
Build and spin up the FastAPI server and database container:
```bash
docker compose up --build
```
The server will start at `http://localhost:8000`. You can access the live Web Dashboard at `http://localhost:8000/`.

### Step 2: Start the Event Stream (Pipeline Simulator)
In a new terminal window, start the simulation pipeline to stream events into the API:
```bash
# On Linux/macOS:
bash pipeline/run.sh

# On Windows:
pipeline\run.bat
```
*Note: This streams the 200 events from `sample_events.jsonl` in simulated real-time (at 5x speed) into the API.*

### Step 3: Run the Test Suite
To execute the automated test cases and verify schema validation, metrics logic, and anomalies detection:
```bash
# Inside the Docker container:
docker compose exec api pytest

# Or locally (if pytest is installed):
pytest
```

---

## 3. API Endpoints Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Check service health, stale feed status, and active lag. |
| `/events/ingest` | POST | Ingest a batch of events (up to 500 events). Idempotent. |
| `/stores/{id}/metrics` | GET | Fetch visitors count, conversion rate, avg queue depth, etc. |
| `/stores/{id}/funnel` | GET | Fetch session-based funnel progression counts & drop-offs. |
| `/stores/{id}/heatmap` | GET | Fetch zone-wise normalized visit scores & average dwells. |
| `/stores/{id}/anomalies` | GET | Fetch active store operational alerts (CRITICAL / WARN). |
| `/stores/{id}/events` | GET | Fetch the last 8 ingested events (used by live ticker). |

---

## 4. Directory Structure

```
/store-intelligence/
├── pipeline/
│   ├── detect.py          # YOLOv8 / Simulator processing loop
│   ├── tracker.py         # Centroid tracking & Re-ID logic
│   ├── emit.py            # Event batch buffer & POST client
│   ├── run.sh             # Linux run shortcut script
│   └── run.bat            # Windows run shortcut script
├── app/
│   ├── static/            # Dashboard Web UI (index.html, app.css, app.js)
│   ├── main.py            # FastAPI entrypoint & router
│   ├── models.py          # Pydantic schemas & custom validations
│   ├── ingestion.py       # Batch validation & saving logic
│   ├── metrics.py         # Analytical computations
│   ├── funnel.py          # Session-based funnel logic
│   ├── anomalies.py       # Queue/conversion/dead-zone checkers
│   ├── health.py          # Lag & connection checker
│   └── database.py        # SQLite setup & CSV/JSON loader
├── tests/
│   ├── test_pipeline.py   # Schema validation test suite
│   ├── test_metrics.py    # Metric & POS correlation test suite
│   └── test_anomalies.py  # Alerting engine test suite
├── docs/
│   ├── DESIGN.md          # System Architecture & AI decisions
│   └── CHOICES.md         # ADRs (Model, Schema, API choices)
├── docker-compose.yml     # Container services configuration
├── Dockerfile             # Multi-stage python runner
├── requirements.txt       # Python dependencies
└── store_layout.json      # Store configuration configuration
```
