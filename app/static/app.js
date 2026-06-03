// APEX STORE INTELLIGENCE DASHBOARD LOGIC

const API_BASE = ""; // Relative to server root
let activeStoreId = "ST1076";
let refreshInterval = null;
let lastKnownEventCount = 0;
let knownEventIds = new Set();

document.addEventListener("DOMContentLoaded", () => {
    setupStoreSelectors();
    fetchDashboardData();
    
    // Start Polling loop every 2.5 seconds
    refreshInterval = setInterval(fetchDashboardData, 2500);

    // Refresh Button Event
    document.getElementById("btn-refresh").addEventListener("click", () => {
        const btn = document.getElementById("btn-refresh");
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Refreshing...';
        fetchDashboardData().finally(() => {
            btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Refresh';
        });
    });
});

function setupStoreSelectors() {
    const items = document.querySelectorAll(".store-item");
    items.forEach(item => {
        item.addEventListener("click", () => {
            items.forEach(i => i.classList.remove("active"));
            item.classList.add("active");
            activeStoreId = item.getAttribute("data-store-id");
            
            // Update UI store header name
            const storeName = item.querySelector(".store-name").textContent;
            const storeSub = item.querySelector(".store-sub").textContent;
            document.getElementById("selected-store-title").textContent = `${storeName} ${storeSub}`;
            
            // Clear events cache for store switch
            knownEventIds.clear();
            const feedContainer = document.getElementById("event-feed-container");
            feedContainer.innerHTML = '<div class="no-events">Waiting for pipeline connection...</div>';
            
            // Fetch immediately
            fetchDashboardData();
        });
    });
}

async function fetchDashboardData() {
    try {
        await Promise.all([
            updateHealthStatus(),
            updateMetrics(),
            updateFunnel(),
            updateHeatmap(),
            updateAnomalies(),
            pollLiveEvents()
        ]);
    } catch (e) {
        console.error("Error refreshing dashboard data:", e);
    }
}

// 1. Health checks & feed lag
async function updateHealthStatus() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) throw new Error("API return error status");
        const data = await response.json();
        
        const textEl = document.getElementById("health-status-text");
        const iconEl = document.getElementById("health-icon");
        const lagEl = document.getElementById("health-lag");
        const stampEl = document.getElementById("health-timestamp");
        
        if (data.stale_feed_warning) {
            textEl.textContent = "FEED STALE";
            textEl.style.color = "var(--color-warning)";
            iconEl.className = "fa-solid fa-triangle-exclamation";
            iconEl.style.color = "var(--color-warning)";
        } else {
            textEl.textContent = "ONLINE";
            textEl.style.color = "var(--color-success)";
            iconEl.className = "fa-solid fa-circle-check";
            iconEl.style.color = "var(--color-success)";
        }
        
        lagEl.textContent = `${data.feed_lag_seconds}s`;
        
        // Show last event timestamp for this store
        const lastTs = data.last_event_timestamps[activeStoreId];
        if (lastTs) {
            const dateObj = new Date(lastTs);
            stampEl.textContent = `Last: ${dateObj.toLocaleTimeString()}`;
            
            // Set active date display header
            document.getElementById("current-active-date").textContent = `Active Date: ${dateObj.toLocaleDateString()}`;
        } else {
            stampEl.textContent = "Last: N/A";
            document.getElementById("current-active-date").textContent = "Active Date: No Data Ingested";
        }
    } catch (e) {
        document.getElementById("health-status-text").textContent = "OFFLINE";
        document.getElementById("health-status-text").style.color = "var(--color-danger)";
        document.getElementById("health-icon").className = "fa-solid fa-circle-xmark";
        document.getElementById("health-icon").style.color = "var(--color-danger)";
        document.getElementById("health-lag").textContent = "--";
    }
}

// 2. Summary stats cards
async function updateMetrics() {
    try {
        const response = await fetch(`${API_BASE}/stores/${activeStoreId}/metrics`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        
        document.getElementById("metric-visitors").textContent = data.unique_visitors;
        document.getElementById("metric-conversion").textContent = `${(data.conversion_rate * 100).toFixed(1)}%`;
        document.getElementById("metric-queue").textContent = data.queue_depth;
        document.getElementById("metric-abandonment").textContent = `${(data.abandonment_rate * 100).toFixed(1)}%`;
        
        // Dynamic color changes depending on warning status
        const queueTrend = document.getElementById("queue-trend");
        if (data.queue_depth >= 4.0) {
            queueTrend.className = "trend alert";
            queueTrend.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Heavy Line';
        } else if (data.queue_depth >= 2.0) {
            queueTrend.className = "trend alert";
            queueTrend.style.color = "var(--color-warning)";
            queueTrend.style.backgroundColor = "var(--color-warning-bg)";
            queueTrend.innerHTML = '<i class="fa-solid fa-user-clock"></i> Queue Building';
        } else {
            queueTrend.className = "trend positive";
            queueTrend.innerHTML = '<i class="fa-solid fa-circle-check"></i> Low Wait';
        }
        
        const abandonTrend = document.getElementById("abandon-trend");
        if (data.abandonment_rate > 0.25) {
            abandonTrend.className = "trend alert";
            abandonTrend.innerHTML = '<i class="fa-solid fa-arrow-trend-up"></i> High Abandon';
        } else {
            abandonTrend.className = "trend positive";
            abandonTrend.innerHTML = '<i class="fa-solid fa-thumbs-up"></i> Normal';
        }
    } catch (e) {
        console.error("Error updating metrics:", e);
    }
}

// 3. Conversion Funnel Chart
async function updateFunnel() {
    try {
        const response = await fetch(`${API_BASE}/stores/${activeStoreId}/funnel`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        
        const container = document.getElementById("funnel-chart");
        container.innerHTML = "";
        
        data.forEach(step => {
            const stepEl = document.createElement("div");
            stepEl.className = "funnel-step";
            
            // Calculate width percentage relative to max entry count (which is first step)
            const entryCount = data[0].count || 1;
            const widthPct = entryCount > 0 ? (step.count / entryCount) * 100 : 0;
            
            const dropClass = step.drop_off_pct > 0 ? "" : "zero";
            const dropText = step.drop_off_pct > 0 ? `-${step.drop_off_pct}%` : "--";
            
            stepEl.innerHTML = `
                <div class="funnel-label">${step.stage}</div>
                <div class="funnel-bar-wrapper">
                    <div class="funnel-bar" style="width: ${widthPct}%"></div>
                    <span class="funnel-val">${step.count}</span>
                </div>
                <div class="funnel-drop ${dropClass}">${dropText}</div>
            `;
            container.appendChild(stepEl);
        });
    } catch (e) {
        console.error("Error updating funnel:", e);
    }
}

// 4. Normalized Heatmap Grid
async function updateHeatmap() {
    try {
        const response = await fetch(`${API_BASE}/stores/${activeStoreId}/heatmap`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        
        // Remove loading spinner
        const storeMap = document.getElementById("store-heatmap");
        storeMap.innerHTML = "";
        
        // Add implicit entrance cell
        const entranceCell = document.createElement("div");
        entranceCell.className = "heatmap-cell entrance";
        entranceCell.innerHTML = `
            <span class="cell-name">MAIN ENTRANCE</span>
            <div class="cell-meta">
                <span class="cell-val"><i class="fa-solid fa-door-open"></i></span>
            </div>
        `;
        storeMap.appendChild(entranceCell);

        let dataConfidence = false;
        
        // Render database zones dynamically
        data.forEach(dbZone => {
            const cell = document.createElement("div");
            let glowClass = "active-glow";
            let score = dbZone.normalized_score;
            let visits = dbZone.visit_count;
            let avgDwellMin = (dbZone.avg_dwell_ms / 60000).toFixed(1);
            dataConfidence = dbZone.data_confidence;
            
            // Color level division
            if (score >= 80) glowClass += " lvl-hot";
            else if (score >= 50) glowClass += " lvl-high";
            else if (score >= 20) glowClass += " lvl-med";
            else glowClass += " lvl-low";
            
            let zoneClass = "skincare"; // default styling class
            const zid = dbZone.zone_id.toUpperCase();
            if (zid.includes("BILLING")) zoneClass = "billing";
            else if (zid.includes("Z02") || zid.includes("HAIR")) zoneClass = "haircare";
            else if (zid.includes("Z03") || zid.includes("COSMETICS")) zoneClass = "cosmetics";
            
            cell.className = `heatmap-cell ${zoneClass} ${glowClass}`;
            cell.innerHTML = `
                <span class="cell-name">${dbZone.zone_name || dbZone.zone_id}</span>
                <div class="cell-meta">
                    <div>
                        <span class="cell-visits" style="display:block; font-size:10px; color:var(--text-muted)">${visits} visits</span>
                        <span class="cell-dwell" style="font-size:10px; color:var(--text-muted)">${avgDwellMin}m avg</span>
                    </div>
                    <span class="cell-val">${score}%</span>
                </div>
            `;
            storeMap.appendChild(cell);
        });

        // Update confidence badge
        const badge = document.getElementById("confidence-badge");
        if (dataConfidence) {
            badge.textContent = "Confidence: HIGH";
            badge.className = "badge";
            badge.style.color = "var(--color-success)";
        } else {
            badge.textContent = "Confidence: LOW";
            badge.className = "badge";
            badge.style.color = "var(--color-warning)";
        }
    } catch (e) {
        console.error("Error updating heatmap:", e);
    }
}

// 5. Active Anomalies list
async function updateAnomalies() {
    try {
        const response = await fetch(`${API_BASE}/stores/${activeStoreId}/anomalies`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        
        const container = document.getElementById("anomalies-container");
        const countBadge = document.getElementById("anomaly-count");
        
        if (!data || data.length === 0) {
            countBadge.textContent = "0 Active";
            countBadge.className = "badge";
            countBadge.style.color = "var(--text-muted)";
            countBadge.style.backgroundColor = "rgba(255,255,255,0.05)";
            container.innerHTML = `
                <div class="no-anomalies">
                    <i class="fa-solid fa-circle-check"></i>
                    <p>System operating normally. No active anomalies detected.</p>
                </div>
            `;
            return;
        }
        
        countBadge.textContent = `${data.length} Active`;
        countBadge.className = "pulse-badge";
        
        container.innerHTML = "";
        data.forEach(anomaly => {
            const element = document.createElement("div");
            element.className = `anomaly-alert ${anomaly.severity}`;
            
            const timeObj = new Date(anomaly.timestamp);
            
            element.innerHTML = `
                <div class="anomaly-top">
                    <span class="anomaly-title"><i class="fa-solid fa-triangle-exclamation"></i> ${anomaly.anomaly_type}</span>
                    <span class="anomaly-time">${timeObj.toLocaleTimeString()}</span>
                </div>
                <div class="anomaly-desc">${anomaly.description}</div>
                <div class="anomaly-action">
                    <strong>Suggested Action:</strong> ${anomaly.suggested_action}
                </div>
            `;
            container.appendChild(element);
        });
    } catch (e) {
        console.error("Error updating anomalies:", e);
    }
}

// 6. Live event ticker feed (sliding logs)
async function pollLiveEvents() {
    try {
        // Query the database directly for the last 5 events
        // Let's create an endpoint or just fetch the raw database state.
        // Wait, since we don't have a direct endpoint for listing raw events in main.py,
        // is there a clean way to fetch the latest events?
        // Wait, in main.py, did we define a GET /events or similar? No, only POST /events/ingest.
        // But wait! We can add a GET /stores/{id}/events endpoint in main.py or we can mock/simulate it by checking if we need to list events.
        // Let's modify app/main.py to expose a quick GET /stores/{id}/events endpoint that returns the last 10 received events!
        // That is extremely useful for a live feed. Let's do that in a moment.
        // Meanwhile, if the endpoint is not available, we can mock it on frontend or fetch it.
        // Let's first make a fetch to the new endpoint `GET /stores/{id}/events` that we will add.
        const response = await fetch(`${API_BASE}/stores/${activeStoreId}/events?limit=8`);
        if (!response.ok) return;
        const data = await response.json();
        
        const container = document.getElementById("event-feed-container");
        if (!data || data.length === 0) {
            return;
        }

        // Filter and display new events
        const hasNew = data.some(evt => !knownEventIds.has(evt.event_id));
        if (!hasNew) return;

        container.innerHTML = "";
        data.forEach(evt => {
            knownEventIds.add(evt.event_id);
            const dateObj = new Date(evt.timestamp);
            
            const element = document.createElement("div");
            element.className = `feed-item ${evt.event_type}`;
            
            let displayMsg = `Visitor <strong>${evt.visitor_id}</strong>: `;
            if (evt.event_type === "ENTRY") displayMsg += "Entered the store";
            else if (evt.event_type === "EXIT") displayMsg += "Exited the store";
            else if (evt.event_type === "ZONE_ENTER") displayMsg += `Entered zone <strong>${evt.zone_id}</strong>`;
            else if (evt.event_type === "ZONE_EXIT") displayMsg += `Left zone <strong>${evt.zone_id}</strong>`;
            else if (evt.event_type === "ZONE_DWELL") displayMsg += `Dwelled in <strong>${evt.zone_id}</strong> (${(evt.dwell_ms/1000).toFixed(0)}s)`;
            else if (evt.event_type === "BILLING_QUEUE_JOIN") displayMsg += `Joined billing queue (Q Depth: ${evt.metadata?.queue_depth || 1})`;
            else if (evt.event_type === "BILLING_QUEUE_ABANDON") displayMsg += "Left billing queue (Abandoned)";
            else if (evt.event_type === "REENTRY") displayMsg += "Re-entered the store (Returning Visitor)";

            element.innerHTML = `
                <div class="feed-left">
                    <span class="feed-indicator"></span>
                    <span class="feed-text">${displayMsg}</span>
                </div>
                <div class="feed-right">${dateObj.toLocaleTimeString()}</div>
            `;
            container.appendChild(element);
        });

        // Limit the cache size
        if (knownEventIds.size > 200) {
            knownEventIds.clear();
        }
    } catch (e) {
        // Silent error
    }
}
