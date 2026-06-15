import serial
import serial.tools.list_ports
import requests
import threading
import time
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

RAILWAY_URL = 'https://stress-detection-project.up.railway.app'
BAUD_RATE = 115200

connected = False
current_port = None
ser = None
thread = None

def read_serial():
    global connected, ser
    while connected and ser:
        try:
            line = ser.readline().decode('utf-8').strip()
            print(f"RAW: {line}")
            if line.startswith("HR:"):
                parts = line.split(",")
                hr_value = float(parts[0].split(":")[1].strip())
                gsr_value = float(parts[1].split(":")[1].strip())

                # get active user
                res = requests.get(f'{RAILWAY_URL}/api/active-user', proxies={})
                user_id = res.json().get('user_id')
                if not user_id:
                    continue

                payload = {
                    "user_id": user_id,
                    "heart_rate": hr_value,
                    "gsr": gsr_value
                }
                response = requests.post(f'{RAILWAY_URL}/api/sensor-data',
                                        json=payload, proxies={})
                print(f"Sent: {payload} -> {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

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
        connected = True
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

if __name__ == '__main__':
    app.run(port=8765)