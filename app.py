import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Load dietitian chat history once at startup
chat_history = ""
if os.path.exists("dietitian_chat.txt"):
    with open("dietitian_chat.txt", "r", encoding="utf-8") as f:
        chat_history = f.read()

SYSTEM_PROMPT = f"""You are a personal AI dietitian assistant for Yulia. 

You have access to Yulia's full conversation history with her clinical dietitian Hila. 
Use this history to understand her health background, goals, dietary preferences, restrictions, 
blood test results, meal plans, and any advice she was given.

Always answer in the same language Yulia writes in (Hebrew or English).
Be warm, personal, and practical. Reference her specific history when relevant.
If she asks about food tracking, help her log and give feedback.
If she asks for meal plans, base them on what you know about her preferences and goals.

--- DIETITIAN CONVERSATION HISTORY ---
{chat_history}
--- END OF HISTORY ---

You are not a replacement for a real dietitian — always encourage her to consult Hila for medical decisions.
"""

# Store conversation history per phone number
conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")

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
