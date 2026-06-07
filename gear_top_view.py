"""
gear_top_view.py  — Top-view gear inspection
─────────────────────────────────────────────
Measures: outer diameter, inner diameter, tooth count
Detects:  YOLO defects

Controls
  q   quit
  r   reset all state
"""

import cv2
import numpy as np
from scipy.signal import find_peaks
from collections import deque

from gear_utils import (
    # scale
    update_scale, draw_aruco, get_scale,
    # yolo
    load_yolo, run_yolo, draw_yolo_boxes,
    # ui
    build_sidebar, attach_sidebar, SIDEBAR_W,
    # math
    exp_smooth,
)

# ─────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────
MODEL_PATH       = "best_yolo_gear.pt"
YOLO_CONF        = 0.35
YOLO_EVERY_N     = 4
ALPHA            = 0.15
CONFIRMATION_FRAMES = 10

EXPECTED_OUTER_MM  = 50.0
OUTER_RANGE        = (45.0, 60.0)
EXPECTED_INNER_MM  = 20.0
INNER_RANGE        = (15.0, 25.0)
EXPECTED_TEETH     = 24

N_BINS            = 512
ACCUMULATOR_SIZE  = 30

# ─────────────────────────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────────────────────────
Frames             = 0
smoothed_px_mm     = None
smoothed_diameters = {"small": None, "large": None}
detection_counters = {"small": 0, "large": 0}
profile_accumulator = deque(maxlen=ACCUMULATOR_SIZE)
stable_tooth_count  = 0
yolo_results_cache  = []
gear_ok_detected    = False

yolo_model, YOLO_AVAILABLE = load_yolo(MODEL_PATH)


# ─────────────────────────────────────────────────────────────────
# TOP-VIEW SPECIFIC HELPERS
# ─────────────────────────────────────────────────────────────────

def contour_to_polar_profile(cnt, cx, cy, n_bins=N_BINS):
    pts    = cnt[:, 0, :]
    angles = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
    dists  = np.sqrt((pts[:, 0] - cx)**2 + (pts[:, 1] - cy)**2)
    order  = np.argsort(angles)
    angles, dists = angles[order], dists[order]

    bin_edges = np.linspace(-np.pi, np.pi, n_bins + 1)
    profile   = np.zeros(n_bins)
    for i in range(n_bins):
        mask = (angles >= bin_edges[i]) & (angles < bin_edges[i + 1])
        profile[i] = dists[mask].max() if mask.any() else np.nan

    nans = np.isnan(profile)
    if nans.any():
        x = np.arange(n_bins)
        profile[nans] = np.interp(x[nans], x[~nans], profile[~nans])

    mn, mx = profile.min(), profile.max()
    if mx > mn:
        profile = (profile - mn) / (mx - mn)
    return profile


def count_teeth_from_profile(profile):
    pad     = N_BINS // 8
    padded  = np.concatenate([profile[-pad:], profile, profile[:pad]])
    smoothed = cv2.GaussianBlur(
        padded.astype(np.float32).reshape(-1, 1), (7, 1), 0
    ).flatten()

    mean_v, std_v = np.mean(smoothed), np.std(smoothed)
    min_dist = max(4, N_BINS // 40)

    peaks, _ = find_peaks(
        smoothed,
        height=mean_v + 0.1 * std_v,
        distance=min_dist,
        prominence=0.15 * std_v,
    )

    teeth_padded = [p for p in peaks if pad <= p < len(padded) - pad]
    teeth_bins   = [p - pad for p in teeth_padded]

    valleys = []
    for i in range(len(teeth_padded) - 1):
        valleys.append(smoothed[teeth_padded[i]:teeth_padded[i + 1]].min())
    if teeth_padded:
        wrap = np.concatenate([smoothed[teeth_padded[-1]:], smoothed[:teeth_padded[0]]])
        valleys.append(wrap.min())

    valley_mean_norm = np.mean(valleys) if valleys else mean_v
    return len(teeth_bins), valley_mean_norm, teeth_bins


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

        gear_ok_detected = any(d[6].lower() == "gear_ok"
                               for d in yolo_results_cache)
        gear_bad_detected = any(d[6].lower() != "gear_ok"
                                for d in yolo_results_cache)

        if gear_ok_detected:
            step1_status = "PASSED"
        elif gear_bad_detected:
            step1_status = "DEFECT DETECTED"

    # ── Measurement ───────────────────────────────────────
    tooth_tip_points = []

    if smoothed_px_mm is not None:
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255,
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(thresh, cv2.RETR_LIST,
                                       cv2.CHAIN_APPROX_SIMPLE)

        found_this_frame = {"small": False, "large": False}

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 100:
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * (area / (perimeter * perimeter))
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            diam_mm = (radius * 2) * smoothed_px_mm

            # Inner diameter
            if INNER_RANGE[0] < diam_mm < INNER_RANGE[1] and circularity > 0.6:
                found_this_frame["small"] = True
                detection_counters["small"] += 1
                if detection_counters["small"] > CONFIRMATION_FRAMES:
                    smoothed_diameters["small"] = exp_smooth(
                        diam_mm, smoothed_diameters["small"], ALPHA)
                    d = smoothed_diameters["small"]
                    cv2.circle(frame, (int(x), int(y)), int(radius), (0, 255, 0), 2)
                    cv2.putText(frame, f"ID:{d:.1f}mm",
                                (int(x - 10), int(y - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # Outer gear
            (cx, cy), radius_hull = cv2.minEnclosingCircle(cnt)
            hull_diam_mm = (radius_hull * 2) * smoothed_px_mm

            if OUTER_RANGE[0] < hull_diam_mm < OUTER_RANGE[1]:
                profile = contour_to_polar_profile(cnt, cx, cy)
                profile_accumulator.append(profile)

                pts         = cnt[:, 0, :]
                angles_all  = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
                order       = np.argsort(angles_all)
                pts_sorted  = pts[order]
                angles_sorted = angles_all[order]

                if len(profile_accumulator) >= 10:
                    avg_profile = np.mean(profile_accumulator, axis=0)
                    tooth_count_now, _, peak_bins = \
                        count_teeth_from_profile(avg_profile)
                    if tooth_count_now > 0:
                        stable_tooth_count = tooth_count_now

                    bin_edges = np.linspace(-np.pi, np.pi, N_BINS + 1)
                    for b in peak_bins:
                        bin_center = (bin_edges[b] + bin_edges[b + 1]) / 2
                        idx = np.argmin(np.abs(angles_sorted - bin_center))
                        tooth_tip_points.append(tuple(pts_sorted[idx]))

                found_this_frame["large"] = True
                detection_counters["large"] += 1

                if detection_counters["large"] > CONFIRMATION_FRAMES:
                    smoothed_diameters["large"] = exp_smooth(
                        hull_diam_mm, smoothed_diameters["large"], ALPHA)
                    d = smoothed_diameters["large"]
                    cv2.circle(frame,
                               (int(cx), int(cy)), int(radius_hull),
                               (0, 0, 255), 2)
                    cv2.putText(frame,
                                f"OD:{d:.1f}mm | Teeth:{stable_tooth_count}",
                                (int(cx - 80), int(cy - int(radius_hull) - 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                    for (tx, ty) in tooth_tip_points:
                        cv2.line(frame,
                                 (int(cx), int(cy)), (int(tx), int(ty)),
                                 (255, 255, 0), 1)
                        cv2.circle(frame, (int(tx), int(ty)), 3, (0, 255, 255), -1)

        for key in ["small", "large"]:
            if not found_this_frame[key]:
                detection_counters[key] = max(0, detection_counters[key] - 1)

    # ── Verdict logic ──────────────────────────────────────
    outer_ok  = (smoothed_diameters["large"] is not None and
                 OUTER_RANGE[0] <= smoothed_diameters["large"] <= OUTER_RANGE[1])
    inner_ok  = (smoothed_diameters["small"] is not None and
                 INNER_RANGE[0] <= smoothed_diameters["small"] <= INNER_RANGE[1])
    teeth_ok  = (stable_tooth_count == EXPECTED_TEETH)

    step2_status = "CHECKING DIMS"
    if outer_ok and inner_ok and teeth_ok:
        step2_status = "DIMS OK"

    final_ok = (gear_ok_detected and outer_ok and inner_ok and teeth_ok
                if YOLO_AVAILABLE
                else (outer_ok and inner_ok and teeth_ok))
    if not (outer_ok or inner_ok or teeth_ok):
        final_ok = None          # still pending

    # ── Scale label ────────────────────────────────────────
    if smoothed_px_mm:
        scale_txt = f"ArUco  {smoothed_px_mm:.3f} px/mm"
    else:
        from gear_utils import FALLBACK_PX_PER_MM
        scale_txt = f"Fallback  {FALLBACK_PX_PER_MM} px/mm"

    # ── Build sidebar ──────────────────────────────────────
    od_txt  = f"{smoothed_diameters['large']:.1f} mm" \
              if smoothed_diameters["large"] else "---"
    id_txt  = f"{smoothed_diameters['small']:.1f} mm" \
              if smoothed_diameters["small"] else "---"
    tc_txt  = str(stable_tooth_count) if stable_tooth_count else "---"

    rows = [
        {"label": "STEP 1 · YOLO",
         "items": [("Status", step1_status)]},
        {"label": "STEP 2 · DIMENSIONS",
         "items": [
             ("Outer Ø", od_txt),
             ("Inner Ø", id_txt),
             ("Teeth",   tc_txt),
         ]},
    ]

    sidebar = build_sidebar(
        height    = frame.shape[0],
        title     = "TOP VIEW",
        rows      = rows,
        final_ok  = final_ok if (outer_ok or inner_ok) else None,
        scale_text= scale_txt,
    )

    display = attach_sidebar(frame, sidebar)
    cv2.imshow("Gear Top-View Inspection", display)

    # ── Key handling ───────────────────────────────────────
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        break
    elif key == ord('r'):
        smoothed_px_mm     = None
        smoothed_diameters = {"small": None, "large": None}
        detection_counters = {"small": 0, "large": 0}
        profile_accumulator.clear()
        stable_tooth_count  = 0
        yolo_results_cache  = []
        gear_ok_detected    = False
        print("[INFO] State reset.")

cap.release()
cv2.destroyAllWindows()
