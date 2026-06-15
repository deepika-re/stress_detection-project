from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import pg8000
import os
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

app = Flask(__name__)
app.secret_key = b'stress_detect_secret_key_fixed_2024'
CORS(app, resources={r"/api/*": {"origins": "*"}})

def get_db():
    db_url = os.environ.get('DATABASE_PUBLIC_URL') or os.environ.get('DATABASE_URL')
    if db_url:
        parsed = urlparse(db_url)
        conn = pg8000.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=parsed.path[1:],
            user=parsed.username,
            password=parsed.password,
            ssl_context=True
        )
    else:
        raise Exception("No database URL found")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        phone TEXT,
        caregiver_email TEXT,
        caregiver_phone TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS readings (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        heart_rate REAL,
        gsr REAL,
        stress_level TEXT,
        timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_session (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS facial_readings (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        dominant_emotion TEXT,
        stress_score REAL,
        timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

def calculate_stress(hr, gsr, facial_score=0.0):
    score = 0
    if hr > 100:
        score += 2
    elif hr > 85:
        score += 1
    if gsr > 600:
        score += 2
    elif gsr > 400:
        score += 1
    if facial_score >= 0.5:
        score += 2
    elif facial_score >= 0.3:
        score += 1
    if score >= 3:
        return "High"
    elif score >= 1:
        return "Medium"
    else:
        return "Low"

def get_latest_facial_score(user_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT stress_score FROM facial_readings WHERE user_id=%s ORDER BY id DESC LIMIT 1', (user_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else 0.0
    except:
        return 0.0

def check_and_alert(user_id, stress_level):
    if stress_level != "High":
        return
    try:
        conn = get_db()
        c = conn.cursor()
        one_min_ago = (datetime.now() - timedelta(minutes=1)).isoformat()
        c.execute('''SELECT COUNT(*) FROM readings
                     WHERE user_id=%s AND stress_level='High' AND timestamp >= %s''',
                  (user_id, one_min_ago))
        count = c.fetchone()[0]
        if count >= 1:
            c.execute('SELECT email, caregiver_email, name FROM users WHERE id=%s', (user_id,))
            user = c.fetchone()
            if user:
                send_email_alert(user[0], user[1], user[2])
        conn.close()
    except Exception as e:
        print(f"Alert error: {e}")

def send_email_alert(user_email, caregiver_email, name):
    sender_email = os.environ.get('EMAIL_USER')
    sender_password = os.environ.get('EMAIL_PASS')
    msg = MIMEText(f"ALERT: {name} has shown HIGH stress levels for over 1 minute. Please check on them immediately.")
    msg['Subject'] = 'Stress Alert - Immediate Attention Needed'
    msg['From'] = sender_email
    recipients = [r for r in [user_email, caregiver_email] if r]
    msg['To'] = ", ".join(recipients)
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipients, msg.as_string())
        print("Alert email sent")
    except Exception as e:
        print(f"Email error: {e}")

# ---------- Page Routes ----------
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html',
                           user_name=session['user_name'],
                           user_id=session['user_id'])

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/logout')
def logout():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM active_session')
        conn.commit()
        conn.close()
    except:
        pass
    session.clear()
    return redirect(url_for('login_page'))

# ---------- Auth API ----------
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    hashed_pw = generate_password_hash(data['password'])
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO users (name, email, password, phone, caregiver_email, caregiver_phone)
                     VALUES (%s, %s, %s, %s, %s, %s)''',
                  (data['name'], data['email'], hashed_pw, data['phone'],
                   data.get('caregiver_email'), data.get('caregiver_phone')))
        conn.commit()
        c.execute('SELECT id FROM users WHERE email=%s', (data['email'],))
        user_id = c.fetchone()[0]
        conn.close()
        return jsonify({"status": "success", "user_id": user_id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name, email, password FROM users WHERE email=%s', (data['email'],))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[3], data['password']):
        session['user_id'] = row[0]
        session['user_name'] = row[1]
        try:
            conn2 = get_db()
            c2 = conn2.cursor()
            c2.execute('DELETE FROM active_session')
            c2.execute('''INSERT INTO active_session (id, user_id, timestamp)
                         VALUES (1, %s, %s)
                         ON CONFLICT (id) DO UPDATE SET user_id=%s, timestamp=%s''',
                       (row[0], datetime.now().isoformat(),
                        row[0], datetime.now().isoformat()))
            conn2.commit()
            conn2.close()
        except Exception as e:
            print(f"Session error: {e}")
        return jsonify({"status": "success", "user_id": row[0], "name": row[1]})
    return jsonify({"status": "error", "message": "Invalid email or password"}), 401

@app.route('/api/active-user')
def active_user():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT user_id FROM active_session WHERE id=1')
        row = c.fetchone()
        conn.close()
        if row:
            return jsonify({"user_id": row[0]})
    except:
        pass
    return jsonify({"user_id": None})

@app.route('/api/whoami')
def whoami():
    return jsonify({
        "session": dict(session),
        "user_id": session.get('user_id'),
        "user_name": session.get('user_name')
    })

@app.route('/api/sensor-data', methods=['POST'])
def receive_data():
    data = request.json
    user_id = data['user_id']
    hr = data.get('heart_rate', 0)
    gsr = data['gsr']
    facial_score = get_latest_facial_score(user_id)
    stress_level = calculate_stress(hr, gsr, facial_score)
    timestamp = datetime.now().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO readings (user_id, heart_rate, gsr, stress_level, timestamp)
                 VALUES (%s, %s, %s, %s, %s)''', (user_id, hr, gsr, stress_level, timestamp))
    conn.commit()
    conn.close()
    check_and_alert(user_id, stress_level)
    return jsonify({"status": "ok", "stress_level": stress_level})

@app.route('/api/latest/<int:user_id>')
def get_latest(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT heart_rate, gsr, stress_level, timestamp
                 FROM readings WHERE user_id=%s ORDER BY id DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"heart_rate": row[0], "gsr": row[1],
                        "stress_level": row[2], "timestamp": row[3]})
    return jsonify({})

@app.route('/api/history/<int:user_id>')
def get_history(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT heart_rate, gsr, stress_level, timestamp
                 FROM readings WHERE user_id=%s ORDER BY id DESC LIMIT 100''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"heart_rate": r[0], "gsr": r[1],
                     "stress_level": r[2], "timestamp": r[3]} for r in rows])

@app.route('/api/facial-data', methods=['POST'])
def facial_data():
    data = request.json
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO facial_readings (user_id, dominant_emotion, stress_score, timestamp)
                 VALUES (%s, %s, %s, %s)''',
              (data['user_id'], data['dominant_emotion'],
               data['stress_score_from_face'], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/all-users')
def all_users():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, name, email, phone, caregiver_email FROM users')
    rows = c.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "name": r[1], "email": r[2],
                     "phone": r[3], "caregiver_email": r[4]} for r in rows])

if __name__ == '__main__':
    app.run(debug=False, port=8080)