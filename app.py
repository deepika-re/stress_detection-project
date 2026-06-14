from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = b'stress_detect_secret_key_fixed_2024'
CORS(app, resources={r"/api/*": {"origins": "*"}})

DB = 'stress_data.db'

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        phone TEXT,
        caregiver_email TEXT,
        caregiver_phone TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        heart_rate REAL,
        gsr REAL,
        stress_level TEXT,
        timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS active_session (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

def calculate_stress(hr, gsr):
    score = 0
    if hr > 100:
        score += 2
    elif hr > 85:
        score += 1
    if gsr > 600:
        score += 2
    elif gsr > 400:
        score += 1
    if score >= 3:
        return "High"
    elif score >= 1:
        return "Medium"
    else:
        return "Low"

def check_and_alert(user_id, stress_level):
    print(f">>> check_and_alert called: user={user_id}, stress={stress_level}")
    if stress_level != "High":
        print(">>> Not High, returning")
        return
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    one_min_ago = (datetime.now() - timedelta(minutes=1)).isoformat()
    c.execute('''SELECT COUNT(*) FROM readings
                 WHERE user_id=? AND stress_level='High' AND timestamp >= ?''',
              (user_id, one_min_ago))
    count = c.fetchone()[0]
    print(f">>> High stress count in last 1 min: {count}")
    if count >= 1:
        print(">>> Sending alert...")
        c.execute('SELECT email, caregiver_email, name FROM users WHERE id=?', (user_id,))
        user = c.fetchone()
        print(f">>> User found: {user}")
        if user:
            send_email_alert(user[0], user[1], user[2])
    conn.close()

def send_email_alert(user_email, caregiver_email, name):
    sender_email = "rdeepika0509@gmail.com"
    sender_password = "jsqm dgwv lcxu pgbj"
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
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('DELETE FROM active_session')
    conn.commit()
    conn.close()
    session.clear()
    return redirect(url_for('login_page'))

# ---------- Auth API ----------
@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    hashed_pw = generate_password_hash(data['password'])
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO users (name, email, password, phone, caregiver_email, caregiver_phone)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (data['name'], data['email'], hashed_pw, data['phone'],
                   data.get('caregiver_email'), data.get('caregiver_phone')))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return jsonify({"status": "success", "user_id": user_id})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error", "message": "Email already registered"}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('SELECT id, name, email, password FROM users WHERE email=?', (data['email'],))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[3], data['password']):
        session['user_id'] = row[0]
        session['user_name'] = row[1]
        conn2 = sqlite3.connect(DB)
        c2 = conn2.cursor()
        c2.execute('DELETE FROM active_session')
        c2.execute('INSERT INTO active_session (id, user_id, timestamp) VALUES (1, ?, ?)',
                   (row[0], datetime.now().isoformat()))
        conn2.commit()
        conn2.close()
        return jsonify({"status": "success", "user_id": row[0], "name": row[1]})
    return jsonify({"status": "error", "message": "Invalid email or password"}), 401

# ---------- Active User API ----------
@app.route('/api/active-user')
def active_user():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('SELECT user_id FROM active_session WHERE id=1')
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"user_id": row[0]})
    return jsonify({"user_id": None})

@app.route('/api/whoami')
def whoami():
    return jsonify({
        "session": dict(session),
        "user_id": session.get('user_id'),
        "user_name": session.get('user_name')
    })

# ---------- Sensor API ----------
@app.route('/api/sensor-data', methods=['POST'])
def receive_data():
    data = request.json
    user_id = data['user_id']
    hr = data.get('heart_rate', 0)
    gsr = data['gsr']
    stress_level = calculate_stress(hr, gsr)
    timestamp = datetime.now().isoformat()
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''INSERT INTO readings (user_id, heart_rate, gsr, stress_level, timestamp)
                 VALUES (?, ?, ?, ?, ?)''', (user_id, hr, gsr, stress_level, timestamp))
    conn.commit()
    conn.close()
    check_and_alert(user_id, stress_level)
    return jsonify({"status": "ok", "stress_level": stress_level})

@app.route('/api/latest/<int:user_id>')
def get_latest(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''SELECT heart_rate, gsr, stress_level, timestamp
                 FROM readings WHERE user_id=? ORDER BY id DESC LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return jsonify({"heart_rate": row[0], "gsr": row[1],
                        "stress_level": row[2], "timestamp": row[3]})
    return jsonify({})

@app.route('/api/history/<int:user_id>')
def get_history(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''SELECT heart_rate, gsr, stress_level, timestamp
                 FROM readings WHERE user_id=? ORDER BY id DESC LIMIT 100''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{"heart_rate": r[0], "gsr": r[1],
                     "stress_level": r[2], "timestamp": r[3]} for r in rows])

if __name__ == '__main__':
    app.run(debug=False, port=8080)