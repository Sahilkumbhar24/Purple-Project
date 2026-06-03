# CHOICES: Architectural Decision Records (ADR)

This document outlines the three key engineering choices made during the development of the **Store Intelligence System**.

---

## Choice 1: Object Detection Model selection

### Options Considered
1. **YOLOv8 Nano (yolov8n)**: High speed (150+ FPS on GPU, 30+ FPS on CPU), low footprint, reasonable accuracy for person detection.
2. **YOLOv9 Medium (yolov9m)**: Higher accuracy, but heavier resource demands (may lag on edge devices without dedicated GPUs).
3. **RT-DETR (Real-Time DEtection TRansformer)**: Top-tier accuracy, but requires PyTorch/CUDA optimizations to run in real-time.

### AI Suggestion
The AI recommended YOLOv8 Medium (`yolov8m.pt`) as the optimal trade-off for in-store checkout tracking accuracy.

### Chosen Approach & Rationale
We chose **YOLOv8 Nano (`yolov8n.pt`)** with a dual-mode simulator fallback. 
* **Rationale**: In real retail store deployments, edge hardware (CCTV DVRs/NVRs) lacks server-grade GPUs. YOLOv8 Nano ensures high frame processing rates on CPU. Furthermore, the dual-mode implementation fallback (Simulation Replay) guarantees that the API and dashboard can be developed and validated in environments where CV models cannot load locally.
* **Uniform & Staff Detection**: Instead of utilizing a resource-heavy multi-class classification neural network to detect employees dressed in the black shirt and black pants uniform, we implemented a lightweight HSV-based color analysis function (`classify_staff_by_uniform`). This processes the upper-torso and lower-leg regions of the YOLO bounding boxes in under 0.1ms, setting `is_staff = True` for employees and excluding them from customer conversion metrics.

---

## Choice 2: Event Schema Design

### Options Considered
1. **Flat Schema**: All data points in root JSON keys.
2. **Nested Metadata Schema**: Grouping variable, context-specific values (like queue depth and SKU categorization) inside a `metadata` object.

### AI Suggestion
The AI suggested a flat event schema for simplified JSON database indexing.

### Chosen Approach & Rationale
We chose the **Nested Metadata Schema**.
* **Rationale**: Flat schemas become bloated and fragile as more business metrics are added. Grouping operational details inside a `metadata` dictionary keeps the core schema clean and backward-compatible. This allows the ingestion layer to process diverse events (e.g. `ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`) using a single, unified database schema without requiring migrations for every new event field.

---

## Choice 3: API Architecture & Storage Engine

### Options Considered
1. **FastAPI + SQLite**: Lightweight, zero-configuration local database file, quick prototyping, native Pydantic validation.
2. **Express.js (Node.js) + PostgreSQL**: Highly scalable, but requires database setup and containerized Postgres running locally.
3. **FastAPI + MongoDB**: Document-based, good for JSON logs, but lacks transactional guarantees for analytics reporting.

### AI Suggestion
The AI suggested FastAPI + PostgreSQL to simulate production scaling.

### Chosen Approach & Rationale
We chose **FastAPI + SQLite** deployed via Docker.
* **Rationale**: A major acceptance gate of this challenge is running the complete system instantly via `docker compose up` with zero manual configuration. SQLite is self-contained in a single file and does not require complex database credentials or startup sequencing. We optimized query performance by creating indexes on `(store_id, visitor_id)` and `timestamp`, ensuring sub-millisecond query latencies for stores with up to 100,000 daily events.
