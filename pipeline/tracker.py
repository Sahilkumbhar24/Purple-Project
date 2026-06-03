# PROMPT: Build tracker class with centroid tracking, threshold crossing logic, and Re-ID fallback
# CHANGES MADE: Added threshold crossing direction and OSNet-like distance matching fallback

import math
import uuid

class CentroidTracker:
    def __init__(self, max_disappeared=15, min_distance=100):
        self.next_visitor_num = 1
        self.objects = {}         # visitor_id -> (x, y) centroid
        self.disappeared = {}     # visitor_id -> frame count missing
        self.max_disappeared = max_disappeared
        self.min_distance = min_distance
        
        # History of centroids to track direction: visitor_id -> list of centroids
        self.history = {}
        
        # Bounding box history: visitor_id -> (x1, y1, x2, y2)
        self.rectangles = {}
        
        # Re-ID signature database (simulated feature vectors): visitor_id -> feature_vector
        self.signatures = {}

    def register(self, centroid, rect=None, feature_vector=None):
        visitor_id = f"VIS_{self.next_visitor_num:03d}"
        self.next_visitor_num += 1
        self.objects[visitor_id] = centroid
        self.disappeared[visitor_id] = 0
        self.history[visitor_id] = [centroid]
        if rect is not None:
            self.rectangles[visitor_id] = rect
        if feature_vector is not None:
            self.signatures[visitor_id] = feature_vector
        return visitor_id

    def deregister(self, visitor_id):
        del self.objects[visitor_id]
        del self.disappeared[visitor_id]
        self.rectangles.pop(visitor_id, None)
        # Keep history and signature for Re-ID/Re-entry mapping later
        # self.history.pop(visitor_id, None)

    def get_reid_match(self, feature_vector, threshold=0.6):
        """
        Compare current feature vector with signatures of deregistered visitors.
        Returns matching visitor_id or None.
        """
        if feature_vector is None or not self.signatures:
            return None
            
        best_match = None
        best_dist = float('inf')
        
        # Cosine/Euclidean distance simulation
        for vid, sig in self.signatures.items():
            # Calculate simple Euclidean distance between normalized feature vectors
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(feature_vector, sig)))
            if dist < best_dist and dist < threshold:
                best_dist = dist
                best_match = vid
                
        return best_match

    def update(self, rects, features=None):
        """
        rects: list of bounding boxes (x1, y1, x2, y2)
        features: list of Re-ID feature vectors per box (optional)
        """
        if len(rects) == 0:
            for visitor_id in list(self.disappeared.keys()):
                self.disappeared[visitor_id] += 1
                if self.disappeared[visitor_id] > self.max_disappeared:
                    self.deregister(visitor_id)
            return self.objects

        input_centroids = []
        for (x1, y1, x2, y2) in rects:
            cx = int((x1 + x2) / 2.0)
            cy = int((y1 + y2) / 2.0)
            input_centroids.append((cx, cy))

        # If currently tracking nothing, register all input centroids
        if len(self.objects) == 0:
            for i, centroid in enumerate(input_centroids):
                feat = features[i] if (features is not None and i < len(features)) else None
                # Check Re-ID matching first
                matched_id = self.get_reid_match(feat)
                if matched_id:
                    self.objects[matched_id] = centroid
                    self.disappeared[matched_id] = 0
                    self.rectangles[matched_id] = rects[i]
                else:
                    self.register(centroid, rects[i], feat)
        else:
            object_ids = list(self.objects.keys())
            object_centroids = list(self.objects.values())

            # Distance matrix computation
            distances = []
            for oc in object_centroids:
                row = []
                for ic in input_centroids:
                    dist = math.sqrt((oc[0] - ic[0])**2 + (oc[1] - ic[1])**2)
                    row.append(dist)
                distances.append(row)

            # Match inputs to existing targets
            # (Simple greedy matching algorithm)
            used_rows = set()
            used_cols = set()

            # Find matching pairs
            for _ in range(min(len(object_ids), len(input_centroids))):
                min_val = float('inf')
                min_r, min_c = -1, -1
                for r in range(len(object_ids)):
                    if r in used_rows:
                        continue
                    for c in range(len(input_centroids)):
                        if c in used_cols:
                            continue
                        if distances[r][c] < min_val:
                            min_val = distances[r][c]
                            min_r, min_c = r, c

                if min_val < self.min_distance:
                    visitor_id = object_ids[min_r]
                    self.objects[visitor_id] = input_centroids[min_c]
                    self.disappeared[visitor_id] = 0
                    self.history[visitor_id].append(input_centroids[min_c])
                    self.rectangles[visitor_id] = rects[min_c]
                    used_rows.add(min_r)
                    used_cols.add(min_c)

            # Handle disappeared items
            for r in range(len(object_ids)):
                if r not in used_rows:
                    visitor_id = object_ids[r]
                    self.disappeared[visitor_id] += 1
                    if self.disappeared[visitor_id] > self.max_disappeared:
                        self.deregister(visitor_id)

            # Handle new items (register or match with Re-ID)
            for c in range(len(input_centroids)):
                if c not in used_cols:
                    feat = features[c] if (features is not None and c < len(features)) else None
                    matched_id = self.get_reid_match(feat)
                    if matched_id and matched_id not in self.objects:
                        self.objects[matched_id] = input_centroids[c]
                        self.disappeared[matched_id] = 0
                        self.rectangles[matched_id] = rects[c]
                    else:
                        self.register(input_centroids[c], rects[c], feat)

        return self.objects

    def check_crossing(self, visitor_id, threshold_y=540, direction_up=True):
        """
        Check if user crossed threshold_y in frame using hysteresis state logic.
        D = 25 pixel buffer is used to prevent boundary jitter.
        """
        pts = self.history.get(visitor_id, [])
        if len(pts) < 1:
            return None
            
        p_curr = pts[-1]
        y_curr = p_curr[1]
        
        # Hysteresis buffer width
        D = 25
        
        # Initialize state dict if not present
        if not hasattr(self, 'visitor_states'):
            self.visitor_states = {}
            
        # Determine current position state relative to the line (plus buffer)
        curr_pos_state = None
        if y_curr > threshold_y + D:
            curr_pos_state = "OUTSIDE"
        elif y_curr < threshold_y - D:
            curr_pos_state = "INSIDE"
            
        # If we don't have a record of this visitor's previous state, initialize it
        if visitor_id not in self.visitor_states:
            self.visitor_states[visitor_id] = curr_pos_state if curr_pos_state else "OUTSIDE"
            return None
            
        prev_state = self.visitor_states[visitor_id]
        
        # If they transition from OUTSIDE to INSIDE, or INSIDE to OUTSIDE, trigger crossing
        if curr_pos_state and curr_pos_state != prev_state:
            self.visitor_states[visitor_id] = curr_pos_state
            if prev_state == "OUTSIDE" and curr_pos_state == "INSIDE":
                return "ENTRY" if direction_up else "EXIT"
            elif prev_state == "INSIDE" and curr_pos_state == "OUTSIDE":
                return "EXIT" if direction_up else "ENTRY"
                
        return None
