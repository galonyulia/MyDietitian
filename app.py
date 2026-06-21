import os
import json
import base64
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq
from tavily import TavilyClient
from supabase import create_client

app = Flask(__name__)

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
tavily      = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
supabase    = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

IL_TZ = ZoneInfo("Asia/Jerusalem")

def load_file(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return ""

profile = load_file("yulia_profile.txt")

# ── Calorie target (calculated once, based on real formulas + her stats) ───────
WEIGHT_KG     = 52.2
HEIGHT_CM     = 157
AGE           = 38
BODY_FAT_PCT  = 30.2
ACTIVITY_MULT = 1.55  # moderately active — crossfit 3-4x/week

lean_mass = WEIGHT_KG * (1 - BODY_FAT_PCT / 100)
BMR  = 370 + (21.6 * lean_mass)
TDEE = BMR * ACTIVITY_MULT
DAILY_CALORIE_TARGET = round(max(TDEE * 0.82, BMR))
DAILY_PROTEIN_TARGET = round(WEIGHT_KG * 1.8)

# ── Database helpers ────────────────────────────────────────────────────────────

def today_il():
    return datetime.now(IL_TZ).strftime("%Y-%m-%d")

def log_food(phone, description, calories, protein, meal_type, source):
    supabase.table("food_log").insert({
        "phone": phone,
        "date": today_il(),
        "time": datetime.now(IL_TZ).strftime("%H:%M"),
        "description": description,
        "calories": calories,
        "protein": protein,
        "meal_type": meal_type,
        "source": source
    }).execute()

def get_today_log(phone):
    result = supabase.table("food_log").select("*").eq("phone", phone).eq("date", today_il()).execute()
    return result.data

def get_recent_days(phone, days=7):
    cutoff = (datetime.now(IL_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    result = supabase.table("food_log").select("*").eq("phone", phone).gte("date", cutoff).execute()
    return result.data

# ── Tools the model can call ────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for current factual info — nutrition facts, research, restaurant/product info not in the profile.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_meal",
            "description": "Log a meal/food Yulia ate, with estimated calories and protein. Call this whenever she reports eating something (text or photo), so it's saved permanently and counted toward her daily total.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Short description of what was eaten"},
                    "calories": {"type": "number", "description": "Estimated calories"},
                    "protein": {"type": "number", "description": "Estimated protein in grams"},
                    "meal_type": {"type": "string", "enum": ["בוקר", "ביניים", "צהריים", "ביניים2", "ערב", "קינוח", "אחר"]}
                },
                "required": ["description", "calories", "protein", "meal_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_summary",
            "description": "Get what Yulia has eaten today and how many calories/protein remain in her budget. Call this when she asks how she's doing today, what she has left, or before suggesting what to eat next.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

def search_web(query):
    try:
        result = tavily.search(query=query, max_results=4, search_depth="basic")
        snippets = [f"- {r['title']}: {r['content'][:300]}" for r in result.get("results", [])]
        return "\n".join(snippets) if snippets else "לא נמצאו תוצאות."
    except Exception as e:
        return f"שגיאת חיפוש: {e}"

def tool_log_meal(phone, args):
    log_food(phone, args["description"], args["calories"], args["protein"], args["meal_type"], "agent")
    return f"נרשם: {args['description']} ({args['calories']} קל', {args['protein']} גר' חלבון)"

def tool_get_daily_summary(phone):
    entries = get_today_log(phone)
    total_cal = sum(e["calories"] for e in entries)
    total_protein = sum(e["protein"] for e in entries)
    remaining_cal = DAILY_CALORIE_TARGET - total_cal
    remaining_protein = DAILY_PROTEIN_TARGET - total_protein
    meals = "\n".join(f"- {e['meal_type']}: {e['description']} ({e['calories']} קל')" for e in entries) or "עדיין לא נרשם כלום היום"
    return f"""יעד יומי: {DAILY_CALORIE_TARGET} קלוריות, {DAILY_PROTEIN_TARGET} גר' חלבון
נאכל עד כה: {total_cal} קלוריות, {total_protein} גר' חלבון
נותר: {remaining_cal} קלוריות, {remaining_protein} גר' חלבון

ארוחות היום:
{meals}"""

# ── Image analysis (vision model describes the food) ──────────────────────────

def analyze_food_image(media_url):
    resp = requests.get(media_url, auth=(os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")))
    image_b64 = base64.b64encode(resp.content).decode()
    mime = resp.headers.get("Content-Type", "image/jpeg")

    vision_resp = groq_client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": "תאר בדיוק מה רואים בתמונה הזו של אוכל — מרכיבים, כמויות משוערות. תהיה ספציפי. בעברית."}
            ]
        }]
    )
    return vision_resp.choices[0].message.content.strip()

# ── System prompt ───────────────────────────────────────────────────────────────

def build_system_prompt():
    return f"""את עוזרת תזונה אישית של יוליה, חמה תומכת ומדויקת. יש לך גישה לפרופיל התזונתי המלא שלה (מהשיחות עם הדיאטנית הילה ממן) וליכולת לעקוב אחרי מה שהיא אוכלת כל יום.

יעד קלורי יומי מחושב: {DAILY_CALORIE_TARGET} קלוריות (לפי נוסחת Katch-McArdle עם אחוזי השומן הידועים שלה, פעילות מותאמת לקרוספיט 3-4 פעמים בשבוע, גירעון מתון לשמירה על שריר).
יעד חלבון יומי: {DAILY_PROTEIN_TARGET} גרם (לתמיכה בשמירה/בניית שריר תוך גירעון קלורי).

תפקידייך:
1. **רישום ארוחות** — כשיוליה מדווחת שאכלה משהו (טקסט או תמונה) — תמיד תקראי ל-log_meal עם הערכת קלוריות וחלבון סבירה, ואז תני משוב.
2. **מעקב יומי** — כשהיא שואלת מה נשאר לה, מה לאכול בהמשך היום, או "איך אני עומדת היום" — תקראי ל-get_daily_summary לפני שאת עונה.
3. **חיפוש מידע** — לשאלות עובדתיות שאת לא בטוחה בהן, תשתמשי ב-search_web. אל תנחשי נתונים.
4. **טון תומך תמיד** — אם אכלה משהו מחוץ לתפריט: לא לבייש, להזכיר בעדינות ובחיוב מה אפשר לעשות אחרת בפעם הבאה, ולהתמקד בתמונה הכוללת (יום אחד לא קובע). אם עמדה ביעד או עשתה בחירה טובה: לציין זאת בכנות ובחום, לא בצורה מוגזמת.
5. **תזכורות לבניית שריר** — היא מתאמנת קרוספיט. כשרלוונטי תזכירי שחלבון מספיק וגירעון לא קיצוני חשובים לשימור/בניית שריר, לא רק לירידה במשקל.

חשוב: את לא דיאטנית מוסמכת. לשינוי יעדים, מצבים רפואיים, או החלטות תזונתיות מהותיות — להפנות להילה.

ענה תמיד בשפה שבה יוליה כותבת (עברית או אנגלית).

--- הפרופיל התזונתי של יוליה ---
{profile}
--- סוף פרופיל ---
"""

conversations = {}

def run_agent_turn(phone, messages):
    """Runs one full agent turn, handling tool calls (possibly multiple rounds)."""
    for _ in range(4):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )
            msg = response.choices[0].message
        except Exception as e:
            if "tool_use_failed" in str(e):
                response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=messages
                )
                msg = response.choices[0].message
            else:
                raise

        if not msg.tool_calls:
            return msg.content

        messages.append(msg)
        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments)
            except Exception:
                args = {}

            if name == "search_web":
                result = search_web(args.get("query", ""))
            elif name == "log_meal":
                result = tool_log_meal(phone, args)
            elif name == "get_daily_summary":
                result = tool_get_daily_summary(phone)
            else:
                result = "כלי לא מוכר"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

    return "קרתה תקלה בעיבוד הבקשה, אפשר לנסות שוב?"

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    from_number  = request.form.get("From", "")
    incoming_msg = request.form.get("Body", "").strip()
    num_media    = int(request.form.get("NumMedia", 0))

    if from_number not in conversations:
        conversations[from_number] = []

    try:
        if num_media > 0:
            media_url = request.form.get("MediaUrl0")
            description = analyze_food_image(media_url)
            user_text = f"[יוליה שלחה תמונה של אוכל]\nתיאור התמונה: {description}"
            if incoming_msg:
                user_text += f"\nהודעה נלווית: {incoming_msg}"
        else:
            user_text = incoming_msg

        conversations[from_number].append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": build_system_prompt()}] + conversations[from_number]

        reply = run_agent_turn(from_number, messages)

        conversations[from_number].append({"role": "assistant", "content": reply})

    except Exception as e:
        print(f"ERROR: {e}")
        reply = "סליחה, הייתה לי תקלה רגעית. אפשר לנסות שוב?"

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
