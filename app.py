#!/usr/bin/env python3
from flask import Flask, render_template_string, request, redirect, session as flask_session, g
import requests
import re
import sqlite3
import hashlib
import os
import time
import sys
import io
from datetime import datetime
from functools import wraps

# ===== CONFIG =====
ADMIN_USER = "admin"
ADMIN_PASS_HASH = "47b3524dbbdd49ffe4637bf1e1d18df6222bffd672393c3dd6c4e0b3b0e63500"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs.db")
URL_STEP1 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/searchApplicationOnlineIndex.faces"
URL_STEP2 = "https://gate.vision.edu.sa/fc/ui/guest/application_online/generalApplication/index/applicationOnlineIndex.faces"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
FIELD_MAP = {
    "first_name": "myForm:fnames", "father_name": "myForm:fatherNames",
    "grand_name": "myForm:grandNames", "family_name": "myForm:familyNames",
    "capabilities": "myForm:capabilities", "tah_score": "myForm:tahselMark",
}

app = Flask(__name__)
app.secret_key = os.urandom(32).hex()


# ===== DATABASE =====
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                national_id TEXT,
                full_name TEXT,
                first_name TEXT,
                father_name TEXT,
                grand_name TEXT,
                family_name TEXT,
                capabilities TEXT,
                tah_score TEXT,
                success INTEGER DEFAULT 0,
                ip TEXT,
                user_agent TEXT,
                device TEXT,
                browser TEXT,
                os TEXT,
                referer TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                ip TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                user_agent TEXT,
                device TEXT,
                browser TEXT,
                os TEXT,
                page TEXT,
                referer TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS blocked_ids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                national_id TEXT UNIQUE,
                reason TEXT,
                blocked_by TEXT,
                timestamp TEXT
            );
        """)
        db.commit()

init_db()


# ===== VISIT TRACKING =====
def parse_user_agent(ua):
    ua = ua or ""
    device = "Desktop"
    if any(x in ua.lower() for x in ["mobile", "android", "iphone", "ipad"]):
        device = "Mobile"
    browser = "Unknown"
    if "Chrome/" in ua and "Edg/" not in ua: browser = "Chrome"
    elif "Firefox/" in ua: browser = "Firefox"
    elif "Safari/" in ua and "Chrome" not in ua: browser = "Safari"
    elif "Edg/" in ua: browser = "Edge"
    os_ = "Unknown"
    if "Windows" in ua: os_ = "Windows"
    elif "Linux" in ua and "Android" not in ua: os_ = "Linux"
    elif "Mac" in ua: os_ = "macOS"
    elif "Android" in ua: os_ = "Android"
    elif "iPhone" in ua or "iPad" in ua: os_ = "iOS"
    return device, browser, os_

@app.before_request
def track_visit():
    if request.path.startswith("/api/") or request.path.startswith("/static/"):
        return
    ua = request.headers.get("User-Agent", "")
    device, browser, os_ = parse_user_agent(ua)
    try:
        db = get_db()
        db.execute("INSERT INTO visits (ip, user_agent, device, browser, os, page, referer, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (request.remote_addr or "0.0.0.0", ua, device, browser, os_,
                    request.path, request.referrer or "", datetime.now().isoformat()))
        db.commit()
    except:
        pass


# ===== SCRAPER =====
def extract_view_state(html):
    m = re.search(r'<input[^>]*name="(?:javax|jakarta)\.faces\.ViewState"[^>]*value="([^"]*)"', html, re.I)
    return m.group(1) if m else ""

def extract_value(html, field_name):
    m = re.search(r'<input[^>]*(?:id|name)="' + re.escape(field_name) + r'"[^>]*value="([^"]*)"', html, re.I)
    return m.group(1).strip() if m and m.group(1).strip() else None

def scrape(national_id, ip, user_agent):
    sess = requests.Session()
    sess.headers.update(HEADERS)

    sess.get(URL_STEP1, timeout=30)
    r2 = sess.get(URL_STEP2, timeout=30)
    r2.raise_for_status()

    view_state = extract_view_state(r2.text)
    r3 = sess.post(URL_STEP2, data={
        "javax.faces.ViewState": view_state, "myForm": "myForm",
        "myForm:nationalNo": national_id, "myForm:retriveQiyasAPIData": "myForm:retriveQiyasAPIData",
    }, timeout=30)
    r3.raise_for_status()

    result = {}
    for key, field in FIELD_MAP.items():
        val = extract_value(r3.text, field)
        if val:
            result[key] = val

    name_parts = []
    for p in ["first_name", "father_name", "grand_name", "family_name"]:
        if p in result:
            name_parts.append(result[p])
    if name_parts:
        result["full_name"] = " ".join(name_parts)

    success = len(result) >= 2

    device, browser, os_ = parse_user_agent(user_agent)

    # Save to database
    db = get_db()
    db.execute("""
        INSERT INTO searches (national_id, full_name, first_name, father_name, grand_name, family_name,
                              capabilities, tah_score, success, ip, user_agent, device, browser, os, referer, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        national_id, result.get("full_name", ""), result.get("first_name", ""),
        result.get("father_name", ""), result.get("grand_name", ""), result.get("family_name", ""),
        result.get("capabilities", ""), result.get("tah_score", ""),
        1 if success else 0, ip, user_agent, device, browser, os_,
        request.referrer or "", datetime.now().isoformat()
    ))
    db.commit()

    return result, success


# ===== DECORATORS =====
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not flask_session.get("admin_logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated


# ===== PAGES =====
MAIN_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>الاستعلام عن النتائج</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;500;600;700;800;900&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Cairo', 'Segoe UI', Arial, sans-serif;
    background: #000;
    min-height: 100vh; display: flex;
    justify-content: center; align-items: center;
    padding: 20px; position: relative; overflow-x: hidden;
}
body::before {
    content: ''; position: fixed; inset: 0;
    background: radial-gradient(circle at 50% 0%, rgba(59,130,246,0.08) 0%, transparent 60%);
    z-index: 0;
}
.orb { position: fixed; border-radius: 50%; filter: blur(100px); z-index: 0; animation: orbFloat 25s ease-in-out infinite; }
.orb:nth-child(1) { width: 500px; height: 500px; background: rgba(59,130,246,0.08); top: -150px; right: -100px; }
.orb:nth-child(2) { width: 400px; height: 400px; background: rgba(6,182,212,0.06); bottom: -120px; left: -100px; animation-delay: -8s; }
.orb:nth-child(3) { width: 250px; height: 250px; background: rgba(59,130,246,0.05); top: 40%; left: 5%; animation-delay: -16s; }
@keyframes orbFloat {
    0%,100% { transform:translate(0,0) scale(1); }
    25% { transform:translate(40px,-50px) scale(1.05); }
    50% { transform:translate(-20px,30px) scale(0.95); }
    75% { transform:translate(30px,40px) scale(1.02); }
}
.container {
    position: relative; z-index: 1;
    background: rgba(255,255,255,0.04);
    backdrop-filter: blur(40px);
    -webkit-backdrop-filter: blur(40px);
    border-radius: 32px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.06);
    padding: 50px 45px; width: 100%; max-width: 520px;
    transition: all 0.4s cubic-bezier(0.175,0.885,0.32,1.275);
}
.container:hover { transform: translateY(-3px); }
@keyframes containerFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.container{animation:splashContainer 0.6s ease 1s both,containerFloat 6s ease-in-out infinite 1.6s}
@keyframes splashContainer{from{opacity:0;transform:translateY(20px) scale(0.95)}to{opacity:1;transform:translateY(0) scale(1)}}
.greeting{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:12px;animation:greetingFade 0.8s ease both}
.wink-icon{width:44px;height:44px;object-fit:contain;border-radius:50%;animation:winkAnim 2s ease-in-out infinite}
@keyframes winkAnim{0%,100%{transform:scale(1)}50%{transform:scale(1.1) rotate(-3deg)}}
.greeting-text{font-size:22px;font-weight:700;color:#fff;letter-spacing:1px}
.greeting-dots{display:inline-block;animation:dotsAnim 1.5s ease-in-out infinite;color:#3b82f6;font-weight:900}
@keyframes dotsAnim{0%,100%{opacity:1}50%{opacity:0.3}}
@keyframes greetingFade{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
.icon-wrap { width: 70px; height: 70px; margin: 0 auto 22px; position: relative; display: flex; align-items: center; justify-content: center; }
@keyframes logoAnim{0%,100%{transform:scale(1) rotate(0deg);filter:drop-shadow(0 0 4px rgba(59,130,246,0.3))}25%{transform:scale(1.1) rotate(-5deg);filter:drop-shadow(0 0 12px rgba(59,130,246,0.5))}75%{transform:scale(1.1) rotate(5deg);filter:drop-shadow(0 0 12px rgba(6,182,212,0.5))}}
.icon-wrap svg { width: 36px; height: 36px; color: #3b82f6; animation:logoAnim 3s ease-in-out infinite; }
h1 { font-size:26px; font-weight:900; color:#fff; margin-bottom:6px; text-align:center; }
h1::after { content:''; display:block; width:50px; height:3px; background:#3b82f6; border-radius:3px; margin:10px auto 0; animation:lineGrow 3s ease-in-out infinite; }
@keyframes lineGrow{0%,100%{width:50px;opacity:1}50%{width:80px;opacity:0.7}}
.subtitle { color:#a0aec0; font-size:14px; margin:6px 0 32px; text-align:center; }
.subtitle strong { color:#3b82f6; font-weight:700; }
.input-group { position:relative; margin-bottom:20px; }
.input-group .input-icon { position:absolute; left:18px; top:50%; transform:translateY(-50%); opacity:0.25; pointer-events:none; color:#6b7280; }
label { display:block; font-weight:600; color:#cbd5e0; margin-bottom:10px; font-size:13px; }
input[type="text"] {
    width:100%; padding:16px 18px 16px 50px;
    border:1px solid rgba(255,255,255,0.1); border-radius:16px;
    font-size:20px; font-family:'Cairo',sans-serif; font-weight:700;
    letter-spacing:3px; direction:ltr; text-align:center;
    transition:all 0.35s cubic-bezier(0.4,0,0.2,1);
    background:rgba(255,255,255,0.05); color:#fff;
}
input[type="text"]:hover { border-color:rgba(59,130,246,0.3); background:rgba(255,255,255,0.07); }
input[type="text"]:focus { outline:none; border-color:#3b82f6; box-shadow:0 0 0 4px rgba(59,130,246,0.15); background:rgba(255,255,255,0.08); animation:none; }
@keyframes inputPulse{0%,100%{border-color:rgba(255,255,255,0.1)}50%{border-color:rgba(59,130,246,0.2)}}
input[type="text"]{animation:inputPulse 3s ease-in-out infinite}
input[type="text"]::placeholder { color:#6b7280; font-weight:400; font-size:14px; letter-spacing:0; animation:placeholderPulse 2s ease-in-out infinite; }
@keyframes placeholderPulse{0%,100%{opacity:0.6}50%{opacity:1}}
.btn-wrap { position:relative; margin-top:8px; border-radius:16px; overflow:hidden; }
.btn-wrap::before { content:''; position:absolute; inset:0; background:linear-gradient(135deg,#2563eb,#3b82f6,#06b6d4); border-radius:16px; }
button {
    position:relative; z-index:1; width:100%; padding:16px;
    background:transparent; color:#fff; border:none; border-radius:16px;
    font-size:16px; font-weight:700; font-family:'Cairo',sans-serif;
    cursor:pointer; transition:all 0.3s;
    display:flex; align-items:center; justify-content:center; gap:8px;
}
@keyframes btnGlow{0%,100%{box-shadow:0 0 8px rgba(59,130,246,0.3)}50%{box-shadow:0 0 20px rgba(59,130,246,0.5)}}
button{animation:btnGlow 3s ease-in-out infinite}
button:hover { transform:scale(1.015); animation:none; }
button:active { transform:scale(0.985); }
button:disabled { opacity:0.6; cursor:not-allowed; transform:none !important; animation:none; }
.error {
    display:flex; align-items:center; gap:10px;
    background:rgba(239,68,68,0.1);
    color:#f87171; padding:16px 20px; border-radius:16px;
    margin-top:22px; font-size:14px; text-align:center;
    font-weight:500; border:1px solid rgba(239,68,68,0.2);
    animation:slideUp 0.4s ease;
}
@keyframes slideUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
.result {
    margin-top:30px; background:rgba(255,255,255,0.04);
    backdrop-filter:blur(20px); -webkit-backdrop-filter:blur(20px);
    border-radius:24px; padding:28px;
    border:1px solid rgba(255,255,255,0.06);
    animation:slideUp 0.5s ease; position:relative; overflow:hidden;
}
.result::before { content:''; position:absolute; top:0; left:0; right:0; height:3px; background:linear-gradient(90deg,#2563eb,#3b82f6,#06b6d4); }
.result h2 { font-size:24px; font-weight:900; color:#fff; text-align:center; margin-bottom:22px; padding-bottom:18px; border-bottom:1px solid rgba(255,255,255,0.06); }
.name-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px 20px; }
.result-item { display:flex; justify-content:space-between; align-items:center; padding:10px 8px; font-size:14px; border-radius:10px; }
.result-item .label { color:#a0aec0; font-weight:500; font-size:13px; }
.result-item .value { color:#fff; font-weight:700; }
.divider { height:1px; background:linear-gradient(90deg,transparent,rgba(59,130,246,0.1),transparent); margin:12px 0; }
.score-section { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }
.score-card { border-radius:18px; padding:18px 14px; text-align:center; transition:all 0.3s ease; position:relative; overflow:hidden; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); animation:cardFadeIn 0.6s ease forwards; opacity:0; }
.score-card:nth-child(1){animation-delay:0.2s}
.score-card:nth-child(2){animation-delay:0.4s}
@keyframes cardFadeIn{from{opacity:0;transform:translateY(15px)}to{opacity:1;transform:translateY(0)}}
.score-card:hover { transform:translateY(-3px); border-color:rgba(59,130,246,0.2); }
.score-card .score-label { font-size:12px; font-weight:600; color:#a0aec0; margin-bottom:6px; }
.score-card .score-value { font-size:32px; font-weight:900; color:#fff; }
.score-card.tahsili .score-value { color:#22c55e; }
.score-card.tahsili .score-value.no-score,
.score-card.capabilities .score-value.no-score { color:#fff; }
.loading { display:none; text-align:center; margin-top:22px; color:#3b82f6; font-weight:600; font-size:14px; animation:pulse 1.5s ease-in-out infinite; }
.loading.active { display:block; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
.spinner { display:inline-block; width:20px; height:20px; border:2.5px solid rgba(255,255,255,0.15); border-top-color:#fff; border-radius:50%; animation:spin 0.7s linear infinite; vertical-align:middle; flex-shrink:0; }
@keyframes spin { to { transform:rotate(360deg); } }
.footer { text-align:center; margin-top:24px; font-size:12px; color:#6b7280; }
.footer a{color:#6b7280}
.footer a:hover{color:#3b82f6}
.heart-glow{display:inline-block;color:#ef4444;animation:heartBeat 1.5s ease-in-out infinite}
@keyframes heartBeat{0%,100%{transform:scale(1);text-shadow:0 0 4px rgba(239,68,68,0.3)}50%{transform:scale(1.2);text-shadow:0 0 16px rgba(239,68,68,0.6)}}
@media (max-width:768px) {
    .container { padding:35px 25px; max-width:100%; }
    h1 { font-size:23px; }
    .input-group .floating-label { font-size:12px; }
}
@media (max-width:480px) {
    body { padding:12px; }
    .container { padding:24px 16px; border-radius:24px; }
    h1 { font-size:20px; }
    .subtitle { font-size:13px; margin:4px 0 24px; }
    .icon-wrap { width:56px; height:56px; margin-bottom:16px; }
    .icon-wrap svg { width:26px; height:26px; }
    input[type="text"] { font-size:18px; padding:14px 14px 14px 40px; letter-spacing:2px; }
    .input-group .floating-label { font-size:11px; right:14px; }
    button { padding:14px; font-size:15px; }
    .score-section { grid-template-columns:1fr; }
    .result { padding:18px; margin-top:20px; }
    .result h2 { font-size:20px; }
    .score-card { padding:14px 10px; }
    .score-card .score-value { font-size:26px; }
    .score-section { gap:10px; }
    .orb:nth-child(1) { width:250px; height:250px; top:-80px; right:-80px; filter:blur(40px); }
    .orb:nth-child(2) { width:200px; height:200px; bottom:-80px; left:-80px; filter:blur(40px); }
    .orb:nth-child(3) { width:150px; height:150px; filter:blur(40px); }
    .footer { font-size:11px; margin-top:18px; }
}
@media (min-width:1024px) {
    .container { padding:55px 50px; max-width:560px; }
    h1 { font-size:28px; }
}
</style>
</head>
<body id="bodyTag">
<div id="splash"><div class="splash-inner"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="splash-logo"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg></div></div>
<style>
#splash{position:fixed;inset:0;z-index:9999;background:#000;display:flex;align-items:center;justify-content:center;animation:splashOut 0.5s ease 1.2s forwards}
.splash-inner{display:flex;align-items:center;justify-content:center;animation:splashScale 0.6s ease}
.splash-logo{width:60px;height:60px;animation:splashLogo 0.8s ease}
@keyframes splashScale{0%{transform:scale(0.3);opacity:0}50%{transform:scale(1.15)}100%{transform:scale(1);opacity:1}}
@keyframes splashLogo{0%{transform:rotate(-30deg) scale(0)}50%{transform:rotate(10deg) scale(1.2)}100%{transform:rotate(0deg) scale(1)}}
@keyframes splashOut{0%{opacity:1}100%{opacity:0;pointer-events:none}}
</style>
<script>if(sessionStorage.getItem('splashShown')){document.getElementById('splash').style.display='none';document.getElementById('container').style.opacity='1'}else{sessionStorage.setItem('splashShown','1')}</script>
<div class="orb"></div><div class="orb"></div><div class="orb"></div>
<div class="container" id="container">
<div class="greeting">
<img src="/static/winking.png" class="wink-icon" alt="">
<span class="greeting-text">أهلا <span class="greeting-dots">..</span></span>
</div>
<h1>الاستعلام عن النتائج</h1>
<p class="subtitle">أدخل <strong>رقم الهوية</strong> للاستعلام عن الاسم ودرجات القدرات والتحصيلي</p>
<form method="post" id="searchForm">
<label for="national_id">رقم الهوية</label>
<div class="input-group">
<input type="text" id="national_id" name="national_id" required placeholder="أدخل 10 أرقام" value="{{ national_id or '' }}" maxlength="10" pattern="\d{10}" title="الرجاء إدخال 10 أرقام" autofocus>
<svg class="input-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M16 2v4M8 2v4"/><path d="M2 10h20"/></svg>
</div>
<div class="btn-wrap">
<button type="submit" id="submitBtn"><span id="btnText">بحث</span><span class="spinner" id="btnSpinner" style="display:none"></span></button>
</div>
</form>
<div class="loading" id="loading">جاري البحث عن البيانات...</div>
{% if error %}<div class="error"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>{{ error }}</div>{% endif %}
{% if result %}
<div class="result">
<h2>{{ result.get('full_name','النتيجة') }}</h2>

<div class="score-section">
<div class="score-card capabilities"><div class="score-label">القدرات</div><div class="score-value {{ 'no-score' if not has_cap else '' }}">{{ result.get('capabilities','—') }}</div></div>
<div class="score-card tahsili"><div class="score-label">التحصيلي</div><div class="score-value {{ 'no-score' if not has_tah else '' }}">{{ result.get('tah_score','—') }}</div></div>
</div>
</div>
{% endif %}
<div class="footer">
Developed By vovo <span class="heart-glow">&#10084;</span>
<a href="https://www.instagram.com/tnnd" target="_blank" style="text-decoration:none;color:inherit;display:inline-flex;align-items:center;gap:4px;margin-right:6px">
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></svg>
</a>
</div>
</div>
<script>
document.getElementById('searchForm')?.addEventListener('submit',function(){
document.getElementById('submitBtn').disabled=true;
document.getElementById('btnText').style.display='none';
document.getElementById('btnSpinner').style.display='inline-block';
document.getElementById('loading').classList.add('active');
});
</script>
</body>
</html>"""

ADMIN_LOGIN_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>دخول الأدمن</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Cairo',sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;display:flex;justify-content:center;align-items:center;padding:20px}
.card{background:#fff;border-radius:24px;padding:40px;width:100%;max-width:400px;box-shadow:0 20px 60px rgba(0,0,0,0.3)}
h1{text-align:center;font-size:24px;font-weight:800;color:#1e1b4b;margin-bottom:8px}
p{text-align:center;color:#6b7280;font-size:14px;margin-bottom:28px}
label{display:block;font-weight:600;color:#374151;margin-bottom:6px;font-size:13px}
input[type="text"],input[type="password"]{width:100%;padding:12px 16px;border:2px solid #e5e7eb;border-radius:12px;font-size:15px;font-family:'Cairo',sans-serif;transition:all 0.3s;margin-bottom:16px}
input:focus{outline:none;border-color:#4f46e5;box-shadow:0 0 0 4px rgba(79,70,229,0.1)}
button{width:100%;padding:12px;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;font-family:'Cairo',sans-serif;cursor:pointer;transition:all 0.3s}
button:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(79,70,229,0.3)}
.error{background:#fef2f2;color:#dc2626;padding:10px;border-radius:10px;margin-bottom:16px;font-size:13px;text-align:center}
</style></head>
<body>
<div class="card">
<h1>لوحة التحكم</h1>
<p>الرجاء تسجيل الدخول</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post">
<label>اسم المستخدم</label>
<input type="text" name="username" required autofocus>
<label>كلمة المرور</label>
<input type="password" name="password" required>
<button type="submit">دخول</button>
</form>
</div></body></html>"""

ADMIN_DASHBOARD_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>لوحة التحكم</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Cairo',sans-serif;background:#f3f4f6;padding:20px;color:#1e1b4b}
.header{background:linear-gradient(135deg,#1e1b4b,#4f46e5);border-radius:20px;padding:25px 30px;margin-bottom:25px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
.header h1{color:#fff;font-size:22px;font-weight:800}
.header span{color:rgba(255,255,255,0.7);font-size:14px}
.header .online-badge{display:inline-flex;align-items:center;gap:6px;background:rgba(34,197,94,0.2);color:#4ade80;padding:5px 14px;border-radius:20px;font-size:13px;font-weight:700}
.header .online-badge .dot{width:8px;height:8px;background:#4ade80;border-radius:50%;animation:livePulse 1.5s ease-in-out infinite}
@keyframes livePulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.5;transform:scale(0.8)}}
.header a{background:rgba(255,255,255,0.15);color:#fff;padding:8px 18px;border-radius:10px;text-decoration:none;font-weight:600;font-size:13px;transition:all 0.3s}
.header a:hover{background:rgba(255,255,255,0.25)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:15px;margin-bottom:25px}
.stat-card{background:#fff;border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.stat-card .num{font-size:28px;font-weight:900;color:#4f46e5}
.stat-card .lbl{font-size:13px;color:#6b7280;font-weight:500;margin-top:4px}
.stat-card.online{background:linear-gradient(145deg,#f0fdf4,#dcfce7);border:1px solid rgba(34,197,94,0.15)}
.stat-card.online .num{color:#16a34a}
.section-title{font-size:18px;font-weight:800;color:#1e1b4b;margin-bottom:15px;display:flex;align-items:center;gap:8px}
.section-title .live-dot{width:10px;height:10px;background:#22c55e;border-radius:50%;animation:livePulse 1.5s ease-in-out infinite}
.live-visitors{background:#fff;border-radius:16px;padding:20px;margin-bottom:25px;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.visitor-item{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #f3f4f6;transition:all 0.3s;border-radius:10px}
.visitor-item:last-child{border-bottom:none}
.visitor-item:hover{background:#f8f7ff}
.visitor-item .ip{font-weight:700;color:#1e1b4b;font-size:13px;direction:ltr}
.visitor-item .details{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.visitor-item .details span{font-size:11px;padding:2px 8px;border-radius:6px;background:#f3f4f6;color:#6b7280;font-weight:600}
.visitor-item .time{font-size:11px;color:#9ca3af;direction:ltr}
.filters{background:#fff;border-radius:16px;padding:18px 20px;margin-bottom:20px;display:flex;gap:12px;flex-wrap:wrap;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.filters label{font-weight:600;font-size:13px}
.filters input,.filters select{padding:8px 12px;border:2px solid #e5e7eb;border-radius:10px;font-family:'Cairo',sans-serif;font-size:13px}
.filters input:focus,.filters select:focus{outline:none;border-color:#4f46e5}
.filters button{padding:8px 20px;background:#4f46e5;color:#fff;border:none;border-radius:10px;font-weight:600;font-family:'Cairo',sans-serif;cursor:pointer}
.table-wrap{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
table{width:100%;border-collapse:collapse;font-size:13px}
thead{background:#f9fafb}
th{padding:14px 12px;text-align:center;font-weight:700;color:#374151;border-bottom:2px solid #e5e7eb;white-space:nowrap}
td{padding:12px;text-align:center;border-bottom:1px solid #f3f4f6;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:hover{background:#f8f7ff}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700}
.badge.yes{background:#dcfce7;color:#16a34a}
.badge.no{background:#fef2f2;color:#dc2626}
.pagination{display:flex;justify-content:center;align-items:center;gap:8px;padding:18px}
.pagination a{padding:6px 14px;border:1px solid #e5e7eb;border-radius:8px;text-decoration:none;color:#374151;font-weight:600;font-size:13px}
.pagination a:hover{background:#4f46e5;color:#fff;border-color:#4f46e5}
.pagination .active{background:#4f46e5;color:#fff;border-color:#4f46e5}
.pagination .disabled{opacity:0.4;pointer-events:none}
.empty{padding:40px;text-align:center;color:#9ca3af;font-size:15px}
@media(max-width:768px){
    .filters{flex-direction:column}
    .table-wrap{overflow-x:auto}
    th,td{font-size:12px;padding:8px 6px}
}
</style></head>
<body>
<div class="header">
<div>
<h1>لوحة التحكم</h1>
<span>سجل عمليات البحث</span>
</div>
<div style="display:flex;gap:10px;align-items:center">
<span class="online-badge" id="onlineBadge"><span class="dot"></span><span id="onlineCount">0</span> متصل</span>
<span style="color:rgba(255,255,255,0.7);font-size:13px">{{ username }}</span>
<a href="/admin/blocks">الحظر</a>
<a href="/admin/logout">تسجيل خروج</a>
</div>
</div>

<div class="stats">
<div class="stat-card"><div class="num">{{ total }}</div><div class="lbl">إجمالي العمليات</div></div>
<div class="stat-card"><div class="num">{{ success_count }}</div><div class="lbl">ناجحة</div></div>
<div class="stat-card"><div class="num">{{ fail_count }}</div><div class="lbl">فاشلة</div></div>
<div class="stat-card"><div class="num">{{ unique_ids }}</div><div class="lbl">هويات مختلفة</div></div>
<div class="stat-card online"><div class="num" id="visitorTotal">0</div><div class="lbl">إجمالي الزوار</div></div>
<div class="stat-card online"><div class="num" id="visitorUnique">0</div><div class="lbl">زوار فريدين</div></div>
</div>

<div class="live-visitors" id="liveSection">
<div class="section-title"><span class="live-dot"></span>المتصلون الآن (آخر 5 دقائق)</div>
<div id="visitorList">
<div class="empty" style="padding:20px">جاري التحميل...</div>
</div>
</div>

<form class="filters" method="get">
<label>رقم الهوية</label>
<input type="text" name="search_id" value="{{ search_id or '' }}" placeholder="بحث..." style="width:140px">
<label>التاريخ من</label>
<input type="date" name="date_from" value="{{ date_from or '' }}">
<label>إلى</label>
<input type="date" name="date_to" value="{{ date_to or '' }}">
<label>الحالة</label>
<select name="status"><option value="">الكل</option><option value="1" {{ 'selected' if status=='1' }}>ناجح</option><option value="0" {{ 'selected' if status=='0' }}>فاشل</option></select>
<button type="submit">تصفية</button>
</form>

<div class="table-wrap">
{% if rows %}
<table>
<thead><tr>
<th>#</th><th>الهوية</th><th>الاسم</th><th>القدرات</th><th>التحصيلي</th><th>الحالة</th><th>IP</th><th>الجهاز</th><th>المتصفح</th><th>نظام التشغيل</th><th>التاريخ</th>
</tr></thead>
<tbody>
{% for r in rows %}
<tr>
<td>{{ r.id }}</td>
<td dir="ltr">{{ r.national_id }}</td>
<td>{{ r.full_name or '-' }}</td>
<td>{{ r.capabilities or '-' }}</td>
<td>{{ r.tah_score or '-' }}</td>
<td><span class="badge {{ 'yes' if r.success else 'no' }}">{{ 'ناجح' if r.success else 'فاشل' }}</span></td>
<td dir="ltr" style="font-size:12px">{{ r.ip or '-' }}</td>
<td>{{ r.device or '-' }}</td>
<td>{{ r.browser or '-' }}</td>
<td>{{ r.os or '-' }}</td>
<td style="font-size:11px;direction:ltr">{{ r.timestamp[:19] if r.timestamp else '-' }}</td>
</tr>
{% endfor %}
</tbody>
</table>
<div class="pagination">
<a class="{{ 'disabled' if page<=1 }}" href="?page={{ page-1 }}&search_id={{ search_id or '' }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&status={{ status or '' }}">السابق</a>
{% for p in range(1, total_pages+1) %}
<a class="{{ 'active' if p==page }}" href="?page={{ p }}&search_id={{ search_id or '' }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&status={{ status or '' }}">{{ p }}</a>
{% endfor %}
<a class="{{ 'disabled' if page>=total_pages }}" href="?page={{ page+1 }}&search_id={{ search_id or '' }}&date_from={{ date_from or '' }}&date_to={{ date_to or '' }}&status={{ status or '' }}">التالي</a>
</div>
{% else %}
<div class="empty">لا توجد نتائج</div>
{% endif %}
</div>

<script>
function loadOnline(){
fetch('/api/active-connections').then(r=>r.json()).then(d=>{
document.getElementById('onlineCount').textContent=d.online;
let h='';
if(d.visitors.length){
d.visitors.forEach(v=>{
let t=v.timestamp||'';
if(t.length>19)t=t.substring(11,19);
else if(t.length>10)t=t.substring(11,16);
h+='<div class="visitor-item"><span class="ip">'+v.ip+'</span><div class="details">'+
'<span>'+v.device+'</span><span>'+v.browser+'</span><span>'+v.os+'</span><span>'+v.page+'</span>'+
'</div><span class="time">'+t+'</span></div>';
});
}else{h='<div class="empty" style="padding:20px">لا يوجد زوار نشطين</div>';}
document.getElementById('visitorList').innerHTML=h;
}).catch(()=>{});
fetch('/api/visitors').then(r=>r.json()).then(d=>{
document.getElementById('visitorTotal').textContent=d.total_visits;
document.getElementById('visitorUnique').textContent=d.unique_visitors;
}).catch(()=>{});
}
loadOnline();
setInterval(loadOnline,5000);
</script>
</body></html>"""


# ===== ROUTES =====
@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    national_id = request.form.get("national_id", "")

    if request.method == "POST" and national_id:
        db = get_db()
        blocked = db.execute("SELECT * FROM blocked_ids WHERE national_id = ?", (national_id,)).fetchone()
        if blocked:
            error = "رقم الهوية محظور"
        else:
            try:
                result_data, success = scrape(
                    national_id,
                    request.remote_addr or "0.0.0.0",
                    request.headers.get("User-Agent", "")
                )
                if not result_data:
                    error = "لم يتم العثور على نتائج"
                else:
                    result = result_data
            except Exception as e:
                error = f"خطأ في الاتصال: {str(e)[:60]}"

    has_cap = bool(result and result.get('capabilities') and result['capabilities'].strip() not in ('—', '-', ''))
    has_tah = bool(result and result.get('tah_score') and result['tah_score'].strip() not in ('—', '-', ''))
    return render_template_string(MAIN_HTML, result=result, error=error, national_id=national_id,
                                   has_cap=has_cap, has_tah=has_tah)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == ADMIN_USER and hashlib.sha256(p.encode()).hexdigest() == ADMIN_PASS_HASH:
            flask_session["admin_logged_in"] = True
            flask_session["admin_user"] = u
            db = get_db()
            db.execute("INSERT INTO admin_logs (action, ip, timestamp) VALUES (?, ?, ?)",
                       ("login", request.remote_addr or "", datetime.now().isoformat()))
            db.commit()
            return redirect("/admin")
        error = "اسم المستخدم أو كلمة المرور غير صحيحة"
    return render_template_string(ADMIN_LOGIN_HTML, error=error)


@app.route("/admin/logout")
def admin_logout():
    flask_session.pop("admin_logged_in", None)
    flask_session.pop("admin_user", None)
    return redirect("/admin/login")


@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()

    # Stats
    total = db.execute("SELECT COUNT(*) as c FROM searches").fetchone()["c"]
    success_count = db.execute("SELECT COUNT(*) as c FROM searches WHERE success=1").fetchone()["c"]
    fail_count = db.execute("SELECT COUNT(*) as c FROM searches WHERE success=0").fetchone()["c"]
    unique_ids = db.execute("SELECT COUNT(DISTINCT national_id) as c FROM searches").fetchone()["c"]

    # Filters
    search_id = request.args.get("search_id", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    status_filter = request.args.get("status", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 50

    query = "SELECT * FROM searches WHERE 1=1"
    params = []
    if search_id:
        query += " AND national_id LIKE ?"
        params.append(f"%{search_id}%")
    if date_from:
        query += " AND timestamp >= ?"
        params.append(date_from + "T00:00:00")
    if date_to:
        query += " AND timestamp <= ?"
        params.append(date_to + "T23:59:59")
    if status_filter in ("0", "1"):
        query += " AND success = ?"
        params.append(int(status_filter))

    total_count = db.execute(query.replace("SELECT *", "SELECT COUNT(*) as c"), params).fetchone()["c"]
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    rows = db.execute(query, params).fetchall()

    visitor_total = db.execute("SELECT COUNT(*) as c FROM visits").fetchone()["c"]
    visitor_unique = db.execute("SELECT COUNT(DISTINCT ip) as c FROM visits").fetchone()["c"]

    return render_template_string(ADMIN_DASHBOARD_HTML,
        rows=rows, total=total, success_count=success_count, fail_count=fail_count,
        unique_ids=unique_ids, page=page, total_pages=total_pages,
        search_id=search_id, date_from=date_from, date_to=date_to, status=status_filter,
        username=flask_session.get("admin_user", "admin"),
        visitor_total=visitor_total, visitor_unique=visitor_unique
    )


# ===== BLOCK ROUTES =====
@app.route("/admin/blocks", methods=["GET", "POST"])
@login_required
def admin_blocks():
    db = get_db()
    msg = ""
    if request.method == "POST":
        action = request.form.get("action", "")
        national_id = request.form.get("national_id", "").strip()
        if action == "block" and national_id:
            db.execute("INSERT OR IGNORE INTO blocked_ids (national_id, reason, blocked_by, timestamp) VALUES (?, ?, ?, ?)",
                       (national_id, request.form.get("reason", ""), flask_session.get("admin_user", "admin"), datetime.now().isoformat()))
            db.commit()
            msg = "تم الحظر"
        elif action == "unblock" and national_id:
            db.execute("DELETE FROM blocked_ids WHERE national_id = ?", (national_id,))
            db.commit()
            msg = "تم إلغاء الحظر"
    blocked = db.execute("SELECT * FROM blocked_ids ORDER BY id DESC").fetchall()
    return render_template_string(ADMIN_BLOCKS_HTML, blocked=blocked, msg=msg, username=flask_session.get("admin_user", "admin"))


ADMIN_BLOCKS_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>إدارة الحظر</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Cairo',sans-serif;background:#000;padding:20px;color:#fff}
.header{background:rgba(255,255,255,0.04);backdrop-filter:blur(40px);border-radius:20px;padding:25px 30px;margin-bottom:25px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;border:1px solid rgba(255,255,255,0.06)}
.header h1{color:#fff;font-size:22px;font-weight:800}
.header a{background:rgba(255,255,255,0.1);color:#fff;padding:8px 18px;border-radius:10px;text-decoration:none;font-weight:600;font-size:13px}
.header a:hover{background:rgba(255,255,255,0.2)}
.form-card{background:rgba(255,255,255,0.04);backdrop-filter:blur(20px);border-radius:16px;padding:24px;margin-bottom:20px;border:1px solid rgba(255,255,255,0.06)}
.form-card h3{font-size:16px;font-weight:700;margin-bottom:16px}
.form-row{display:flex;gap:12px;flex-wrap:wrap;align-items:end}
.form-row input,.form-row select{padding:10px 14px;border:1px solid rgba(255,255,255,0.1);border-radius:10px;background:rgba(255,255,255,0.05);color:#fff;font-family:'Cairo',sans-serif;font-size:13px}
.form-row input:focus{outline:none;border-color:#3b82f6}
.form-row button{padding:10px 20px;border:none;border-radius:10px;font-weight:700;font-family:'Cairo',sans-serif;cursor:pointer}
.btn-block{background:#ef4444;color:#fff}
.btn-unblock{background:rgba(255,255,255,0.1);color:#fff}
.btn-unblock:hover{background:rgba(239,68,68,0.3)}
.msg{background:rgba(34,197,94,0.1);color:#4ade80;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:13px;text-align:center}
table{width:100%;border-collapse:collapse;font-size:13px}
th{padding:12px;text-align:center;font-weight:700;color:#a0aec0;border-bottom:1px solid rgba(255,255,255,0.06)}
td{padding:10px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.03);color:#fff}
table input[type="hidden"]{display:none}
</style></head>
<body>
<div class="header"><div><h1>إدارة الحظر</h1></div><div style="display:flex;gap:10px"><a href="/admin">لوحة التحكم</a><a href="/admin/logout">تسجيل خروج</a></div></div>
{% if msg %}<div class="msg">{{ msg }}</div>{% endif %}
<div class="form-card"><h3>حظر رقم هوية</h3>
<form method="post" class="form-row">
<input type="hidden" name="action" value="block">
<input type="text" name="national_id" required placeholder="رقم الهوية" maxlength="10" style="direction:ltr">
<input type="text" name="reason" placeholder="سبب الحظر (اختياري)">
<button type="submit" class="btn-block">حظر</button>
</form></div>
{% if blocked %}
<table><thead><tr><th>رقم الهوية</th><th>السبب</th><th>بواسطة</th><th>التاريخ</th><th></th></tr></thead>
<tbody>
{% for b in blocked %}
<tr>
<td dir="ltr">{{ b.national_id }}</td><td>{{ b.reason or '-' }}</td><td>{{ b.blocked_by or '-' }}</td><td style="font-size:11px;direction:ltr">{{ b.timestamp[:19] if b.timestamp else '-' }}</td>
<td><form method="post" style="display:inline"><input type="hidden" name="action" value="unblock"><input type="hidden" name="national_id" value="{{ b.national_id }}"><button type="submit" class="btn-unblock">إلغاء الحظر</button></form></td>
</tr>
{% endfor %}
</tbody></table>
{% else %}
<div style="text-align:center;padding:40px;color:#6b7280">لا توجد أرقام محظورة</div>
{% endif %}
</body></html>"""


# ===== API ENDPOINTS =====
@app.route("/api/active-connections")
@login_required
def api_active_connections():
    db = get_db()
    cutoff = (datetime.now().timestamp() - 300)  # last 5 minutes
    cutoff_str = datetime.fromtimestamp(cutoff).isoformat()
    rows = db.execute("""
        SELECT ip, device, browser, os, page, timestamp
        FROM visits WHERE timestamp >= ? ORDER BY id DESC
    """, (cutoff_str,)).fetchall()
    total_online = len(rows)
    unique_ips = len(set(r["ip"] for r in rows))
    return {
        "online": total_online,
        "unique_ips": unique_ips,
        "visitors": [dict(r) for r in rows[:50]]
    }

@app.route("/api/visitors")
@login_required
def api_visitors():
    db = get_db()
    total_visits = db.execute("SELECT COUNT(*) as c FROM visits").fetchone()["c"]
    unique_visitors = db.execute("SELECT COUNT(DISTINCT ip) as c FROM visits").fetchone()["c"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_visits = db.execute("SELECT COUNT(*) as c FROM visits WHERE timestamp LIKE ?", (f"{today}%",)).fetchone()["c"]
    return {
        "total_visits": total_visits,
        "unique_visitors": unique_visitors,
        "today_visits": today_visits
    }


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("=" * 50)
    print("الموقع يعمل على: http://localhost:8000")
    print("لوحة التحكم:     http://localhost:8000/admin/login")
    print("اسم المستخدم: admin")
    print("كلمة المرور:  admin123")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8000, debug=True)
