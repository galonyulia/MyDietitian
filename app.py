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

# Profile is compact — extracted once, loaded at startup
profile   = load_file("yulia_profile.txt")
meal_plan = load_file("meal_plan.txt")

# Fallback to raw chat if profile not ready yet
context = profile if profile else load_file("dietitian_chat.txt")

SYSTEM_PROMPT = f"""את עוזרת תזונה אישית של יוליה. יש לך גישה לפרופיל התזונתי המלא שלה, שנבנה מהשיחות עם הדיאטנית הקלינית שלה הילה ממן.

ענה תמיד בשפה שבה יוליה כותבת (עברית או אנגלית).
היי חמה, תומכת ופרקטית. השתמשי במידע הספציפי שיש לך על יוליה.
לשינויים רפואיים — הפני להילה.

--- הפרופיל התזונתי של יוליה ---
{context}
--- סוף פרופיל ---
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
