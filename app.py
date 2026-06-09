import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def load_file(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return ""

chat_history = load_file("dietitian_chat.txt")
meal_plan    = load_file("meal_plan.txt")

SYSTEM_PROMPT = f"""את עוזרת תזונה אישית של יוליה גלאון. יש לך גישה מלאה לשיחה שלה עם הדיאטנית הקלינית שלה הילה ממן, ולתפריט התזונה האישי שלה.

פרטים אישיים של יוליה:
- גובה: 1.57, משקל: 79 ק"ג, גיל: 38
- אחוזי שומן: 30.2%, היקף בטן: 56.4
- מטרה: להוריד 10 ק"ג של שומן
- מתחילה את היום ב-6 בבוקר
- יש לה ילדים

תפקידך:
1. לענות על שאלות תזונה בהתבסס על ההיסטוריה וההמלצות של הילה
2. לעזור למעקב אחרי אכילה יומית ולתת פידבק
3. להציע ארוחות בהתאם לתפריט שנקבע
4. לענות תמיד בשפה שבה יוליה כותבת (עברית או אנגלית)
5. להיות חמה, תומכת ופרקטית

חשוב: את לא מחליפה דיאטנית אמיתית – לשינויים רפואיים יש להפנות להילה.

--- תפריט התזונה האישי ---
{meal_plan}
--- סוף תפריט ---

--- היסטוריית השיחה עם הדיאטנית ---
{chat_history}
--- סוף היסטוריה ---
"""

conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number  = request.form.get("From", "")

    if from_number not in conversations:
        conversations[from_number] = []

    conversations[from_number].append({"role": "user", "content": incoming_msg})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversations[from_number]
    )

    reply = response.choices[0].message.content
    conversations[from_number].append({"role": "assistant", "content": reply})

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
