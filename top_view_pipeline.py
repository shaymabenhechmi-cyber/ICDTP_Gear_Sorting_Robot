import cv2
import numpy as np
from collections import deque
from scipy.signal import find_peaks
from gear_utils import *

MODEL_PATH = "best_yolo_gear.pt"
YOLO_CONF = 0.35

OUTER_RANGE = (45.0,60.0)
INNER_RANGE = (15.0,25.0)
EXPECTED_TEETH = 24

N_BINS = 512
ACCUM = 30
ALPHA = 0.15


def contour_to_profile(cnt, cx, cy):
    pts = cnt[:,0,:]
    angles = np.arctan2(pts[:,1]-cy, pts[:,0]-cx)
    dists = np.sqrt((pts[:,0]-cx)**2+(pts[:,1]-cy)**2)

    order = np.argsort(angles)
    angles = angles[order]
    dists  = dists[order]

    bins = np.linspace(-np.pi,np.pi,N_BINS+1)
    prof = np.zeros(N_BINS)

    for i in range(N_BINS):
        mask = (angles>=bins[i])&(angles<bins[i+1])
        prof[i] = dists[mask].max() if mask.any() else 0

    return prof


def count_teeth(profile):
    smooth = cv2.GaussianBlur(profile.reshape(-1,1),(7,1),0).flatten()
    peaks,_ = find_peaks(smooth, distance=10)
    return len(peaks)


def process_top(frame,state):

    gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)

    state["px"],corners,ids = update_scale(gray,state["px"])
    draw_aruco(frame,corners,ids)
    px_mm = get_scale(state["px"])

    if state["frame"]%4==0:
        state["yolo"] = run_yolo(state["model"],frame,YOLO_CONF)

    draw_yolo_boxes(frame,state["yolo"])

    blurred = cv2.GaussianBlur(gray,(5,5),0)
    _,th = cv2.threshold(blurred,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)

    contours,_ = cv2.findContours(th,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)

    for cnt in contours:

        area = cv2.contourArea(cnt)
        if area<100:
            continue

        (cx,cy),r = cv2.minEnclosingCircle(cnt)
        diam = (r*2)/px_mm

        if INNER_RANGE[0]<diam<INNER_RANGE[1]:
            state["inner"]=exp_smooth(diam,state["inner"])

        if OUTER_RANGE[0]<diam<OUTER_RANGE[1]:
            state["outer"]=exp_smooth(diam,state["outer"])

            prof = contour_to_profile(cnt,cx,cy)
            state["profiles"].append(prof)

            if len(state["profiles"])>10:
                avg = np.mean(state["profiles"],axis=0)
                state["teeth"]=count_teeth(avg)

        # draw circle
        cv2.circle(frame,(int(cx),int(cy)),int(r),(0,0,255),2)

    # ✅ AFFICHAGE
    if state["outer"]:
        cv2.putText(frame,f"OD: {state['outer']:.1f} mm",(20,40),
                    cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,0,255),2)

    if state["inner"]:
        cv2.putText(frame,f"ID: {state['inner']:.1f} mm",(20,70),
                    cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,0),2)

    if state["teeth"]:
        cv2.putText(frame,f"Teeth: {state['teeth']}",(20,100),
                    cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,255,0),2)

    return frame


def run_top_view():

    model,_ = load_yolo(MODEL_PATH)

    cap = cv2.VideoCapture(0)

    state = {
        "px":None,
        "inner":None,
        "outer":None,
        "teeth":0,
        "profiles":deque(maxlen=ACCUM),
        "yolo":[],
        "frame":0,
        "model":model
    }

    while True:

        ret,frame = cap.read()
        if not ret:
            break

        state["frame"]+=1

        frame = process_top(frame,state)

        cv2.imshow("TOP VIEW",frame)

        k = cv2.waitKey(1)&0xFF
        if k==ord('q'): break

    cap.release()
    cv2.destroyAllWindows()


def validate_top_view():

    model,_ = load_yolo(MODEL_PATH)
    cap = cv2.VideoCapture(0)

    state = {
        "px":None,"inner":None,"outer":None,"teeth":0,
        "profiles":deque(maxlen=ACCUM),
        "yolo":[],"frame":0,"model":model
    }

    for _ in range(100):
        ret,frame = cap.read()
        if not ret: break
        state["frame"]+=1
        process_top(frame,state)

    cap.release()

    if state["outer"] and state["inner"]:
        return "Good", state
    return "Defected", state