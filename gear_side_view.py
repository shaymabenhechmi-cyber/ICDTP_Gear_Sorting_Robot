"""
gear_side_view.py  — Side-view gear inspection
───────────────────────────────────────────────
Measures: face height, helix angle
Detects:  YOLO healthy / damaged class

Controls
  q   quit
  r   reset all state
"""

import cv2
import numpy as np
import math
from collections import deque

from gear_utils import (
    # scale
    update_scale, draw_aruco, get_scale,
    # yolo
    load_yolo, run_yolo, draw_yolo_boxes, best_gear_box,
    # ui
    build_sidebar, attach_sidebar,
    # math
    exp_smooth,
)

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────
MODEL_PATH           = "best_yolo_gear_v3.pt"
YOLO_CONF            = 0.35
YOLO_EVERY_N         = 4
ALPHA                = 0.15
CONFIRMATION_FRAMES  = 10

HEALTHY_CLASS_NAME   = "healthy_gear"
DAMAGED_CLASS_NAME   = "damaged_gear"

EXPECTED_HEIGHT_MM   = 20.0
HEIGHT_TOLERANCE_MM  = 5.0
EXPECTED_HELIX_ANGLE = 15.0
HELIX_TOLERANCE_DEG  = 7.0

# ─────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────
Frames              = 0
smoothed_px_mm      = None
smoothed_height_mm  = None
smoothed_helix_deg  = None
height_counter      = 0
helix_counter       = 0
edge_profile_acc    = deque(maxlen=20)
yolo_results_cache  = []
gear_ok_detected    = False

yolo_model, YOLO_AVAILABLE = load_yolo(MODEL_PATH)


# ─────────────────────────────────────────────────────────────────
# SIDE-VIEW SPECIFIC HELPERS
# ─────────────────────────────────────────────────────────────────

def measure_height_from_box(x1, y1, x2, y2, px_mm):
    """Convert YOLO box dimensions from pixels to mm."""
    height_mm = (y2 - y1) / px_mm
    width_mm  = (x2 - x1) / px_mm
    return height_mm, width_mm


def estimate_helix_angle(gray_full, x1, y1, x2, y2, debug_frame=None):
    """
    Crop the gear face ROI from the YOLO box, then estimate
    the helix angle via HoughLinesP on tooth edges.
    """
    fh, fw = gray_full.shape
    rx1, ry1 = max(0, x1), max(0, y1)
    rx2, ry2 = min(fw, x2), min(fh, y2)

    roi = gray_full[ry1:ry2, rx1:rx2]
    if roi.size == 0:
        return None

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    roi   = clahe.apply(roi)
    blur  = cv2.GaussianBlur(roi, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 100)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges  = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    h_roi, w_roi = roi.shape
    min_len = max(15, w_roi // 8)

    lines = cv2.HoughLinesP(edges, 1, np.deg2rad(0.5),
                            threshold=20,
                            minLineLength=min_len,
                            maxLineGap=10)
    if lines is None:
        return None

    angles = []
    for line in lines:
        lx1, ly1, lx2, ly2 = line[0]
        dx, dy = lx2 - lx1, ly2 - ly1
        if math.hypot(dx, dy) < min_len:
            continue
        angle = math.degrees(math.atan2(abs(dx), abs(dy)))
        if 3 < angle < 65:
            angles.append(angle)
            if debug_frame is not None:
                cv2.line(debug_frame,
                         (lx1 + rx1, ly1 + ry1),
                         (lx2 + rx1, ly2 + ry1),
                         (255, 200, 0), 1)

    return float(np.median(angles)) if angles else None


# ─────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────
cap = cv2.VideoCapture(0)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    Frames += 1

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # ── Scale ─────────────────────────────────────────────
    smoothed_px_mm, corners, ids = update_scale(gray, smoothed_px_mm)
    draw_aruco(frame, corners, ids)
    px_mm = get_scale(smoothed_px_mm)

    # ── YOLO ──────────────────────────────────────────────
    step1_status = "SCANNING..."
    if YOLO_AVAILABLE:
        if Frames % YOLO_EVERY_N == 0:
            yolo_results_cache = run_yolo(yolo_model, frame, YOLO_CONF)
        draw_yolo_boxes(frame, yolo_results_cache)

        gear_ok_detected  = any(d[6].lower() == HEALTHY_CLASS_NAME.lower()
                                for d in yolo_results_cache)
        gear_bad_detected = any(d[6].lower() == DAMAGED_CLASS_NAME.lower()
                                for d in yolo_results_cache)

        if gear_ok_detected:
            step1_status = "PASSED"
        elif gear_bad_detected:
            step1_status = "DEFECT DETECTED"

    # ── Measurement guided by YOLO box ────────────────────
    gear_box = best_gear_box(yolo_results_cache, HEALTHY_CLASS_NAME, DAMAGED_CLASS_NAME)

    if gear_box is not None:
        bx1, by1, bx2, by2 = gear_box[0], gear_box[1], gear_box[2], gear_box[3]
        mid_y = (by1 + by2) // 2

        # Height
        height_mm, _ = measure_height_from_box(bx1, by1, bx2, by2, px_mm)
        height_counter += 1
        if height_counter > CONFIRMATION_FRAMES:
            smoothed_height_mm = exp_smooth(height_mm, smoothed_height_mm, ALPHA)

        # Height bracket on left side of box
        cv2.line(frame, (bx1 - 18, by1), (bx1 - 18, by2), (255, 80, 0), 2)
        cv2.line(frame, (bx1 - 26, by1), (bx1 - 8, by1), (255, 80, 0), 2)
        cv2.line(frame, (bx1 - 26, by2), (bx1 - 8, by2), (255, 80, 0), 2)
        h_label = (f"H:{smoothed_height_mm:.1f}mm"
                   if smoothed_height_mm else f"H~{height_mm:.1f}mm")
        cv2.putText(frame, h_label,
                    (max(0, bx1 - 110), mid_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 80, 0), 2)

        # Helix angle
        helix_now = estimate_helix_angle(gray, bx1, by1, bx2, by2,
                                         debug_frame=frame)
        if helix_now is not None:
            edge_profile_acc.append(helix_now)

        if len(edge_profile_acc) >= 5:
            stable_helix = float(np.median(edge_profile_acc))
            helix_counter += 1
            if helix_counter > CONFIRMATION_FRAMES:
                smoothed_helix_deg = exp_smooth(
                    stable_helix, smoothed_helix_deg, ALPHA)

        if smoothed_helix_deg is not None:
            cv2.putText(frame,
                        f"Helix: {smoothed_helix_deg:.1f} deg",
                        (bx1, max(20, by1 - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 180), 2)

            # Arc indicator right of box
            arc_cx = min(frame.shape[1] - 60, bx2 + 60)
            arc_cy = mid_y
            arc_r  = 40
            cv2.ellipse(frame, (arc_cx, arc_cy), (arc_r, arc_r),
                        0, 90 - smoothed_helix_deg, 90, (0, 255, 180), 2)
            cv2.line(frame,
                     (arc_cx, arc_cy - arc_r - 5),
                     (arc_cx, arc_cy + arc_r + 5),
                     (120, 120, 120), 1)
            ang_rad = math.radians(90 - smoothed_helix_deg)
            cv2.line(frame,
                     (arc_cx, arc_cy),
                     (arc_cx + int(arc_r * math.cos(ang_rad)),
                      arc_cy - int(arc_r * math.sin(ang_rad))),
                     (0, 255, 180), 2)
    else:
        height_counter = max(0, height_counter - 1)
        helix_counter  = max(0, helix_counter  - 1)

    # ── Verdict logic ──────────────────────────────────────
    height_ok = (smoothed_height_mm is not None and
                 abs(smoothed_height_mm - EXPECTED_HEIGHT_MM) <= HEIGHT_TOLERANCE_MM)
    helix_ok  = (smoothed_helix_deg is not None and
                 abs(smoothed_helix_deg - EXPECTED_HELIX_ANGLE) <= HELIX_TOLERANCE_DEG)

    step2_status = "WAITING FOR GEAR"
    if height_ok and helix_ok:
        step2_status = "DIMS OK"
    elif smoothed_height_mm is not None or smoothed_helix_deg is not None:
        step2_status = "CHECKING DIMS"

    final_ok = (gear_ok_detected and height_ok and helix_ok
                if YOLO_AVAILABLE
                else (height_ok and helix_ok))
    if not (height_ok or helix_ok):
        final_ok = None   # still pending

    # ── Scale label ────────────────────────────────────────
    if smoothed_px_mm:
        scale_txt = f"ArUco  {smoothed_px_mm:.3f} px/mm"
    else:
        from gear_utils import FALLBACK_PX_PER_MM
        scale_txt = f"Fallback  {FALLBACK_PX_PER_MM} px/mm"

    # ── Build sidebar ──────────────────────────────────────
    h_txt  = f"{smoothed_height_mm:.1f} mm" if smoothed_height_mm else "---"
    ha_txt = f"{smoothed_helix_deg:.1f} °"  if smoothed_helix_deg  else "---"

    rows = [
        {"label": "STEP 1 · YOLO",
         "items": [("Status", step1_status)]},
        {"label": "STEP 2 · DIMENSIONS",
         "items": [
             ("Height", h_txt),
             ("Helix",  ha_txt),
         ]},
    ]

    sidebar = build_sidebar(
        height    = frame.shape[0],
        title     = "SIDE VIEW",
        rows      = rows,
        final_ok  = final_ok if (height_ok or helix_ok) else None,
        scale_text= scale_txt,
    )

    display = attach_sidebar(frame, sidebar)
    cv2.imshow("Gear Side-View Inspection", display)

    # ── Key handling ───────────────────────────────────────
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        smoothed_height_mm = None
        smoothed_helix_deg = None
        height_counter     = 0
        helix_counter      = 0
        edge_profile_acc.clear()
        yolo_results_cache = []
        gear_ok_detected   = False
        print("[INFO] State reset.")

cap.release()
cv2.destroyAllWindows()
