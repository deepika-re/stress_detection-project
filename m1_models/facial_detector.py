import cv2
import requests
import time
import numpy as np

BACKEND_URL = 'https://stress-alert-detection-production.up.railway.app/api/facial-data'
# Load OpenCV's built-in face detector
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

def estimate_stress_from_face(frame, faces):
    """
    Simple rule-based stress estimation from face features:
    - No face detected = unknown
    - Eyes detected = check eye openness
    - Frowning approximation using face aspect ratio
    """
    if len(faces) == 0:
        return "No face", 0.0

    for (x, y, w, h) in faces:
        face_roi = frame[y:y+h, x:x+w]
        gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)

        eyes = eye_cascade.detectMultiScale(gray_face, 1.1, 4)
        eye_count = len(eyes)

        # Face aspect ratio — stress/tension can tighten facial muscles
        aspect_ratio = w / h

        stress_score = 0.0
        if eye_count < 2:
            stress_score += 0.3  # squinting = possible stress
        if aspect_ratio < 0.75:
            stress_score += 0.3  # elongated face = tension

        if stress_score >= 0.5:
            emotion = "stressed"
        elif stress_score >= 0.3:
            emotion = "neutral"
        else:
            emotion = "calm"

        return emotion, stress_score

    return "unknown", 0.0

cap = cv2.VideoCapture(0)
print("Facial detector running... Press Q to quit")

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)

    emotion, stress_score = estimate_stress_from_face(frame, faces)

    # Draw rectangles around faces
    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(frame, f"{emotion} ({stress_score:.1f})",
                    (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

    cv2.imshow('Facial Stress Detection', frame)

    # Send to backend every 3 seconds
    try:
        payload = {
            "user_id": 1,
            "dominant_emotion": emotion,
            "stress_score_from_face": stress_score
        }
        requests.post(BACKEND_URL, json=payload, proxies={})
    except:
        pass

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

    time.sleep(3)

cap.release()
cv2.destroyAllWindows()