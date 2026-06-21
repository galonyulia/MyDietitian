import os
import json
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq
from tavily import TavilyClient

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
tavily = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))

def load_file(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    return ""

profile = load_file("yulia_profile.txt")

SYSTEM_PROMPT = f"""את עוזרת תזונה אישית של יוליה. יש לך גישה לפרופיל התזונתי המלא שלה, שנבנה מהשיחות עם הדיאטנית הקלינית שלה הילה ממן, ולתפריט המאושר שלה.

ענה תמיד בשפה שבה יוליה כותבת (עברית או אנגלית).
היי חמה, תומכת ופרקטית.

כשיוליה שואלת שאלה עובדתית שאת לא בטוחה בה, או שדורשת מידע עדכני (ערכים תזונתיים של מזון ספציפי, מחקרים חדשים, מידע על מסעדה/מוצר) — השתמשי בכלי החיפוש search_web במקום לנחש. אל תמציאי נתונים.

חשוב מאוד: את לא דיאטנית מוסמכת ואינך מחליפה את הילה. לכל שינוי בתפריט הרשמי, התאמת יעדים, או שאלה רפואית — הפני את יוליה להילה. את כאן כדי לעזור לה לעקוב, להבין את התפריט הקיים, ולענות על שאלות תזונה כלליות מבוססות מידע אמין.

--- הפרופיל התזונתי של יוליה ---
{profile}
--- סוף פרופיל ---
"""

TOOLS = [{
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Search the web for current, factual information — nutrition facts, research, restaurant/product info, or anything not in Yulia's profile. Use this instead of guessing.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"]
        }
    }
}]

def search_web(query):
    try:
        result = tavily.search(query=query, max_results=4, search_depth="basic")
        snippets = []
        for r in result.get("results", []):
            snippets.append(f"- {r['title']}: {r['content'][:300]}")
        return "\n".join(snippets) if snippets else "לא נמצאו תוצאות."
    except Exception as e:
        return f"שגיאת חיפוש: {e}"

conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number  = request.form.get("From", "")

    if from_number not in conversations:
        conversations[from_number] = []

    conversations[from_number].append({"role": "user", "content": incoming_msg})

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversations[from_number]

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto"
    )

    msg = response.choices[0].message

    # If the model wants to search, do it, then call again with the result
    if msg.tool_calls:
        messages.append(msg)
        for tool_call in msg.tool_calls:
            if tool_call.function.name == "search_web":
                args = json.loads(tool_call.function.arguments)
                result = search_web(args["query"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

        # Second call — model now answers using search results
        final = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages
        )
        reply = final.choices[0].message.content
    else:
        reply = msg.content

    conversations[from_number].append({"role": "assistant", "content": reply})

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
