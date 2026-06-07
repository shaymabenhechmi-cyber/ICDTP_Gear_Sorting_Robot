"""
main.py  —  Gear Inspection Pipeline
──────────────────────────────────────────────────────────────────
Launches either the Top-View or Side-View inspection mode from a
single entry point.

Usage
  python main.py                  # shows mode-selection menu
  python main.py --mode top       # start directly in top-view
  python main.py --mode side      # start directly in side-view

Controls (in any mode)
  q   quit
  r   reset all state
  m   return to mode-selection menu
"""

import argparse
import sys
import cv2
import numpy as np
import math
from collections import deque
from scipy.signal import find_peaks

from gear_utils import (
    update_scale, draw_aruco, get_scale,
    load_yolo, run_yolo, draw_yolo_boxes, best_gear_box,
    build_sidebar, attach_sidebar,
    exp_smooth, FALLBACK_PX_PER_MM, SIDEBAR_W,
)

# ─────────────────────────────────────────────────────────────────
# SHARED CONFIG
# ─────────────────────────────────────────────────────────────────
YOLO_EVERY_N        = 4
ALPHA               = 0.15
CONFIRMATION_FRAMES = 10

# ── Top-view ──────────────────────────────────────────────────────
TOP_MODEL_PATH     = "best_yolo_gear.pt"
TOP_YOLO_CONF      = 0.35
EXPECTED_OUTER_MM  = 50.0
OUTER_RANGE        = (45.0, 60.0)
EXPECTED_INNER_MM  = 20.0
INNER_RANGE        = (15.0, 25.0)
EXPECTED_TEETH     = 24
N_BINS             = 512
ACCUMULATOR_SIZE   = 30

# ── Side-view ─────────────────────────────────────────────────────
SIDE_MODEL_PATH      = "best_yolo_gear_v3.pt"
SIDE_YOLO_CONF       = 0.35
HEALTHY_CLASS_NAME   = "healthy_gear"
DAMAGED_CLASS_NAME   = "damaged_gear"
EXPECTED_HEIGHT_MM   = 20.0
HEIGHT_TOLERANCE_MM  = 5.0
EXPECTED_HELIX_ANGLE = 15.0
HELIX_TOLERANCE_DEG  = 7.0


# ─────────────────────────────────────────────────────────────────
# MODE-SELECTION MENU  (rendered with OpenCV — no external GUI lib)
# ─────────────────────────────────────────────────────────────────
_BG_MENU   = (18,  22,  28)
_ACCENT    = (60,  200, 210)
_WHITE     = (230, 235, 240)
_DIM       = (110, 120, 135)
_GREEN     = (60,  220, 120)
_CARD      = (28,  34,  42)
_BORDER    = (45,  55,  68)
MENU_W, MENU_H = 520, 320


def _draw_menu(selected):
    """Render the mode-selection canvas. selected ∈ {0, 1, None}."""
    img = np.full((MENU_H, MENU_W, 3), _BG_MENU, dtype=np.uint8)

    # header
    cv2.rectangle(img, (0, 0), (MENU_W, 56), _CARD, -1)
    cv2.line(img, (0, 56), (MENU_W, 56), _BORDER, 1)
    cv2.rectangle(img, (0, 0), (5, 56), _ACCENT, -1)
    cv2.putText(img, "GEAR INSPECTION PIPELINE",
                (18, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, _WHITE, 2, cv2.LINE_AA)
    cv2.putText(img, "Select inspection mode",
                (18, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.38, _DIM, 1, cv2.LINE_AA)

    options = [
        ("1", "TOP VIEW",  "Outer Ø · Inner Ø · Tooth count"),
        ("2", "SIDE VIEW", "Face height · Helix angle"),
    ]

    for i, (key, title, subtitle) in enumerate(options):
        bx1, by1 = 24, 76 + i * 90
        bx2, by2 = MENU_W - 24, by1 + 72
        is_sel = (selected == i)
        card_col  = (38, 48, 60) if is_sel else _CARD
        bord_col  = _ACCENT if is_sel else _BORDER

        cv2.rectangle(img, (bx1, by1), (bx2, by2), card_col, -1)
        cv2.rectangle(img, (bx1, by1), (bx2, by2), bord_col, 2)

        # key badge
        cv2.rectangle(img, (bx1 + 10, by1 + 14), (bx1 + 36, by1 + 40), _ACCENT, -1)
        cv2.putText(img, key,
                    (bx1 + 18, by1 + 33),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, _BG_MENU, 2, cv2.LINE_AA)

        cv2.putText(img, title,
                    (bx1 + 50, by1 + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.60, _ACCENT if is_sel else _WHITE,
                    2 if is_sel else 1, cv2.LINE_AA)
        cv2.putText(img, subtitle,
                    (bx1 + 50, by1 + 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, _DIM, 1, cv2.LINE_AA)

    # footer
    cv2.putText(img, "Press  1 / 2  to select    Enter to confirm    Q to quit",
                (24, MENU_H - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.34, _DIM, 1, cv2.LINE_AA)
    return img


def show_menu():
    """
    Display mode-selection window.
    Returns 'top', 'side', or None (quit).
    """
    selected = 0
    cv2.namedWindow("Gear Inspection — Select Mode", cv2.WINDOW_AUTOSIZE)

    while True:
        cv2.imshow("Gear Inspection — Select Mode", _draw_menu(selected))
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q') or key == 27:          # q / Esc → quit
            cv2.destroyAllWindows()
            return None
        elif key == ord('1'):
            selected = 0
        elif key == ord('2'):
            selected = 1
        elif key in (13, 10):                      # Enter → confirm
            cv2.destroyAllWindows()
            return "top" if selected == 0 else "side"


# ─────────────────────────────────────────────────────────────────
# TOP-VIEW HELPERS
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
        padded.astype(np.float32).reshape(-1, 1), (7, 1), 0).flatten()

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
        wrap = np.concatenate([smoothed[teeth_padded[-1]:],
                               smoothed[:teeth_padded[0]]])
        valleys.append(wrap.min())

    valley_mean_norm = np.mean(valleys) if valleys else mean_v
    return len(teeth_bins), valley_mean_norm, teeth_bins


# ─────────────────────────────────────────────────────────────────
# SIDE-VIEW HELPERS
# ─────────────────────────────────────────────────────────────────

def measure_height_from_box(x1, y1, x2, y2, px_mm):
    height_mm = (y2 - y1) / px_mm
    width_mm  = (x2 - x1) / px_mm
    return height_mm, width_mm


def estimate_helix_angle(gray_full, x1, y1, x2, y2, debug_frame=None):
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
                            threshold=20, minLineLength=min_len, maxLineGap=10)
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
# TOP-VIEW LOOP
# ─────────────────────────────────────────────────────────────────

def run_top_view():
    yolo_model, YOLO_AVAILABLE = load_yolo(TOP_MODEL_PATH)

    Frames             = 0
    smoothed_px_mm     = None
    smoothed_diameters = {"small": None, "large": None}
    detection_counters = {"small": 0,    "large": 0}
    profile_accumulator = deque(maxlen=ACCUMULATOR_SIZE)
    stable_tooth_count  = 0
    yolo_results_cache  = []
    gear_ok_detected    = False

    cap = cv2.VideoCapture("http://192.168.100.3:4747/video")
    mode = "top"          # return value; overridden if user presses m

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        Frames += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        smoothed_px_mm, corners, ids = update_scale(gray, smoothed_px_mm)
        draw_aruco(frame, corners, ids)
        px_mm = get_scale(smoothed_px_mm)

        step1_status = "SCANNING..."
        if YOLO_AVAILABLE:
            if Frames % YOLO_EVERY_N == 0:
                yolo_results_cache = run_yolo(yolo_model, frame, TOP_YOLO_CONF)
            draw_yolo_boxes(frame, yolo_results_cache)
            gear_ok_detected  = any(d[6].lower() == "gear_ok"
                                    for d in yolo_results_cache)
            gear_bad_detected = any(d[6].lower() != "gear_ok"
                                    for d in yolo_results_cache)
            if gear_ok_detected:
                step1_status = "PASSED"
            elif gear_bad_detected:
                step1_status = "DEFECT DETECTED"

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

                (cx, cy), radius_hull = cv2.minEnclosingCircle(cnt)
                hull_diam_mm = (radius_hull * 2) * smoothed_px_mm

                if OUTER_RANGE[0] < hull_diam_mm < OUTER_RANGE[1]:
                    profile = contour_to_polar_profile(cnt, cx, cy)
                    profile_accumulator.append(profile)

                    pts          = cnt[:, 0, :]
                    angles_all   = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
                    order        = np.argsort(angles_all)
                    pts_sorted   = pts[order]
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

            for k in ["small", "large"]:
                if not found_this_frame[k]:
                    detection_counters[k] = max(0, detection_counters[k] - 1)

        outer_ok = (smoothed_diameters["large"] is not None and
                    OUTER_RANGE[0] <= smoothed_diameters["large"] <= OUTER_RANGE[1])
        inner_ok = (smoothed_diameters["small"] is not None and
                    INNER_RANGE[0] <= smoothed_diameters["small"] <= INNER_RANGE[1])
        teeth_ok = (stable_tooth_count == EXPECTED_TEETH)

        step2_status = "CHECKING DIMS"
        if outer_ok and inner_ok and teeth_ok:
            step2_status = "DIMS OK"

        final_ok = (gear_ok_detected and outer_ok and inner_ok and teeth_ok
                    if YOLO_AVAILABLE
                    else (outer_ok and inner_ok and teeth_ok))
        if not (outer_ok or inner_ok or teeth_ok):
            final_ok = None

        scale_txt = (f"ArUco  {smoothed_px_mm:.3f} px/mm"
                     if smoothed_px_mm
                     else f"Fallback  {FALLBACK_PX_PER_MM} px/mm")

        od_txt = f"{smoothed_diameters['large']:.1f} mm" \
                 if smoothed_diameters["large"] else "---"
        id_txt = f"{smoothed_diameters['small']:.1f} mm" \
                 if smoothed_diameters["small"] else "---"
        tc_txt = str(stable_tooth_count) if stable_tooth_count else "---"

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
            height=frame.shape[0], title="TOP VIEW",
            rows=rows,
            final_ok=final_ok if (outer_ok or inner_ok) else None,
            scale_text=scale_txt,
        )

        # mode hint overlay
        cv2.putText(frame, "M: menu  R: reset  Q: quit",
                    (8, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (80, 90, 100), 1, cv2.LINE_AA)

        cv2.imshow("Gear Inspection — Top View", attach_sidebar(frame, sidebar))

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            mode = None
            break
        elif key == ord('m'):
            mode = "menu"
            break
        elif key == ord('r'):
            smoothed_px_mm     = None
            smoothed_diameters = {"small": None, "large": None}
            detection_counters = {"small": 0,    "large": 0}
            profile_accumulator.clear()
            stable_tooth_count  = 0
            yolo_results_cache  = []
            gear_ok_detected    = False
            print("[INFO] State reset.")

    cap.release()
    cv2.destroyAllWindows()
    return mode


# ─────────────────────────────────────────────────────────────────
# SIDE-VIEW LOOP
# ─────────────────────────────────────────────────────────────────

def run_side_view():
    yolo_model, YOLO_AVAILABLE = load_yolo(SIDE_MODEL_PATH)

    Frames             = 0
    smoothed_px_mm     = None
    smoothed_height_mm = None
    smoothed_helix_deg = None
    height_counter     = 0
    helix_counter      = 0
    edge_profile_acc   = deque(maxlen=20)
    yolo_results_cache = []
    gear_ok_detected   = False

    cap = cv2.VideoCapture("http://192.168.100.3:4747/video")

    mode = "side"

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        Frames += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        smoothed_px_mm, corners, ids = update_scale(gray, smoothed_px_mm)
        draw_aruco(frame, corners, ids)
        px_mm = get_scale(smoothed_px_mm)

        step1_status = "SCANNING..."
        if YOLO_AVAILABLE:
            if Frames % YOLO_EVERY_N == 0:
                yolo_results_cache = run_yolo(yolo_model, frame, SIDE_YOLO_CONF)
            draw_yolo_boxes(frame, yolo_results_cache)

            gear_ok_detected  = any(d[6].lower() == HEALTHY_CLASS_NAME.lower()
                                    for d in yolo_results_cache)
            gear_bad_detected = any(d[6].lower() == DAMAGED_CLASS_NAME.lower()
                                    for d in yolo_results_cache)
            if gear_ok_detected:
                step1_status = "PASSED"
            elif gear_bad_detected:
                step1_status = "DEFECT DETECTED"

        gear_box = best_gear_box(yolo_results_cache,
                                 HEALTHY_CLASS_NAME, DAMAGED_CLASS_NAME)

        if gear_box is not None:
            bx1, by1, bx2, by2 = gear_box[0], gear_box[1], gear_box[2], gear_box[3]
            mid_y = (by1 + by2) // 2

            height_mm, _ = measure_height_from_box(bx1, by1, bx2, by2, px_mm)
            height_counter += 1
            if height_counter > CONFIRMATION_FRAMES:
                smoothed_height_mm = exp_smooth(height_mm, smoothed_height_mm, ALPHA)

            cv2.line(frame, (bx1 - 18, by1), (bx1 - 18, by2), (255, 80, 0), 2)
            cv2.line(frame, (bx1 - 26, by1), (bx1 - 8, by1), (255, 80, 0), 2)
            cv2.line(frame, (bx1 - 26, by2), (bx1 - 8, by2), (255, 80, 0), 2)
            h_label = (f"H:{smoothed_height_mm:.1f}mm"
                       if smoothed_height_mm else f"H~{height_mm:.1f}mm")
            cv2.putText(frame, h_label,
                        (max(0, bx1 - 110), mid_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 80, 0), 2)

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
            final_ok = None

        scale_txt = (f"ArUco  {smoothed_px_mm:.3f} px/mm"
                     if smoothed_px_mm
                     else f"Fallback  {FALLBACK_PX_PER_MM} px/mm")

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
            height=frame.shape[0], title="SIDE VIEW",
            rows=rows,
            final_ok=final_ok if (height_ok or helix_ok) else None,
            scale_text=scale_txt,
        )

        cv2.putText(frame, "M: menu  R: reset  Q: quit",
                    (8, frame.shape[0] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, (80, 90, 100), 1, cv2.LINE_AA)

        cv2.imshow("Gear Inspection — Side View", attach_sidebar(frame, sidebar))

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            mode = None
            break
        elif key == ord('m'):
            mode = "menu"
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
    return mode


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Gear Inspection Pipeline — top-view & side-view")
    parser.add_argument("--mode", choices=["top", "side"],
                        help="Start directly in a mode (skips menu)")
    args = parser.parse_args()

    mode = args.mode  # may be None → show menu

    while True:
        if mode is None:
            mode = show_menu()
            if mode is None:           # user pressed Q in menu
                print("[INFO] Exiting.")
                sys.exit(0)

        if mode == "top":
            result = run_top_view()
        elif mode == "side":
            result = run_side_view()
        else:
            result = None

        # result == "menu"  → loop back to selector
        # result == None    → user pressed Q inside a mode → quit
        if result is None:
            print("[INFO] Exiting.")
            sys.exit(0)
        elif result == "menu":
            mode = None               # show menu again


if __name__ == "__main__":
    main()
