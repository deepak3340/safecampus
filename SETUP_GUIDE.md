# SafeGuard AI — Claude Bilingual Chatbot Setup Guide

## 🆕 Naya Feature: Hindi + English AI Chatbot

Ab SafeGuard ka chatbot **Claude AI** se powered hai jo:
- 🇮🇳 **Hindi** mein baat kar sakta hai (Devanagari script)
- 🇬🇧 **English** mein baat kar sakta hai
- Language **automatic detect** karta hai
- Earthquake, Fire, Flood, Cyclone, First Aid sab samajhta hai

---

## ⚡ Quick Setup (3 Steps)

### Step 1: Anthropic API Key Lo (FREE)
1. Jaao: https://console.anthropic.com
2. Sign up karo (free account)
3. "API Keys" section mein jaao
4. "Create Key" click karo
5. Key copy karo (looks like: `sk-ant-api03-xxxxx...`)

### Step 2: Key Set Karo

**Windows (run.bat edit karo):**
```
run.bat ko Notepad mein kholo
is line ko dhundo:
  set ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
apni key se replace karo:
  set ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx
```

**Linux/Mac (terminal mein):**
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx
python app.py
```

### Step 3: Server Chalao
```
run.bat double-click karo
Ya: python app.py
```

---

## 🧪 Test Karo

Chatbot mein ye poochhen:

| Hindi | English |
|-------|---------|
| भूकंप आने पर क्या करें? | What to do during earthquake? |
| आग लगने पर क्या करना चाहिए? | Fire safety tips |
| CPR kaise karte hain? | How to perform CPR? |
| इमरजेंसी किट में क्या रखें? | Emergency kit checklist |
| NDMA helpline number kya hai? | NDMA contact numbers |

---

## ❓ Agar API Key Nahi Hai?

Koi baat nahi! **Offline fallback mode** automatically kaam karta hai.
Is mode mein:
- Basic disaster safety answers milenge
- Hindi + English dono mein basic responses honge
- Sari core features kaam karengi

API key add karne se responses **behtar aur smarter** ho jaate hain.

---

## 🚀 Login Credentials (Demo)

| Role | Username | Password |
|------|----------|----------|
| Admin | admin | admin123 |
| Student | priya | pass123 |
| Student | arjun | pass123 |

---

## 📞 India Emergency Numbers
- National Emergency: **112**
- NDMA: **1078**
- Fire: **101**
- Ambulance: **108**
- Police: **100**
