import cv2
import numpy as np
import math
from collections import deque
from gear_utils import *

MODEL_PATH = "best_yolo_gear_v3.pt"

EXPECTED_HEIGHT = 20
EXPECTED_HELIX = 15

def estimate_helix(gray,x1,y1,x2,y2):

    roi = gray[y1:y2,x1:x2]
    edges = cv2.Canny(roi,30,100)

    lines = cv2.HoughLinesP(edges,1,np.pi/180,20,20,10)

    if lines is None:
        return None

    angles=[]
    for l in lines:
        x1,y1,x2,y2=l[0]
        dx,dy=x2-x1,y2-y1
        ang = math.degrees(math.atan2(abs(dx),abs(dy)))
        if 3<ang<65:
            angles.append(ang)

    return np.median(angles) if angles else None


def process_side(frame,state):

    gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)

    state["px"],_,_ = update_scale(gray,state["px"])
    px_mm = get_scale(state["px"])

    if state["frame"]%4==0:
        state["yolo"]=run_yolo(state["model"],frame,0.35)

    draw_yolo_boxes(frame,state["yolo"])

    box = best_gear_box(state["yolo"],"healthy_gear","damaged_gear")

    if box:
        x1,y1,x2,y2 = box[:4]

        h = (y2-y1)/px_mm
        state["height"]=exp_smooth(h,state["height"])

        helix = estimate_helix(gray,x1,y1,x2,y2)
        if helix:
            state["helix"]=helix

        # ✅ DRAW HEIGHT
        cv2.line(frame,(x1-15,y1),(x1-15,y2),(255,80,0),2)

    # ✅ DISPLAY
    if state["height"]:
        cv2.putText(frame,f"H: {state['height']:.1f} mm",(20,40),
                    cv2.FONT_HERSHEY_SIMPLEX,0.7,(255,80,0),2)

    if state["helix"]:
        cv2.putText(frame,f"Helix: {state['helix']:.1f} deg",(20,80),
                    cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,180),2)

    return frame


def run_side_view():

    model,_ = load_yolo(MODEL_PATH)
    cap = cv2.VideoCapture(0)

    state={
        "px":None,
        "height":None,
        "helix":None,
        "yolo":[],
        "frame":0,
        "model":model
    }

    while True:
        ret,frame = cap.read()
        if not ret: break

        state["frame"]+=1

        frame = process_side(frame,state)

        cv2.imshow("SIDE VIEW",frame)

        if cv2.waitKey(1)==ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


def validate_side_view():

    model,_ = load_yolo(MODEL_PATH)
    cap = cv2.VideoCapture(0)

    state={
        "px":None,"height":None,"helix":None,
        "yolo":[],"frame":0,"model":model
    }

    for _ in range(100):
        ret,frame = cap.read()
        if not ret: break
        state["frame"]+=1
        process_side(frame,state)

    cap.release()

    if state["height"] and state["helix"]:
        return "Good",state
    return "Defected",state