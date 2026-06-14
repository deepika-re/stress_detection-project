import serial
import requests
import time

SERIAL_PORT = '/dev/cu.usbserial-0001'
BAUD_RATE = 115200
BASE_URL = 'http://localhost:8080'

def get_active_user():
    try:
        res = requests.get(f'{BASE_URL}/api/active-user', proxies={})
        data = res.json()
        return data.get('user_id', None)
    except:
        return None

ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
time.sleep(2)

while True:
    try:
        user_id = get_active_user()
        if not user_id:
            print("No active user logged in, waiting...")
            time.sleep(3)
            continue

        line = ser.readline().decode('utf-8').strip()
        if line.startswith("HR:"):
            parts = line.split(",")
            hr_value = parts[0].split(":")[1].strip()
            gsr_value = parts[1].split(":")[1].strip()

            payload = {
                "user_id": user_id,
                "heart_rate": float(hr_value),
                "gsr": float(gsr_value)
            }
            response = requests.post(f'{BASE_URL}/api/sensor-data', json=payload, proxies={})
            print(f"Sent: {payload} -> {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(1)