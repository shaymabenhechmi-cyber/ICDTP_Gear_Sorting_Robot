"""
gear_utils.py
─────────────────────────────────────────────────────────────────
Shared helpers for gear inspection scripts (top-view & side-view).

Provides:
  • exponential smoothing
  • ArUco scale detection
  • YOLO model loader, runner, box-drawer
  • Sidebar UI renderer

FIXES vs original
─────────────────
1. update_scale(): scale was inverted (mm/px instead of px/mm).
   Corrected to  side_px / MARKER_SIZE_MM  so every consumer that
   does  diam = (r*2) / px_mm  gets a real millimetre value.
2. update_scale(): now averages all 4 marker sides instead of only
   the first edge – more stable under perspective distortion.
3. run_yolo(): guarded against model=None (YOLO failed to load).
4. draw_aruco(): guarded against empty corners list (crash fix).
5. _draw_rounded_rect() outlined mode: arc quadrant angles were
   wrong/duplicated; replaced with correct TL/TR/BL/BR arcs.
6. build_sidebar(): added y_max guard so rows never overwrite the
   verdict or footer area when many metrics are displayed.
7. build_sidebar(): PENDING text colour was _DIM-on-_DIM (invisible);
   corrected to _WHITE so it remains readable.
"""

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────────
# GLOBAL DEFAULTS  (override per-script before calling helpers)
# ─────────────────────────────────────────────────────────────────
MARKER_SIZE_MM     = 30.0   # real side length of ArUco marker (mm)
FALLBACK_PX_PER_MM = 4.0   # fallback when marker not yet seen
YOLO_CONF          = 0.35
YOLO_EVERY_N       = 4

DEFECT_COLORS = [
    (0,   255, 100),
    (0,   0,   255),
    (0,   255, 255),
    (255, 0,   255),
    (255, 128, 0  ),
]

# ─────────────────────────────────────────────────────────────────
# MATH / SIGNAL
# ─────────────────────────────────────────────────────────────────

def exp_smooth(current, previous, alpha=0.15):
    """
    Exponential moving average.
    Returns `current` on first call (previous=None).
    `current` must never be None.
    """
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


# ─────────────────────────────────────────────────────────────────
# ARUCO SCALE
# ─────────────────────────────────────────────────────────────────

_aruco_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_aruco_params = cv2.aruco.DetectorParameters()          # must be instantiated
_aruco_det    = cv2.aruco.ArucoDetector(_aruco_dict, _aruco_params)


def update_scale(gray, smoothed_px_mm, alpha=0.05):
    """
    Detect an ArUco marker in `gray` and return the updated px/mm scale.

    FIX: original used  MARKER_SIZE_MM / side_px  → gives mm/px (inverted).
    Correct formula is  side_px / MARKER_SIZE_MM  → gives px/mm.
    All callers use  diam_mm = (r_px * 2) / px_mm,  which only works when
    px_mm is truly pixels-per-millimetre.

    Returns
    ───────
    smoothed_px_mm  updated px/mm value (or unchanged if no marker found)
    corners         raw ArUco corners (may be empty list)
    ids             raw ArUco ids     (may be None)
    """
    corners, ids, _ = _aruco_det.detectMarkers(gray)
    if ids is not None and len(corners) > 0:
        c = corners[0][0]   # shape (4, 2)  – four corner points
        # Average all four sides for robustness against perspective tilt
        sides = [
            np.linalg.norm(c[0] - c[1]),
            np.linalg.norm(c[1] - c[2]),
            np.linalg.norm(c[2] - c[3]),
            np.linalg.norm(c[3] - c[0]),
        ]
        side_px = float(np.mean(sides))
        if side_px > 0:
            measured       = side_px / MARKER_SIZE_MM   # px/mm  ← FIXED
            smoothed_px_mm = exp_smooth(measured, smoothed_px_mm, alpha)
    return smoothed_px_mm, corners, ids


def draw_aruco(frame, corners, ids):
    """Draw detected ArUco markers onto frame (in-place).
    FIX: original crashed when corners was an empty list."""
    if ids is not None and len(corners) > 0:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)


def get_scale(smoothed_px_mm):
    """Return smoothed scale (px/mm) or the global fallback."""
    return smoothed_px_mm if smoothed_px_mm is not None else FALLBACK_PX_PER_MM


# ─────────────────────────────────────────────────────────────────
# YOLO
# ─────────────────────────────────────────────────────────────────

def load_yolo(model_path):
    """
    Load a YOLOv8 model.
    Returns (model, True) on success, (None, False) on failure.
    """
    try:
        from ultralytics import YOLO
        model = YOLO(model_path)
        print(f"[INFO] YOLO model loaded : '{model_path}'")
        print(f"[INFO] Classes           : {model.names}")
        return model, True
    except Exception as exc:
        print(f"[WARN] YOLO unavailable  : {exc}")
        return None, False


def run_yolo(model, frame, conf=None):
    """
    Run inference on `frame`.
    Returns list of (x1, y1, x2, y2, conf, cls_id, cls_name).

    FIX: guard against model=None so callers never crash when YOLO
    failed to load.
    """
    if model is None:           # ← FIX
        return []
    if conf is None:
        conf = YOLO_CONF
    detections = []
    for r in model.predict(frame, conf=conf, verbose=False):
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            c        = float(box.conf[0])
            cls_id   = int(box.cls[0])
            cls_name = model.names[cls_id]
            detections.append((x1, y1, x2, y2, c, cls_id, cls_name))
    return detections


def draw_yolo_boxes(frame, detections):
    """Draw bounding boxes + labels for every detection."""
    for (x1, y1, x2, y2, conf, cls_id, cls_name) in detections:
        color = DEFECT_COLORS[cls_id % len(DEFECT_COLORS)]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{cls_name} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1,
                    cv2.LINE_AA)


def best_gear_box(detections, healthy_name, damaged_name):
    """
    Return highest-confidence detection matching healthy_name or
    damaged_name.  Falls back to any detection.  Returns None if empty.
    """
    named = [d for d in detections
             if d[6].lower() in (healthy_name.lower(), damaged_name.lower())]
    pool  = named if named else detections
    return max(pool, key=lambda d: d[4]) if pool else None


# ─────────────────────────────────────────────────────────────────
# SIDEBAR UI
# ─────────────────────────────────────────────────────────────────
SIDEBAR_W = 240  # pixels

# Colour palette (BGR tuples for OpenCV)
_BG     = (18,  22,  28)
_CARD   = (28,  34,  42)
_BORDER = (45,  55,  68)
_WHITE  = (230, 235, 240)
_DIM    = (110, 120, 135)
_GREEN  = (60,  220, 120)
_YELLOW = (230, 185,  40)
_RED    = (220,  65,  65)
_CYAN   = (60,  200, 210)
_ORANGE = (220, 135,  50)


def _status_color(val):
    v = val.upper()
    if any(x in v for x in ("OK", "PASSED", "GOOD")):
        return _GREEN
    if any(x in v for x in ("DEFECT", "FAIL", "BAD")):
        return _RED
    if any(x in v for x in ("CHECKING", "SCANNING")):
        return _YELLOW
    return _DIM


def _draw_rounded_rect(img, pt1, pt2, color, radius=6, thickness=-1):
    """Filled (thickness=-1) or outlined rounded rectangle.

    FIX: original outlined mode had wrong/duplicated arc angles.
    Correct quadrant arcs: TL=180-270, TR=270-360, BL=90-180, BR=0-90.
    """
    x1, y1 = pt1
    x2, y2 = pt2
    r = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    if thickness == -1:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        for cx, cy in [(x1+r, y1+r), (x2-r, y1+r),
                       (x1+r, y2-r), (x2-r, y2-r)]:
            cv2.circle(img, (cx, cy), r, color, -1)
    else:
        cv2.rectangle(img, (x1 + r, y1),     (x2 - r, y2),     color, thickness)
        cv2.rectangle(img, (x1,     y1 + r), (x2,     y2 - r), color, thickness)
        cv2.ellipse(img, (x1+r, y1+r), (r, r), 0, 180, 270, color, thickness)  # TL
        cv2.ellipse(img, (x2-r, y1+r), (r, r), 0, 270, 360, color, thickness)  # TR
        cv2.ellipse(img, (x1+r, y2-r), (r, r), 0,  90, 180, color, thickness)  # BL
        cv2.ellipse(img, (x2-r, y2-r), (r, r), 0,   0,  90, color, thickness)  # BR


def _put(img, text, x, y, scale=0.48, color=_WHITE, bold=False):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, 2 if bold else 1, cv2.LINE_AA)


def _divider(img, y, x1, x2):
    cv2.line(img, (x1, y), (x2, y), _BORDER, 1)


def build_sidebar(height, title, rows, final_ok, scale_text):
    """
    Build a SIDEBAR_W × height panel.

    Parameters
    ──────────
    height     : int
    title      : str            e.g. "TOP VIEW"
    rows       : list of dicts  {"label": str, "items": [(key, val), …]}
    final_ok   : True  → green  GOOD GEAR
                 False → red    DEFECTIVE
                 None  → grey   PENDING…
    scale_text : str            e.g. "ArUco  4.12 px/mm"

    FIX: added y_max guard so metric rows never overwrite the verdict
    block or footer regardless of how many rows are supplied.
    FIX: PENDING text was _DIM drawn on a _DIM background (invisible);
    corrected to _WHITE.
    """
    sb    = np.full((height, SIDEBAR_W, 3), _BG, dtype=np.uint8)
    pad_x = 12

    # ── Title bar ──────────────────────────────────────────────
    cv2.rectangle(sb, (0, 0), (SIDEBAR_W, 44), _CARD, -1)
    cv2.line(sb, (0, 44), (SIDEBAR_W, 44), _BORDER, 1)
    cv2.rectangle(sb, (0, 0), (4, 44), _CYAN, -1)
    _put(sb, "GEAR INSPECT", 14, 18, scale=0.52, color=_WHITE, bold=True)
    _put(sb, title,          14, 36, scale=0.40, color=_CYAN)

    y     = 58
    # Reserve 70 px for verdict + 24 px for footer
    y_max = height - 70 - 24

    for section in rows:
        if y >= y_max:
            break
        _put(sb, section["label"], pad_x, y, scale=0.38, color=_DIM)
        y += 4
        _divider(sb, y, pad_x, SIDEBAR_W - pad_x)
        y += 10
        for (key, val) in section["items"]:
            if y >= y_max:
                break
            col = _status_color(val) if key.lower() == "status" else _WHITE
            _put(sb, key, pad_x, y, scale=0.42, color=_DIM)
            (tw, _), _ = cv2.getTextSize(val, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
            _put(sb, val, SIDEBAR_W - tw - pad_x, y,
                 scale=0.42, color=col, bold=(key.lower() == "status"))
            y += 20
        y += 6

    # ── Final verdict ──────────────────────────────────────────
    verdict_y = height - 70
    _divider(sb, verdict_y - 8, pad_x, SIDEBAR_W - pad_x)

    if final_ok is True:
        vcolor, vlabel = _GREEN, "GOOD GEAR"
    elif final_ok is False:
        vcolor, vlabel = _RED,   "DEFECTIVE"
    else:
        vcolor, vlabel = _DIM,   "PENDING..."

    _draw_rounded_rect(sb,
                       (pad_x,             verdict_y),
                       (SIDEBAR_W - pad_x, verdict_y + 34),
                       vcolor, radius=5)

    (tw, _), _ = cv2.getTextSize(vlabel, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    tx      = pad_x + (SIDEBAR_W - 2 * pad_x - tw) // 2
    # FIX: use _BG for solid verdicts (text contrasts against colour bg),
    #      _WHITE for PENDING (contrasts against dark _DIM bg).
    txt_col = _BG if final_ok is not None else _WHITE
    cv2.putText(sb, vlabel, (tx, verdict_y + 23),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, txt_col, 2, cv2.LINE_AA)

    # ── Scale footer ───────────────────────────────────────────
    _put(sb, scale_text, pad_x, height - 14, scale=0.36, color=_DIM)

    return sb


def attach_sidebar(frame, sidebar):
    """Horizontally concatenate frame and sidebar (resizes sidebar height)."""
    fh = frame.shape[0]
    if sidebar.shape[0] != fh:
        sidebar = cv2.resize(sidebar, (SIDEBAR_W, fh))
    return np.hstack([frame, sidebar])