"""
gear_utils.py
─────────────────────────────────────────────────────────────────
Shared helpers for gear inspection scripts (top-view & side-view).

Provides:
  • exponential smoothing
  • ArUco scale detection
  • YOLO model loader, runner, box-drawer
  • Sidebar UI renderer
"""

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────────
# GLOBAL DEFAULTS  (override per-script before calling helpers)
# ─────────────────────────────────────────────────────────────────
MARKER_SIZE_MM   = 30.0
FALLBACK_PX_PER_MM = 4.0
YOLO_CONF        = 0.35
YOLO_EVERY_N     = 4

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
    """Exponential moving average. Returns `current` on first call."""
    if previous is None:
        return current
    return alpha * current + (1.0 - alpha) * previous


# ─────────────────────────────────────────────────────────────────
# ARUCO SCALE
# ─────────────────────────────────────────────────────────────────
_aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
_aruco_det  = cv2.aruco.ArucoDetector(_aruco_dict, cv2.aruco.DetectorParameters())


def update_scale(gray, smoothed_px_mm, alpha=0.05):
    """
    Detect ArUco marker in `gray` and return updated smoothed px/mm.
    Also returns corners + ids so the caller can draw them.

    Returns:
        smoothed_px_mm  – updated value (or unchanged if no marker found)
        corners         – raw ArUco corners (may be empty)
        ids             – raw ArUco ids (may be None)
    """
    corners, ids, _ = _aruco_det.detectMarkers(gray)
    if ids is not None and len(corners) > 0:
        side_px = np.linalg.norm(corners[0][0][0] - corners[0][0][1])
        if side_px > 0:
            measured = MARKER_SIZE_MM / side_px
            smoothed_px_mm = exp_smooth(measured, smoothed_px_mm, alpha)
    return smoothed_px_mm, corners, ids


def draw_aruco(frame, corners, ids):
    if ids is not None:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)


def get_scale(smoothed_px_mm):
    """Return smoothed scale or fallback."""
    return smoothed_px_mm if smoothed_px_mm is not None else FALLBACK_PX_PER_MM


# ─────────────────────────────────────────────────────────────────
# YOLO
# ─────────────────────────────────────────────────────────────────

def load_yolo(model_path):
    """
    Load a YOLOv8 model. Returns (model, True) on success,
    (None, False) on failure.
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
    """
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
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)


def best_gear_box(detections, healthy_name, damaged_name):
    """
    Return the highest-confidence detection whose class matches
    healthy_name or damaged_name.  Falls back to any detection.
    """
    named = [d for d in detections
             if d[6].lower() in (healthy_name.lower(), damaged_name.lower())]
    pool  = named if named else detections
    return max(pool, key=lambda d: d[4]) if pool else None


# ─────────────────────────────────────────────────────────────────
# SIDEBAR UI
# ─────────────────────────────────────────────────────────────────
SIDEBAR_W = 240  # pixels

# Palette
_BG      = (18,  22,  28)
_CARD    = (28,  34,  42)
_BORDER  = (45,  55,  68)
_WHITE   = (230, 235, 240)
_DIM     = (110, 120, 135)
_GREEN   = (60,  220, 120)
_YELLOW  = (230, 185,  40)
_RED     = (220,  65,  65)
_CYAN    = (60,  200, 210)
_ORANGE  = (220, 135,  50)


def _status_color(status_key):
    """Map a status key string to an RGB color."""
    sk = status_key.upper()
    if "OK" in sk or "PASSED" in sk or "GOOD" in sk:
        return _GREEN
    if "DEFECT" in sk or "FAIL" in sk or "BAD" in sk:
        return _RED
    if "CHECKING" in sk or "SCANNING" in sk:
        return _YELLOW
    return _DIM


def _draw_rounded_rect(img, pt1, pt2, color, radius=6, thickness=-1):
    """Draw a filled or outlined rounded rectangle (OpenCV helper)."""
    x1, y1 = pt1
    x2, y2 = pt2
    r = min(radius, (x2 - x1) // 2, (y2 - y1) // 2)
    # fill body
    if thickness == -1:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, -1)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, -1)
        for cx, cy in [(x1+r, y1+r), (x2-r, y1+r), (x1+r, y2-r), (x2-r, y2-r)]:
            cv2.circle(img, (cx, cy), r, color, -1)
    else:
        cv2.rectangle(img, (x1 + r, y1), (x2 - r, y2), color, thickness)
        cv2.rectangle(img, (x1, y1 + r), (x2, y2 - r), color, thickness)
        for cx, cy in [(x1+r, y1+r), (x2-r, y1+r), (x1+r, y2-r), (x2-r, y2-r)]:
            cv2.ellipse(img, (cx, cy), (r, r), 0, 180, 270, color, thickness)
            cv2.ellipse(img, (cx, cy), (r, r), 0,  90, 180, color, thickness)
            cv2.ellipse(img, (cx, cy), (r, r), 0,   0,  90, color, thickness)
            cv2.ellipse(img, (cx, cy), (r, r), 0, 270, 360, color, thickness)


def _put(img, text, x, y, scale=0.48, color=_WHITE, bold=False):
    thickness = 2 if bold else 1
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)


def _divider(img, y, x1, x2):
    cv2.line(img, (x1, y), (x2, y), _BORDER, 1)


def build_sidebar(height, title, rows, final_ok, scale_text):
    """
    Create a SIDEBAR_W × height sidebar image.

    Parameters
    ──────────
    height      : int   – must match the camera frame height
    title       : str   – script title shown at top  e.g. "SIDE VIEW"
    rows        : list of dicts, each:
                    {"label": str,   # section header
                     "items": list of (key_str, value_str)}
                  e.g. [{"label": "STEP 1 · YOLO",
                          "items": [("Status", "PASSED")]},
                         {"label": "STEP 2 · DIMS",
                          "items": [("Height", "20.1 mm"),
                                    ("Helix",  "15.2 °")]}]
    final_ok    : bool | None   – True=green, False=red, None=pending
    scale_text  : str   – e.g. "ArUco  4.12 px/mm"
    """
    sb = np.full((height, SIDEBAR_W, 3), _BG, dtype=np.uint8)

    # ── Title bar ──────────────────────────────────────────
    cv2.rectangle(sb, (0, 0), (SIDEBAR_W, 44), _CARD, -1)
    cv2.line(sb, (0, 44), (SIDEBAR_W, 44), _BORDER, 1)
    # small accent stripe
    cv2.rectangle(sb, (0, 0), (4, 44), _CYAN, -1)
    _put(sb, "GEAR INSPECT", 14, 18, scale=0.52, color=_WHITE, bold=True)
    _put(sb, title,          14, 36, scale=0.40, color=_CYAN)

    y = 58
    pad_x = 12

    for section in rows:
        # Section label
        _put(sb, section["label"], pad_x, y, scale=0.38, color=_DIM)
        y += 4
        _divider(sb, y, pad_x, SIDEBAR_W - pad_x)
        y += 10

        for (key, val) in section["items"]:
            col = _status_color(val) if key.lower() == "status" else _WHITE
            _put(sb, key, pad_x, y, scale=0.42, color=_DIM)
            # right-align value
            (tw, _), _ = cv2.getTextSize(val, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
            _put(sb, val, SIDEBAR_W - tw - pad_x, y, scale=0.42, color=col, bold=(key.lower()=="status"))
            y += 20

        y += 6

    # ── Final verdict ──────────────────────────────────────
    verdict_y = height - 70
    _divider(sb, verdict_y - 8, pad_x, SIDEBAR_W - pad_x)

    if final_ok is True:
        vcolor = _GREEN
        vlabel = "GOOD GEAR"
        
    elif final_ok is False:
        vcolor = _RED
        vlabel = "DEFECTIVE"
        
    else:
        vcolor = _DIM
        vlabel = "PENDING..."
    

    _draw_rounded_rect(sb,
                       (pad_x, verdict_y),
                       (SIDEBAR_W - pad_x, verdict_y + 34),
                       vcolor, radius=5)
    label_full =  vlabel
    (tw, _), _ = cv2.getTextSize(label_full, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    tx = pad_x + (SIDEBAR_W - 2*pad_x - tw) // 2
    cv2.putText(sb, label_full, (tx, verdict_y + 23),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                _BG if final_ok is not None else _DIM, 2, cv2.LINE_AA)

    # ── Scale footer ───────────────────────────────────────
    _put(sb, scale_text, pad_x, height - 14, scale=0.36, color=_DIM)

    return sb


def attach_sidebar(frame, sidebar):
    """
    Horizontally concatenate `frame` and `sidebar`.
    Sidebar height is resized to match frame if needed.
    """
    fh = frame.shape[0]
    if sidebar.shape[0] != fh:
        sidebar = cv2.resize(sidebar, (SIDEBAR_W, fh))
    return np.hstack([frame, sidebar])
