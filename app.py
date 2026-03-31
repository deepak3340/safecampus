import sqlite3, hashlib, os, re, json, random
import urllib.request
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, jsonify,
                   session, redirect, url_for, g)

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()
DB = os.path.join(os.path.dirname(__file__), "safecampus.db")

#Database helpers

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def mutate(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

# Schema & seed

def init_db():
    db = sqlite3.connect(DB)
    db.executescript("""
    PRAGMA journal_mode=WAL;

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student',
        institution TEXT DEFAULT 'Demo Institution',
        region TEXT DEFAULT 'madhya_pradesh',
        points INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS badges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        badge_name TEXT NOT NULL,
        badge_icon TEXT DEFAULT '🏅',
        earned_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS drill_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        drill_type TEXT NOT NULL,
        time_taken INTEGER NOT NULL,
        points_earned INTEGER NOT NULL,
        rating TEXT NOT NULL,
        completed_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        topic TEXT NOT NULL,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        points_earned INTEGER NOT NULL,
        completed_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS module_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        module_id INTEGER NOT NULL,
        completed INTEGER DEFAULT 0,
        completed_at TEXT,
        UNIQUE(user_id, module_id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sos_broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        drill_type TEXT,
        sent_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(admin_id) REFERENCES users(id)
    );
    """)
    db.commit()

    # Seed demo users
    users = [
        ("admin",    hash_pw("admin123"),  "Dr. A. Sharma",   "admin",   "Delhi Public School", "delhi"),
        ("priya",    hash_pw("pass123"),   "Priya Singh",     "student", "Delhi Public School", "madhya_pradesh"),
        ("arjun",    hash_pw("pass123"),   "Arjun Mehta",     "student", "Delhi Public School", "gujarat"),
        ("sneha",    hash_pw("pass123"),   "Sneha Patel",     "student", "Delhi Public School", "kerala"),
        ("ravi",     hash_pw("pass123"),   "Ravi Kumar",      "student", "Delhi Public School", "odisha"),
    ]
    for u in users:
        try:
            db.execute("INSERT INTO users (username,password,name,role,institution,region) VALUES (?,?,?,?,?,?)", u)
        except: pass

    # Seed points & badges for demo students
    demo = [("priya",340,4), ("arjun",210,3), ("sneha",480,5), ("ravi",420,5)]
    for uname, pts, lvl in demo:
        db.execute("UPDATE users SET points=?,level=? WHERE username=?", (pts, lvl, uname))

    badge_data = [
        ("priya",  "First Responder",   "🥇"),
        ("priya",  "Quiz Master",       "🧠"),
        ("arjun",  "Fire Drill Pro",    "🔥"),
        ("sneha",  "Earthquake Expert", "🌍"),
        ("sneha",  "First Responder",   "🥇"),
        ("sneha",  "Top Scorer",        "🏆"),
        ("ravi",   "Flood Guardian",    "🌊"),
        ("ravi",   "First Responder",   "🥇"),
    ]
    for uname, bname, bicon in badge_data:
        row = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if row:
            try:
                db.execute("INSERT INTO badges (user_id,badge_name,badge_icon) VALUES (?,?,?)",
                           (row[0], bname, bicon))
            except: pass

    # Seed some drill history
    drill_history = [
        ("priya",  "earthquake", 28, 90, "Excellent"),
        ("priya",  "fire",       35, 80, "Good"),
        ("arjun",  "fire",       22, 95, "Excellent"),
        ("sneha",  "earthquake", 19, 100,"Excellent"),
        ("sneha",  "flood",      31, 85, "Good"),
        ("ravi",   "flood",      26, 92, "Excellent"),
    ]
    for uname, dtype, tt, pe, rat in drill_history:
        row = db.execute("SELECT id FROM users WHERE username=?", (uname,)).fetchone()
        if row:
            db.execute("INSERT INTO drill_attempts (user_id,drill_type,time_taken,points_earned,rating) VALUES (?,?,?,?,?)",
                       (row[0], dtype, tt, pe, rat))

    db.commit()
    db.close()

# ─── Auth helpers 
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "admin":
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def current_user():
    if "user_id" not in session:
        return None
    return query("SELECT * FROM users WHERE id=?", (session["user_id"],), one=True)

def add_points(user_id, pts):
    user = query("SELECT points FROM users WHERE id=?", (user_id,), one=True)
    if user:
        new_pts = user["points"] + pts
        new_level = min(10, 1 + new_pts // 100)
        mutate("UPDATE users SET points=?, level=? WHERE id=?", (new_pts, new_level, user_id))

def award_badge(user_id, name, icon="🏅"):
    existing = query("SELECT id FROM badges WHERE user_id=? AND badge_name=?", (user_id, name), one=True)
    if not existing:
        mutate("INSERT INTO badges (user_id,badge_name,badge_icon) VALUES (?,?,?)", (user_id, name, icon))
        return True
    return False

# ─── AI Disaster Advisor (Claude AI — bilingual Hindi + English) ─────────────

# Fallback knowledge base (used if API unavailable)
KNOWLEDGE_BASE = {
    "earthquake": {
        "keywords": ["earthquake","quake","tremor","seismic","magnitude","richter","fault","aftershock","bhukamp"],
        "before": "Before an earthquake: (1) Secure heavy furniture to walls. (2) Know your building's evacuation routes. (3) Prepare a 72-hour emergency kit: water, food, first aid, torch, radio. (4) Identify safe spots in each room — under sturdy tables, against interior walls. (5) Practice Drop-Cover-Hold-On with your family.",
        "during": "During an earthquake: DROP to hands and knees immediately. Take COVER under a sturdy desk or against an interior wall, protecting your head and neck. HOLD ON until shaking stops. Stay away from windows, exterior walls, and heavy objects. If outside, move away from buildings, trees, and power lines. Do NOT run outside during shaking.",
        "after":  "After an earthquake: Check yourself for injuries before helping others. Expect aftershocks. Check for gas leaks — if you smell gas, open windows and leave immediately. Do NOT use elevators. Take photos of damage for insurance. Listen to official broadcasts. Do not re-enter damaged buildings.",
        "kit":    "Earthquake emergency kit: 3L water per person per day (72 hrs), non-perishable food, first aid kit, torch + extra batteries, battery-powered radio, whistle to signal for help, dust mask, plastic sheeting and duct tape, moist towelettes, wrench to shut off gas, manual can opener, local maps, medications, copies of important documents.",
        "india":  "In India, earthquake-prone zones: Zone V (highest risk) includes NE India, J&K, Himachal, Uttarakhand, parts of Gujarat and Bihar. Zone IV includes Delhi, J&K, Himachal foothills, Sikkim, UP hills, Bihar plains, West Bengal. NDMA helpline: 1078. Follow BIS IS 1893 building codes."
    },
    "flood": {
        "keywords": ["flood","flooding","flash flood","inundation","waterlogging","baarish","barsat","high water","river overflow","dam break","tsunami"],
        "before": "Before a flood: (1) Know your flood risk zone — check with local municipality. (2) Waterproof important documents and valuables in plastic bags. (3) Move electrical appliances to higher ground. (4) Know your evacuation route to higher ground. (5) Keep emergency contact numbers saved offline. (6) Fill bathtubs with clean water.",
        "during": "During a flood: Move immediately to higher floors. Do NOT walk through moving water — just 15 cm can knock you off your feet. Switch off electricity at the main breaker. Do NOT drive through flooded roads. If your car is submerged, open the window before the door to escape. Signal for help from upper floors. Do NOT attempt to swim in flood water.",
        "after":  "After a flood: Do not return home until authorities declare it safe. Avoid floodwater — it may be contaminated with sewage or chemicals. Document all damage. Boil all drinking water. Watch for mold growth in your home. Discard food that came in contact with floodwater. Get vaccinated — floods increase leptospirosis and hepatitis A risk.",
        "india":  "India flood hotspots: Assam (Brahmaputra), Bihar (Kosi, Gandak, Bagmati), UP (Ganga, Yamuna), Kerala (2018 mega-floods), Odisha (Mahanadi), West Bengal (Hooghly). India's flood forecasting is done by Central Water Commission (CWC): 1800-180-1717. NDRF flood rescue: 011-24363260."
    },
    "fire": {
        "keywords": ["fire","flame","smoke","blaze","burn","arson","wildfire","forest fire","kitchen fire","electrical fire","aag","firefighter"],
        "before": "Before a fire emergency: (1) Install smoke detectors on every floor — test monthly. (2) Know two exits from every room. (3) Keep fire extinguishers in kitchen and lab areas. (4) Never overload electrical sockets. (5) Practice RACE: Rescue, Alarm, Contain, Extinguish. (6) Identify your building's fire assembly point.",
        "during": "During a fire: Activate the nearest fire alarm. Call 101. Use RACE: Rescue anyone in immediate danger, Alarm others, Contain by closing doors, Extinguish only if fire is small and you have a clear exit. Feel doors with the back of your hand — if hot, do NOT open. Crawl low under smoke (clean air is near the floor). Close doors behind you to slow fire spread.",
        "after":  "After a fire: Do not re-enter the building until fire department declares it safe. Seek medical attention even for minor smoke inhalation. Document losses for insurance. Contact your institution's administration. Get emotional support — fire trauma is real. Check with fire marshal before restoring electricity or gas.",
        "extinguisher": "How to use a fire extinguisher — PASS technique: PULL the pin (breaks tamper seal). AIM the nozzle at the BASE of the fire, not the flames. SQUEEZE the handle slowly and evenly. SWEEP side to side at the base of the fire until it is out. Types: CO2 (electrical fires), Dry chemical ABC (most fires), Water mist (Class A). Never use water on electrical or oil fires.",
        "india":  "India fire emergency: Call 101 (Fire) or 112 (National Emergency). Major fire-prone locations: slums, factories, electrical substations, hospitals, schools with thatched roofs. India's National Building Code mandates fire safety systems for all buildings above 15m. NDRF also responds to major fire incidents."
    },
    "cyclone": {
        "keywords": ["cyclone","hurricane","typhoon","storm","tufan","wind","gale","depression","tropical storm","landfall"],
        "before": "Before a cyclone: (1) Listen to IMD (India Meteorological Department) warnings — cyclone watch = 48 hrs, cyclone warning = 24 hrs. (2) Board up windows and reinforce doors. (3) Move to a pucca (concrete) building. (4) Charge all devices and keep battery banks ready. (5) Trim trees near your home. (6) Keep emergency kit ready. (7) Know your nearest cyclone shelter.",
        "during": "During a cyclone: Stay indoors away from windows and glass. If your building is unsafe, evacuate before the storm arrives. Do NOT go outside when the 'eye' passes — the calm is temporary, the second wall of the storm is coming. Do NOT take shelter under trees or near power lines. Shut all doors, windows, and ventilators.",
        "after":  "After a cyclone: Check for injured people. Avoid floodwater, downed power lines, and damaged buildings. Do not use tap water until authorities confirm it is safe. Beware of snakes and insects displaced by flooding. Report structural damage to authorities. Do not light open fires until gas lines are checked.",
        "india":  "India cyclone-prone states: Odisha (most frequent), Andhra Pradesh, Tamil Nadu, West Bengal, Gujarat, Maharashtra. IMD issues cyclone alerts at cyclone.imd.gov.in. NDRF stations positioned at Bhubaneswar, Vijayawada, Chennai during cyclone season (April-June, October-December). Toll-free: 1078."
    },
    "firstaid": {
        "keywords": ["first aid","cpr","bleeding","fracture","burn","choking","shock","unconscious","medical","injury","wound","prathamik upchar"],
        "cpr":      "CPR steps: (1) Check scene is safe. (2) Check responsiveness — tap shoulders, shout. (3) Call 108 (ambulance). (4) 30 chest compressions — place heel of hand on centre of chest, push hard and fast (5 cm depth, 100-120/min). (5) 2 rescue breaths — tilt head back, lift chin, pinch nose, breathe for 1 second watching chest rise. (6) Repeat 30:2 cycle until help arrives or person recovers. For hands-only CPR: skip rescue breaths, do continuous compressions.",
        "bleeding": "Controlling severe bleeding: (1) Call 108 immediately. (2) Apply firm direct pressure with a clean cloth — do NOT remove the cloth even if it soaks through (add more on top). (3) If limb, elevate above heart level. (4) If bleeding doesn't stop in 10 minutes, apply a tourniquet 5 cm above the wound. (5) Keep person warm to prevent shock.",
        "burns":    "Burn first aid: (1) Remove from heat source. (2) Cool under running water for 20 minutes — do NOT use ice, butter, or toothpaste. (3) Cover loosely with clean cling film or non-fluffy material. (4) Do NOT burst blisters. (5) For chemical burns, flush with large amounts of water for 30+ minutes. (6) For electrical burns — do NOT touch person until power is off. Seek hospital for all burns larger than a 50-paise coin.",
        "choking":  "Choking response: (1) Ask 'Are you choking?' — if they can cough, encourage coughing. (2) If they cannot cough/speak: Give 5 firm back blows between shoulder blades with heel of hand. (3) If ineffective: Give 5 abdominal thrusts (Heimlich maneuver) — stand behind, fist just above navel, sharp inward-upward thrusts. (4) Alternate 5 back blows and 5 abdominal thrusts. (5) If unconscious: start CPR and call 108.",
        "fracture": "Suspected fracture: (1) Do NOT try to realign the bone. (2) Immobilize the injured area using splints (straight sticks, boards) padded with cloth. (3) Apply ice wrapped in cloth to reduce swelling (not direct ice). (4) Elevate if possible. (5) For open fractures (bone visible): cover with clean bandage, do NOT push bone back. (6) Call 108 for spine, pelvis, or femur fractures — do NOT move the person."
    },
    "emergency_kit": {
        "keywords": ["kit","emergency bag","go bag","survival kit","prepare","preparation","what to keep","essential","72 hour"],
        "contents": "72-hour disaster emergency kit checklist: WATER: 3 litres per person per day. FOOD: Non-perishable items (dry fruits, biscuits, energy bars, canned goods). FIRST AID: Bandages, antiseptic, pain killers, personal medications, thermometer. LIGHT: Torch with extra batteries, candles, matchbox. COMMUNICATION: Battery-powered or hand-crank radio, whistle. DOCUMENTS: Aadhaar, PAN, insurance papers in waterproof pouch. TOOLS: Knife, rope, dust mask, gloves, raincoat. MONEY: Cash in small denominations. PHONE: Portable charger, emergency contacts written on paper (phone may die)."
    },
    "ndma": {
        "keywords": ["ndma","ndrf","government","helpline","contact","number","call","authority","disaster management","ministry"],
        "info": "Key India disaster management contacts: National Emergency: 112 | NDMA: 1078 | Fire: 101 | Ambulance: 108 | Police: 100 | NDRF: 011-24363260 | CWC Flood: 1800-180-1717 | IMD Weather: 1800-180-1717 | Women Helpline: 1091 | Child Helpline: 1098. NDMA (National Disaster Management Authority) is India's apex body for disaster preparedness under the PM's chairmanship. NDRF (National Disaster Response Force) has 16 battalions stationed across India."
    }
}

GREETINGS = ["hello","hi","hey","namaste","namaskar","helo","hii"]
THANKS = ["thank","thanks","thankyou","dhanyawad","shukriya"]
HELP_WORDS = ["help","what can you do","capabilities","features"]

SYSTEM_PROMPT = """You are SafeGuard AI — a bilingual disaster safety advisor for students and teachers in India.

LANGUAGE RULE (VERY IMPORTANT):
- Detect the language of the user's message automatically.
- If user writes in Hindi (or Hinglish), respond FULLY in Hindi (Devanagari script).
- If user writes in English, respond FULLY in English.
- Never mix languages in a single response.

YOUR EXPERTISE:
- 🌍 Earthquake (Bhukamp) safety — before, during, after; Drop-Cover-Hold-On
- 🔥 Fire (Aag) emergencies — RACE protocol, PASS extinguisher technique, evacuation
- 🌊 Flood (Baadhh) preparedness — India flood zones, CWC helpline
- 🌀 Cyclone (Toofan) safety — IMD warnings, evacuation
- 🏥 First Aid — CPR, bleeding control, burns, fractures, choking
- 🎒 Emergency Kit — 72-hour kit checklist
- 📞 India helplines — NDMA 1078, Fire 101, Ambulance 108, Police 100, National Emergency 112

RESPONSE STYLE:
- Be warm, friendly, and encouraging
- Use bullet points and emojis to make responses clear
- Keep responses concise but complete (max 200 words)
- Always include the relevant India helpline at the end when discussing emergencies
- For greetings, introduce yourself briefly in the same language

IMPORTANT: Only answer questions related to disaster safety, emergency preparedness, first aid, and general safety topics. For completely unrelated questions, politely redirect to your expertise area."""

def ai_advisor(message, user_name="there"):
    """Call Claude API for bilingual disaster safety responses. Falls back to offline KB if API unavailable."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")
        if api_key:
            payload = json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 500,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": f"[User name: {user_name}]\n{message}"}
                ]
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                result = json.loads(res.read().decode("utf-8"))
                return result["content"][0]["text"]
    except Exception as e:
        app.logger.warning(f"Claude API error, falling back to offline KB: {e}")

    # ── Offline fallback ──────────────────────────────────────────────────────
    msg = message.lower().strip()

    if any(g in msg for g in GREETINGS):
        return f"Namaste {user_name}! 🙏 Main SafeGuard hoon — aapka AI disaster safety advisor. Earthquake, flood, fire, cyclone, first aid ya emergency kit ke baare mein kuch bhi poochh sakte hain!\n\nHello {user_name}! I'm SafeGuard, your AI disaster safety advisor. Ask me anything about earthquake, flood, fire, cyclone safety, first aid, or emergency preparedness!"

    if any(t in msg for t in THANKS):
        return "Aapka swagat hai! Surakshit rahein. 🛡️\nYou're welcome! Stay safe and prepared. Feel free to ask anything else!"

    if any(h in msg for h in HELP_WORDS):
        return "Main in topics mein help kar sakta hoon:\n🌍 Earthquake • 🌊 Flood • 🔥 Fire • 🌀 Cyclone • 🏥 First Aid • 🎒 Emergency Kit • 📞 NDMA Helplines\n\nI can help with: 🌍 Earthquake • 🌊 Flood • 🔥 Fire • 🌀 Cyclone • 🏥 First Aid • 🎒 Emergency Kit • 📞 NDMA helplines"

    # ── Offline KB matching (fallback when API unavailable) ───────────────────
    best_match = None
    best_score = 0
    for category, data in KNOWLEDGE_BASE.items():
        score = sum(1 for kw in data.get("keywords", []) if kw in msg)
        if score > best_score:
            best_score = score
            best_match = (category, data)

    if best_match and best_score > 0:
        category, data = best_match
        if "before" in msg or "prepare" in msg:       preferred = "before"
        elif "during" in msg or "right now" in msg:   preferred = "during"
        elif "after" in msg or "recover" in msg:      preferred = "after"
        elif "cpr" in msg or "cardiac" in msg:        preferred = "cpr"
        elif "bleed" in msg or "wound" in msg:        preferred = "bleeding"
        elif "burn" in msg:                           preferred = "burns"
        elif "chok" in msg:                           preferred = "choking"
        elif "fractur" in msg or "bone" in msg:       preferred = "fracture"
        elif "extinguish" in msg:                     preferred = "extinguisher"
        elif "india" in msg or "helpline" in msg:     preferred = "india" if "india" in data else "info"
        elif "kit" in msg or "bag" in msg:            preferred = "kit" if "kit" in data else "before"
        else:                                         preferred = list(data.keys())[1] if len(data) > 1 else None

        content_key = preferred if preferred and preferred in data else (list(data.keys())[1] if len(data) > 1 else None)
        if content_key and content_key in data:
            icons = {"earthquake":"🌍","flood":"🌊","fire":"🔥","cyclone":"🌀","firstaid":"🏥","emergency_kit":"🎒","ndma":"📞"}
            icon = icons.get(category, "🛡️")
            return f"{icon} **{category.replace('_',' ').title()} — {content_key.title()}**\n\n{data[content_key]}\n\n💡 *Aur poochhen: 'before/during/after {category}?' | Ask more: 'What to do before/during/after {category}?'*"

    if re.search(r'(number|call|helpline|phone|nambar)', msg):
        return KNOWLEDGE_BASE["ndma"]["info"]

    return ("Mujhe samajh nahi aaya — poochhen jaise: 'Bhukamp mein kya karein?' ya 'CPR kaise karein?'\n\n"
            "I didn't catch that — try: 'What to do during earthquake?' or 'How to do CPR?' or 'Emergency kit checklist?'")

# ─── Static data ──────────────────────────────────────────────────────────────

REGIONS = {
    "madhya_pradesh": {"name":"Madhya Pradesh","risks":["Flood","Drought","Heat Wave"],"level":"moderate"},
    "gujarat":        {"name":"Gujarat",        "risks":["Earthquake","Cyclone","Flood"],"level":"high"},
    "kerala":         {"name":"Kerala",         "risks":["Flood","Landslide","Cyclone"], "level":"high"},
    "himachal":       {"name":"Himachal Pradesh","risks":["Landslide","Earthquake","Snow Storm"],"level":"low"},
    "odisha":         {"name":"Odisha",          "risks":["Cyclone","Flood","Drought"],   "level":"critical"},
    "delhi":          {"name":"Delhi NCR",       "risks":["Earthquake","Heat Wave","Flood"],"level":"moderate"},
}

MODULES = [
    {"id":1,"title":"Earthquake Safety","icon":"🌍","desc":"Drop-Cover-Hold-On techniques and post-quake survival protocols.","pts":50,"duration":"15 min","difficulty":"Beginner","lessons":5},
    {"id":2,"title":"Flood Preparedness","icon":"🌊","desc":"Flood zones, vertical evacuation routes, and waterproofing essentials.","pts":60,"duration":"20 min","difficulty":"Intermediate","lessons":6},
    {"id":3,"title":"Fire Evacuation","icon":"🔥","desc":"RACE protocol, fire extinguisher use, and building evacuation drills.","pts":45,"duration":"12 min","difficulty":"Beginner","lessons":4},
    {"id":4,"title":"Cyclone & Storm","icon":"🌀","desc":"Pre-cyclone preparations, shelter protocols, and IMD alert systems.","pts":70,"duration":"25 min","difficulty":"Advanced","lessons":7},
    {"id":5,"title":"First Aid Basics","icon":"🏥","desc":"CPR, bleeding control, fracture management in disaster scenarios.","pts":80,"duration":"30 min","difficulty":"Intermediate","lessons":8},
    {"id":6,"title":"Mental Health in Crisis","icon":"🧠","desc":"Trauma management and psychological first aid for survivors.","pts":55,"duration":"18 min","difficulty":"Intermediate","lessons":5},
]

QUIZ_DB = {
    "earthquake":[
        {"q":"What is the correct action during an earthquake?","opts":["Run outside","Drop, Cover, Hold On","Call for help immediately","Open all windows"],"ans":1,"exp":"Drop-Cover-Hold On is the scientifically proven technique that reduces injury from falling debris."},
        {"q":"Where is the SAFEST spot during an indoor earthquake?","opts":["Doorframe","Under a sturdy table","Near exterior walls","In an elevator"],"ans":1,"exp":"Under a sturdy table protects you from falling objects — the doorframe myth is outdated."},
        {"q":"After shaking stops, what is the FIRST thing to check?","opts":["Your phone","Gas leaks and structural damage","Weather updates","Social media"],"ans":1,"exp":"Gas leaks can cause fires or explosions — always check first before anything else."},
        {"q":"India's highest earthquake risk zone is Zone:","opts":["Zone I","Zone III","Zone V","Zone II"],"ans":2,"exp":"Zone V (highest risk) covers NE India, J&K, Himachal Pradesh, Uttarakhand and parts of Gujarat."},
        {"q":"Earthquake magnitude is measured on the:","opts":["Beaufort Scale","Richter / Moment Magnitude Scale","Decibel Scale","Kelvin Scale"],"ans":1,"exp":"The Richter Scale (now Moment Magnitude Scale) measures earthquake energy released at the source."},
    ],
    "flood":[
        {"q":"How much moving water can knock an adult off their feet?","opts":["60 cm","30 cm","15 cm","90 cm"],"ans":2,"exp":"Just 15 cm (6 inches) of fast-moving water has enough force to knock over an adult."},
        {"q":"What should you do FIRST when a flood warning is issued?","opts":["Watch the news","Move valuables to higher ground","Go to the roof","Call relatives"],"ans":1,"exp":"Moving valuables prevents loss and preparing for evacuation is the immediate priority."},
        {"q":"After a flood, tap water should be:","opts":["Drunk normally","Avoided entirely for 48 hours","Boiled before drinking","Mixed with purification tablets only"],"ans":2,"exp":"Flood water can contaminate supply pipes with sewage and pathogens — always boil first."},
        {"q":"If your car starts filling with water, you should:","opts":["Call for help and wait","Break the window with a sharp object after pressure equalizes","Accelerate and drive out","Stay calm and do nothing"],"ans":1,"exp":"Once water pressure equalizes (car mostly full), open the window/door and swim to safety."},
        {"q":"India's flood forecasting is managed by:","opts":["NDMA only","IMD and Central Water Commission (CWC)","State Police","Indian Army"],"ans":1,"exp":"CWC monitors river levels and IMD provides meteorological warnings. Both together issue flood forecasts."},
    ],
    "fire":[
        {"q":"RACE in fire emergency stands for:","opts":["Run Away Carefully Everywhere","Rescue, Alarm, Contain, Extinguish","React, Alert, Call, Escape","Remove, Activate, Close, Evacuate"],"ans":1,"exp":"RACE is the standard hospital/building fire response protocol taught globally."},
        {"q":"Escaping a smoke-filled corridor — you should:","opts":["Stand and run fast","Crawl low where air is cleaner","Break a window first","Call the fire department before moving"],"ans":1,"exp":"Smoke rises — clean air is within 30cm of the floor. Crawling dramatically reduces smoke inhalation."},
        {"q":"The PASS fire extinguisher technique stands for:","opts":["Pull, Aim, Squeeze, Sweep","Press, Activate, Spray, Stop","Point, Arm, Shoot, Secure","Prepare, Assess, Spray, Stand"],"ans":0,"exp":"Pull the pin → Aim at the base of fire → Squeeze the handle → Sweep side to side."},
        {"q":"If your clothes catch fire, you should:","opts":["Run to water immediately","Strip them off quickly","Stop, Drop, and Roll","Fan the flames to extinguish"],"ans":2,"exp":"Running feeds oxygen to the fire. Stop, Drop, and Roll smothers the flames by cutting off air supply."},
        {"q":"You should NOT use water on which type of fire?","opts":["Paper fire","Wood fire","Electrical or oil fire","Fabric fire"],"ans":2,"exp":"Water conducts electricity (electrical fire risk) and causes oil fires to explode and spread violently."},
    ],
}

DRILLS = [
    {"id":1,"type":"earthquake","title":"Magnitude 6.2 Earthquake Drill","steps":[
        {"n":1,"icon":"⬇️","action":"DROP to hands and knees — do not stand or run"},
        {"n":2,"icon":"🛡️","action":"COVER your head and neck under a sturdy desk or table"},
        {"n":3,"icon":"✊","action":"HOLD ON tightly — do not let go until shaking fully stops"},
        {"n":4,"icon":"🔍","action":"Shaking stopped — check yourself and others for injuries"},
        {"n":5,"icon":"🚶","action":"Evacuate via stairs only — do NOT use elevators"},
        {"n":6,"icon":"📍","action":"Assemble at the designated muster point and report to warden"},
    ]},
    {"id":2,"type":"fire","title":"Building Fire Alarm Response","steps":[
        {"n":1,"icon":"🔔","action":"Activate the nearest fire alarm pull station immediately"},
        {"n":2,"icon":"📣","action":"Shout 'FIRE!' to alert others — call 101"},
        {"n":3,"icon":"🤚","action":"Feel door with BACK of hand — if hot, do NOT open it"},
        {"n":4,"icon":"🧎","action":"Crawl low under smoke towards the nearest marked exit"},
        {"n":5,"icon":"🚪","action":"Close all doors behind you to slow fire and smoke spread"},
        {"n":6,"icon":"📍","action":"Reach assembly point — account for everyone, never re-enter"},
    ]},
    {"id":3,"type":"flood","title":"Flash Flood Warning Response","steps":[
        {"n":1,"icon":"⬆️","action":"Move immediately to the highest floor available"},
        {"n":2,"icon":"⚡","action":"Switch off electricity at the main breaker panel"},
        {"n":3,"icon":"⚠️","action":"Do NOT enter floodwater — 15cm moving water can knock you down"},
        {"n":4,"icon":"📱","action":"Call 112 and family members — conserve phone battery"},
        {"n":5,"icon":"🚩","action":"Signal rescuers from upper window with bright cloth or light"},
        {"n":6,"icon":"🛶","action":"Wait for official NDRF rescue — never attempt to swim out"},
    ]},
]

EMERGENCY_CONTACTS = [
    {"name":"National Emergency","number":"112","type":"Emergency","icon":"🚨"},
    {"name":"NDMA Helpline","number":"1078","type":"Disaster","icon":"🏛️"},
    {"name":"Fire Department","number":"101","type":"Fire","icon":"🔥"},
    {"name":"Ambulance","number":"108","type":"Medical","icon":"🚑"},
    {"name":"Police","number":"100","type":"Police","icon":"👮"},
    {"name":"NDRF (National Disaster Response Force)","number":"011-24363260","type":"Disaster","icon":"🛡️"},
    {"name":"Central Water Commission (Flood)","number":"1800-180-1717","type":"Flood","icon":"🌊"},
    {"name":"India Meteorological Dept","number":"1800-180-1717","type":"Weather","icon":"🌦️"},
    {"name":"Women Helpline","number":"1091","type":"Support","icon":"👩"},
    {"name":"Child Helpline","number":"1098","type":"Support","icon":"👶"},
]

# ─── Page routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    stats = {
        "students": query("SELECT COUNT(*) as c FROM users WHERE role='student'", one=True)["c"],
        "drills":   query("SELECT COUNT(*) as c FROM drill_attempts", one=True)["c"],
        "quizzes":  query("SELECT COUNT(*) as c FROM quiz_attempts", one=True)["c"],
    }
    return render_template("index.html", stats=stats)

@app.route("/login", methods=["GET","POST"])
def login_page():
    if request.method == "POST":
        data = request.get_json()
        user = query("SELECT * FROM users WHERE username=? AND password=?",
                     (data["username"], hash_pw(data["password"])), one=True)
        if user:
            session["user_id"] = user["id"]
            session["role"]    = user["role"]
            session["name"]    = user["name"]
            return jsonify({"ok":True,"role":user["role"]})
        return jsonify({"ok":False,"msg":"Invalid credentials — check username and password."})
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/dashboard")
@login_required
def dashboard():
    u = current_user()
    if u["role"] == "admin":
        return redirect("/admin")
    badges  = query("SELECT * FROM badges WHERE user_id=? ORDER BY earned_at DESC", (u["id"],))
    drills  = query("SELECT * FROM drill_attempts WHERE user_id=? ORDER BY completed_at DESC LIMIT 5", (u["id"],))
    mods    = query("SELECT module_id FROM module_progress WHERE user_id=? AND completed=1", (u["id"],))
    done_ids = {r["module_id"] for r in mods}
    lboard  = query("""SELECT u.name, u.points, u.level,
                        (SELECT COUNT(*) FROM badges b WHERE b.user_id=u.id) badges,
                        (SELECT COUNT(*) FROM drill_attempts d WHERE d.user_id=u.id) drills
                       FROM users u WHERE u.role='student'
                       ORDER BY u.points DESC LIMIT 8""")
    return render_template("dashboard.html", user=u, badges=badges,
                           recent_drills=drills, modules=MODULES,
                           done_ids=done_ids, leaderboard=lboard,
                           now_hour=datetime.now().hour)

@app.route("/admin")
@login_required
@admin_required
def admin():
    u = current_user()
    total_s   = query("SELECT COUNT(*) c FROM users WHERE role='student'", one=True)["c"]
    total_d   = query("SELECT COUNT(*) c FROM drill_attempts", one=True)["c"]
    total_q   = query("SELECT COUNT(*) c FROM quiz_attempts", one=True)["c"]
    avg_pts   = query("SELECT AVG(points) c FROM users WHERE role='student'", one=True)["c"] or 0
    top_s     = query("""SELECT u.name, u.points, u.level,
                          (SELECT COUNT(*) FROM badges b WHERE b.user_id=u.id) badges,
                          (SELECT COUNT(*) FROM drill_attempts d WHERE d.user_id=u.id) drills
                         FROM users u WHERE u.role='student' ORDER BY u.points DESC LIMIT 5""")
    recent_d  = query("""SELECT u.name, da.drill_type, da.rating, da.time_taken, da.completed_at
                          FROM drill_attempts da JOIN users u ON u.id=da.user_id
                          ORDER BY da.completed_at DESC LIMIT 8""")
    dept_data = [
        {"dept":"Science",     "score":82,"students":210},
        {"dept":"Commerce",    "score":74,"students":185},
        {"dept":"Arts",        "score":68,"students":175},
        {"dept":"Engineering", "score":88,"students":277},
    ]
    broadcasts = query("SELECT sb.*, u.name FROM sos_broadcasts sb JOIN users u ON u.id=sb.admin_id ORDER BY sb.sent_at DESC LIMIT 5")
    return render_template("admin.html", user=u,
                           total_students=total_s, total_drills=total_d,
                           total_quizzes=total_q, avg_pts=round(avg_pts),
                           top_students=top_s, recent_drills=recent_d,
                           dept_data=dept_data, broadcasts=broadcasts)

@app.route("/modules")
@login_required
def modules():
    u = current_user()
    mods = query("SELECT module_id FROM module_progress WHERE user_id=? AND completed=1", (u["id"],))
    done = {r["module_id"] for r in mods}
    return render_template("modules.html", user=u, modules=MODULES, done=done)

@app.route("/drill")
@login_required
def drill():
    u = current_user()
    history = query("SELECT * FROM drill_attempts WHERE user_id=? ORDER BY completed_at DESC LIMIT 6", (u["id"],))
    return render_template("drill.html", user=u, drills=DRILLS, history=history)

@app.route("/quiz")
@login_required
def quiz():
    u = current_user()
    history = query("SELECT * FROM quiz_attempts WHERE user_id=? ORDER BY completed_at DESC LIMIT 6", (u["id"],))
    return render_template("quiz.html", user=u, history=history)

@app.route("/alerts")
def alerts():
    u = current_user()
    return render_template("alerts.html", user=u, regions=REGIONS)

@app.route("/emergency")
def emergency():
    u = current_user()
    return render_template("emergency.html", user=u, contacts=EMERGENCY_CONTACTS)

@app.route("/advisor")
@login_required
def advisor():
    u = current_user()
    history = query("SELECT * FROM chat_history WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (u["id"],))
    return render_template("advisor.html", user=u, history=list(reversed(history)))

# ─── API routes ───────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json()
    msg  = data.get("message","").strip()
    if not msg:
        return jsonify({"ok":False})
    u    = current_user()
    resp = ai_advisor(msg, u["name"].split()[0])
    mutate("INSERT INTO chat_history (user_id,message,response) VALUES (?,?,?)",
           (u["id"], msg, resp))
    return jsonify({"ok":True,"response":resp})

@app.route("/api/quiz/<topic>")
def api_quiz(topic):
    return jsonify(QUIZ_DB.get(topic, []))

@app.route("/api/submit_quiz", methods=["POST"])
@login_required
def api_submit_quiz():
    data    = request.get_json()
    score   = data.get("score",0)
    total   = data.get("total",5)
    topic   = data.get("topic","general")
    u       = current_user()
    pts     = score * 20
    mutate("INSERT INTO quiz_attempts (user_id,topic,score,total,points_earned) VALUES (?,?,?,?,?)",
           (u["id"], topic, score, total, pts))
    add_points(u["id"], pts)
    badge = None
    if score == total:
        bname = f"{topic.capitalize()} Expert"
        if award_badge(u["id"], bname, "🧠"):
            badge = bname
    return jsonify({"ok":True,"points":pts,"badge":badge,
                    "total_points": query("SELECT points FROM users WHERE id=?", (u["id"],), one=True)["points"]})

@app.route("/api/complete_drill", methods=["POST"])
@login_required
def api_complete_drill():
    data  = request.get_json()
    dtype = data.get("type","unknown")
    tt    = data.get("time_taken",60)
    u     = current_user()
    if tt < 25:   rating, pts = "Excellent", 100
    elif tt < 40: rating, pts = "Good",       75
    else:          rating, pts = "Needs Practice", 50
    mutate("INSERT INTO drill_attempts (user_id,drill_type,time_taken,points_earned,rating) VALUES (?,?,?,?,?)",
           (u["id"], dtype, tt, pts, rating))
    add_points(u["id"], pts)
    badge = None
    if rating == "Excellent":
        bname = f"{dtype.capitalize()} Drill Pro"
        if award_badge(u["id"], bname, "⏱️"):
            badge = bname
    return jsonify({"ok":True,"rating":rating,"points":pts,"badge":badge,
                    "total_points": query("SELECT points FROM users WHERE id=?", (u["id"],), one=True)["points"]})

@app.route("/api/complete_module", methods=["POST"])
@login_required
def api_complete_module():
    data = request.get_json()
    mid  = data.get("module_id")
    u    = current_user()
    mod  = next((m for m in MODULES if m["id"]==mid), None)
    if not mod: return jsonify({"ok":False})
    mutate("INSERT OR REPLACE INTO module_progress (user_id,module_id,completed,completed_at) VALUES (?,?,1,datetime('now'))",
           (u["id"], mid))
    add_points(u["id"], mod["pts"])
    return jsonify({"ok":True,"points":mod["pts"]})

@app.route("/api/broadcast", methods=["POST"])
@login_required
@admin_required
def api_broadcast():
    data  = request.get_json()
    msg   = data.get("message","Emergency drill in progress. Please follow evacuation protocol.")
    dtype = data.get("drill_type","general")
    u     = current_user()
    mutate("INSERT INTO sos_broadcasts (admin_id,message,drill_type) VALUES (?,?,?)",
           (u["id"], msg, dtype))
    return jsonify({"ok":True,"message":msg,"sent_at":datetime.now().strftime("%H:%M, %d %b")})

@app.route("/api/alerts")
def api_alerts():
    alerts = []
    level_order = {"critical":0,"high":1,"moderate":2,"low":3}
    for rid, r in REGIONS.items():
        for risk in r["risks"]:
            if random.random() > 0.45:
                alerts.append({"region":r["name"],"risk":risk,"level":r["level"],
                                "time":f"{random.randint(1,8)}h ago",
                                "message":f"{risk} advisory active for {r['name']}. Follow NDMA guidelines and stay prepared."})
    alerts.sort(key=lambda x: level_order.get(x["level"],9))
    return jsonify(alerts[:9])

@app.route("/api/stats")
def api_stats():
    return jsonify({
        "students": query("SELECT COUNT(*) c FROM users WHERE role='student'", one=True)["c"],
        "drills":   query("SELECT COUNT(*) c FROM drill_attempts", one=True)["c"],
        "quizzes":  query("SELECT COUNT(*) c FROM quiz_attempts", one=True)["c"],
    })

# ─── Init & run ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not os.path.exists(DB):
        print("🗄️  Initialising database...")
        init_db()
        print("✅ Database ready.")
    app.run(debug=True, host="0.0.0.0", port=5000)
