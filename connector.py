import serial
import serial.tools.list_ports
import requests
import threading
import time
import cv2
import numpy as np
import base64
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

RAILWAY_URL = 'https://stress-detection-project.up.railway.app'
BAUD_RATE = 115200

# Serial globals
connected = False
current_port = None
ser = None
thread = None
cached_user_id = None
last_user_fetch = 0

# Facial detection globals
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade  = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
facial_result  = {"emotion": "unknown", "stress_score": 0.0, "frame_b64": None}
facial_running = False
facial_thread  = None


# ─── Facial helpers ───────────────────────────────────────────────────────────

def estimate_stress_from_face(frame, faces):
    """
    Simple rule-based stress estimation from face features:
      - No face detected  → unknown
      - Eyes detected     → check eye openness
      - Frowning approx   → face aspect ratio
    """
    if len(faces) == 0:
        return "No face", 0.0

    for (x, y, w, h) in faces:
        face_roi  = frame[y:y+h, x:x+w]
        gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)

        eyes      = eye_cascade.detectMultiScale(gray_face, 1.1, 4)
        eye_count = len(eyes)

        aspect_ratio = w / h
        stress_score = 0.0

        if eye_count < 2:
            stress_score += 0.3   # squinting → possible stress
        if aspect_ratio < 0.75:
            stress_score += 0.3   # elongated face → tension

        if stress_score >= 0.5:
            emotion = "stressed"
        elif stress_score >= 0.3:
            emotion = "neutral"
        else:
            emotion = "calm"

        return emotion, round(stress_score, 2)

    return "unknown", 0.0


def run_facial_detection():
    global facial_result, facial_running
    cap = cv2.VideoCapture(0)

    while facial_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)

        emotion, score = estimate_stress_from_face(frame, faces)

        # Draw bounding box + label on frame
        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame, f"{emotion} ({score:.1f})",
                        (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Encode frame → base64 JPEG for browser display
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        frame_b64 = base64.b64encode(buffer).decode('utf-8')

        facial_result = {
            "emotion":      emotion,
            "stress_score": score,
            "frame_b64":    frame_b64
        }

        time.sleep(0.1)   # ~10 fps capture rate

    cap.release()


# ─── Serial reader ────────────────────────────────────────────────────────────

def read_serial():
    global connected, ser, cached_user_id, last_user_fetch
    while connected and ser:
        try:
            line = ser.readline().decode('utf-8').strip()
            if line.startswith("HR:"):
                parts     = line.split(",")
                hr_value  = float(parts[0].split(":")[1].strip())
                gsr_value = float(parts[1].split(":")[1].strip())

                if hr_value == 0 and gsr_value == 0:
                    continue

                # Re-fetch active user at most every 30 s
                now = time.time()
                if cached_user_id is None or (now - last_user_fetch) > 30:
                    res = requests.get(f'{RAILWAY_URL}/api/active-user', proxies={})
                    cached_user_id = res.json().get('user_id')
                    last_user_fetch = now

                if not cached_user_id:
                    continue

                payload = {
                    "user_id":    cached_user_id,
                    "heart_rate": hr_value,
                    "gsr":        gsr_value
                }
                response = requests.post(
                    f'{RAILWAY_URL}/api/sensor-data',
                    json=payload, proxies={}
                )
                print(f"Sent: {payload} -> {response.status_code}")

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)


# ─── Serial routes ────────────────────────────────────────────────────────────

@app.route('/ports')
def list_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return jsonify({"ports": ports})


@app.route('/connect', methods=['POST'])
def connect():
    global connected, current_port, ser, thread
    data = request.json
    port = data.get('port')
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
        time.sleep(2)
        connected    = True
        current_port = port
        thread = threading.Thread(target=read_serial, daemon=True)
        thread.start()
        return jsonify({"status": "connected", "port": port})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/disconnect', methods=['POST'])
def disconnect():
    global connected, ser
    connected = False
    if ser:
        ser.close()
        ser = None
    return jsonify({"status": "disconnected"})


@app.route('/status')
def status():
    return jsonify({"connected": connected, "port": current_port})


# ─── Facial routes ────────────────────────────────────────────────────────────

@app.route('/facial/start', methods=['POST'])
def start_facial():
    global facial_running, facial_thread
    if not facial_running:
        facial_running = True
        facial_thread  = threading.Thread(target=run_facial_detection, daemon=True)
        facial_thread.start()
    return jsonify({"status": "facial_started"})


@app.route('/facial/stop', methods=['POST'])
def stop_facial():
    global facial_running
    facial_running = False
    return jsonify({"status": "facial_stopped"})


@app.route('/facial/score')
def get_facial_score():
    return jsonify({
        "emotion":      facial_result["emotion"],
        "stress_score": facial_result["stress_score"],
        "frame_b64":    facial_result["frame_b64"]
    })


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(port=8765)