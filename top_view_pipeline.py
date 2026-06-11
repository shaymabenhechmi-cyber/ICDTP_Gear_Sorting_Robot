"""
top_view.py - Version corrigée avec priorité absolue à YOLO defect
"""

import cv2
import numpy as np
from collections import deque
from scipy.signal import find_peaks
from gear_utils import (
    update_scale, draw_aruco, get_scale,
    run_yolo, draw_yolo_boxes, best_gear_box,
    load_yolo, exp_smooth,
    build_sidebar, attach_sidebar, SIDEBAR_W,
    YOLO_EVERY_N,
)

# ─────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────
MODEL_PATH = "best_yolo_gear.pt"
YOLO_CONF  = 0.35

OUTER_RANGE    = (45.0, 60.0)   # mm – expected outer-diameter window
INNER_RANGE    = (15.0, 25.0)   # mm – expected inner-bore window
EXPECTED_TEETH = 24

N_BINS = 512    # angular bins for radial profile
ACCUM  = 30     # frames averaged for tooth count

# ─────────────────────────────────────────────────────────────────
# TOOTH-COUNT HELPERS
# ─────────────────────────────────────────────────────────────────

def _contour_to_profile(cnt, cx, cy):
    """Convert a contour to a radial distance profile (N_BINS bins)."""
    pts    = cnt[:, 0, :]
    angles = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
    dists  = np.sqrt((pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2)
    order  = np.argsort(angles)
    angles, dists = angles[order], dists[order]

    bins = np.linspace(-np.pi, np.pi, N_BINS + 1)
    prof = np.zeros(N_BINS)
    for i in range(N_BINS):
        mask    = (angles >= bins[i]) & (angles < bins[i + 1])
        prof[i] = np.max(dists[mask]) if np.any(mask) else 0
    return prof


def _count_teeth(profile):
    """Count peaks (teeth) in a smoothed radial profile."""
    smooth = cv2.GaussianBlur(profile.reshape(-1, 1), (7, 1), 0).flatten()
    peaks, _ = find_peaks(smooth, distance=N_BINS // (EXPECTED_TEETH * 2))
    return len(peaks)


# ─────────────────────────────────────────────────────────────────
# STATUS OVERLAY SIMPLIFIÉ - VERDICT CLAIR
# ─────────────────────────────────────────────────────────────────

def _draw_simple_result(frame, final_ok, yolo_class, outer_mm, inner_mm, teeth):
    """
    Affichage minimal : uniquement le verdict final bien visible
    """
    h, w = frame.shape[:2]
    
    # Bande de résultat en bas (plus grande et plus visible)
    result_h = 100
    result_y = h - result_h
    
    # Déterminer le verdict - PRIORITÉ ABSOLUE À YOLO DEFECT
    if final_ok is True:
        verdict = "ACCEPTE - GOOD GEAR"
        bg_color = (0, 100, 0)      # Vert foncé
        txt_color = (0, 255, 0)     # Vert vif
        border_color = (0, 255, 0)
    elif final_ok is False:
        verdict = "REJETE - DEFECTIVE GEAR"
        bg_color = (0, 0, 100)      # Rouge foncé
        txt_color = (0, 0, 255)     # Rouge vif
        border_color = (0, 0, 255)
    else:
        verdict = "ANALYSE EN COURS..."
        bg_color = (60, 60, 60)     # Gris
        txt_color = (200, 200, 200)
        border_color = (100, 100, 100)
    
    # Fond semi-transparent
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, result_y), (w, h), bg_color, -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    
    # Bordure
    cv2.rectangle(frame, (0, result_y), (w, h), border_color, 3)
    
    # Texte du verdict (grand et centré)
    font_scale = 1.5 if final_ok is not None else 1.2
    (tw, th), _ = cv2.getTextSize(verdict, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 3)
    text_x = (w - tw) // 2
    text_y = result_y + (result_h + th) // 2
    cv2.putText(frame, verdict, (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, txt_color, 3, cv2.LINE_AA)
    
    # Petit texte d'information en dessous
    if final_ok is not None and outer_mm is not None:
        info = f"OD:{outer_mm:.1f}mm ID:{inner_mm:.1f}mm"
        if teeth:
            info += f" Teeth:{teeth}"
        (iw, ih), _ = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.putText(frame, info, ((w - iw) // 2, text_y + 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    
    # Ajouter un avertissement si YOLO a détecté defective
    if yolo_class == "damaged":
        warn_y = result_y - 10
        cv2.putText(frame, "⚠ YOLO DETECTED DAMAGED GEAR ⚠", (w//2 - 150, warn_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────
# STATE FACTORY
# ─────────────────────────────────────────────────────────────────

def _make_state(model):
    return {
        "model":        model,
        "frame":        0,
        "px":           None,
        "outer":        None,
        "inner":        None,
        "teeth":        None,
        "profiles":     deque(maxlen=ACCUM),
        "outer_center": None,
        "outer_r_px":   None,
        "inner_center": None,
        "inner_r_px":   None,
        "yolo":         [],
        "yolo_class":   None,
        "yolo_ok":      False,
        "dims_ok":      False,
        "final_ok":     None,
        "seen":         False,
    }


# ─────────────────────────────────────────────────────────────────
# CORE FRAME PROCESSOR
# ─────────────────────────────────────────────────────────────────

def process_top(frame, state):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # ── 1. ArUco scale ──────────────────────────────────────────
    state["px"], corners, ids = update_scale(gray, state["px"])
    draw_aruco(frame, corners, ids)

    if state["px"] is None:
        cv2.putText(frame, "ARUCO NOT DETECTED", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)
        _draw_simple_result(frame, None, None, None, None, None)
        return frame

    px_mm = get_scale(state["px"])

    # ── 2. YOLO detection ───────────────────────────────────────
    if state["frame"] % YOLO_EVERY_N == 0:
        state["yolo"] = run_yolo(state["model"], frame, YOLO_CONF)

    draw_yolo_boxes(frame, state["yolo"])

    # Analyser les détections YOLO
    _det = state["yolo"]
    _healthy = [d for d in _det if d[6].lower() == "healthy_gear"]
    _damaged = [d for d in _det if d[6].lower() == "damaged_gear" or d[6].lower() == "gear_defect"]
    
    healthy_box = max(_healthy, key=lambda d: d[4]) if _healthy else None
    damaged_box = max(_damaged, key=lambda d: d[4]) if _damaged else None
    gear_box = best_gear_box(_det, "healthy_gear", "damaged_gear")

    # IMPORTANT: Priorité à damaged_box
    if damaged_box is not None:
        bx1, by1, bx2, by2 = damaged_box[:4]
        state["seen"] = True
        state["yolo_class"] = "damaged"
        print(f"[YOLO] ❌ DAMAGED GEAR detected - Confidence: {damaged_box[4]:.2f}")
    elif healthy_box is not None:
        bx1, by1, bx2, by2 = healthy_box[:4]
        state["seen"] = True
        state["yolo_class"] = "healthy"
        print(f"[YOLO] ✓ HEALTHY GEAR detected - Confidence: {healthy_box[4]:.2f}")
    elif gear_box is not None:
        bx1, by1, bx2, by2 = gear_box[:4]
        state["seen"] = True
        state["yolo_class"] = "unknown"
        print(f"[YOLO] ? UNKNOWN gear detected")
    else:
        bx1, by1, bx2, by2 = 0, 0, frame.shape[1], frame.shape[0]
        state["yolo_class"] = None
        print(f"[YOLO] No gear detected")

    # ── 3. Segmentation inside ROI ──────────────────────────────
    roi_gray = gray[by1:by2, bx1:bx2]
    if roi_gray.size == 0:
        _draw_simple_result(frame, state["final_ok"], state["yolo_class"], 
                           state["outer"], state["inner"], state["teeth"])
        return frame
        
    blurred = cv2.GaussianBlur(roi_gray, (5, 5), 0)
    _, th = cv2.threshold(blurred, 0, 255,
                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best_outer = None
    best_inner = None
    best_outer_area = 0
    best_inner_area = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 200:
            continue

        cnt_full = cnt.copy()
        cnt_full[:, 0, 0] += bx1
        cnt_full[:, 0, 1] += by1

        (cx, cy), r = cv2.minEnclosingCircle(cnt_full)
        if r <= 0:
            continue

        diam = (r * 2) / px_mm

        if OUTER_RANGE[0] < diam < OUTER_RANGE[1]:
            if area > best_outer_area:
                best_outer_area = area
                best_outer = (cnt_full, cx, cy, r, diam)

        elif INNER_RANGE[0] < diam < INNER_RANGE[1]:
            if area > best_inner_area:
                best_inner_area = area
                best_inner = (cnt_full, cx, cy, r, diam)

    # ── 4. Update measurements ──────────────────────────────────
    if best_outer is not None:
        cnt_full, cx, cy, r, diam = best_outer
        state["outer"] = exp_smooth(diam, state["outer"])
        state["outer_center"] = (int(cx), int(cy))
        state["outer_r_px"] = int(r)

        prof = _contour_to_profile(cnt_full, cx, cy)
        state["profiles"].append(prof)
        if len(state["profiles"]) >= 10:
            avg = np.mean(state["profiles"], axis=0)
            state["teeth"] = _count_teeth(avg)

    if best_inner is not None:
        _, cx, cy, r, diam = best_inner
        state["inner"] = exp_smooth(diam, state["inner"])
        state["inner_center"] = (int(cx), int(cy))
        state["inner_r_px"] = int(r)

    # ── 5. Draw circles ─────────────────────────────────────────
    if state["outer_center"] and state["outer_r_px"]:
        cx, cy = state["outer_center"]
        r = state["outer_r_px"]
        # Changer la couleur du cercle si defective
        circle_color = (0, 0, 255) if state["yolo_class"] == "damaged" else (0, 0, 255)
        cv2.circle(frame, (cx, cy), r, circle_color, 2)

        od_lbl = f"OD:{state['outer']:.1f}mm"
        if state["teeth"]:
            od_lbl += f" T:{state['teeth']}"
        (tw, th2), _ = cv2.getTextSize(od_lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.putText(frame, od_lbl,
                    (cx - tw // 2, max(cy - r - 8, th2 + 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    circle_color, 2, cv2.LINE_AA)

    if state["inner_center"] and state["inner_r_px"]:
        cx, cy = state["inner_center"]
        r = state["inner_r_px"]
        cv2.circle(frame, (cx, cy), r, (0, 255, 0), 2)

        id_lbl = f"ID:{state['inner']:.1f}mm"
        (tw, th2), _ = cv2.getTextSize(id_lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.putText(frame, id_lbl,
                    (cx - tw // 2, cy + th2 // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 255, 0), 2, cv2.LINE_AA)

    # ── 6. VERDICT LOGIC CORRIGÉE ───────────────────────────────
    # PRIORITÉ ABSOLUE: Si YOLO détecte "damaged" -> DEFECTIF
    # Même si les dimensions sont bonnes, on rejette !
    
    dims_ok = (
        state["outer"] is not None and
        state["inner"] is not None and
        OUTER_RANGE[0] <= state["outer"] <= OUTER_RANGE[1] and
        INNER_RANGE[0] <= state["inner"] <= INNER_RANGE[1]
    )
    state["dims_ok"] = dims_ok
    state["yolo_ok"] = state["yolo_class"] is not None

    # LOGIQUE DE DÉCISION FINALE CORRIGÉE
    if not state["seen"]:
        state["final_ok"] = None
        print("[VERDICT] Waiting for gear...")
    elif state["yolo_class"] == "damaged":
        # PRIORITÉ 1: YOLO dit defective → TOUJOURS DEFECTIF
        state["final_ok"] = False
        print(f"[VERDICT] ❌❌❌ DEFECTIVE GEAR - YOLO detected damaged gear ❌❌❌")
    elif state["yolo_class"] == "healthy":
        # PRIORITÉ 2: YOLO dit healthy → vérifier les dimensions
        if dims_ok:
            state["final_ok"] = True
            print(f"[VERDICT] ✓ GOOD GEAR - Healthy and dimensions OK")
        else:
            state["final_ok"] = False
            print(f"[VERDICT] ❌ DEFECTIVE GEAR - Healthy but dimensions NOK")
    elif state["yolo_class"] == "unknown":
        # PRIORITÉ 3: Unknown → se fier aux dimensions
        if dims_ok:
            state["final_ok"] = True
            print(f"[VERDICT] ✓ GOOD GEAR - Dimensions OK")
        else:
            state["final_ok"] = False
            print(f"[VERDICT] ❌ DEFECTIVE GEAR - Dimensions NOK")
    else:
        state["final_ok"] = None
        print("[VERDICT] No gear detected")

    # ── 7. Afficher le résultat ──────────────────────────────────
    _draw_simple_result(frame, state["final_ok"], state["yolo_class"], 
                       state["outer"], state["inner"], state["teeth"])

    # ── 8. Sidebar avec mise en évidence du défaut ──────────────
    scale_txt = (f"ArUco {state['px']:.2f} px/mm" if state["px"] else "ArUco --")
    
    # Ajouter un indicateur visuel dans la sidebar si defective
    if state["yolo_class"] == "damaged":
        defect_warning = "⚠ DAMAGED ⚠"
    else:
        defect_warning = "---"
    
    rows = [
        {
            "label": "YOLO DETECTION",
            "items": [
                ("Class", state["yolo_class"].upper() if state["yolo_class"] else "--"),
                ("Status", defect_warning),
            ],
        },
        {
            "label": "DIMENSIONS",
            "items": [
                ("OD", f"{state['outer']:.1f}mm" if state["outer"] else "--"),
                ("ID", f"{state['inner']:.1f}mm" if state["inner"] else "--"),
                ("Teeth", str(state["teeth"]) if state["teeth"] else "--"),
            ],
        },
    ]
    
    sidebar = build_sidebar(frame.shape[0], "INSPECTION", rows, state["final_ok"], scale_txt)
    frame = attach_sidebar(frame, sidebar)

    return frame


# ─────────────────────────────────────────────────────────────────
# ENTRY POINTS
# ─────────────────────────────────────────────────────────────────

def run_top_view():
    print("[START] Top view inspection - Version corrigée")
    print("[INFO] PRIORITÉ ABSOLUE: YOLO 'damaged' = REJET IMMÉDIAT")
    model, _ = load_yolo(MODEL_PATH)
    cap = cv2.VideoCapture("http://192.168.100.3:4747/video")
    state = _make_state(model)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        state["frame"] += 1
        frame = process_top(frame, state)
        cv2.imshow("INSPECTION", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


def validate_top_view():
    """Validation sur 100 frames"""
    print("[VALIDATE] Validation en cours...")
    model, _ = load_yolo(MODEL_PATH)
    cap = cv2.VideoCapture("http://192.168.100.3:4747/video")
    state = _make_state(model)

    for i in range(100):
        ret, frame = cap.read()
        if not ret:
            break
        state["frame"] += 1
        process_top(frame, state)
        if i % 20 == 0:
            print(f"[VALIDATE] Frame {i}/100")

    cap.release()

    if state["final_ok"] is True:
        print(f"[RESULT] ✓ GOOD GEAR")
        return "Good", state
    elif state["final_ok"] is False:
        print(f"[RESULT] ❌ DEFECTIVE GEAR")
        return "Defected", state
    else:
        print(f"[RESULT] ? UNCERTAIN")
        return "Uncertain", state


if __name__ == "__main__":
    run_top_view()