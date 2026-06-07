import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import google.generativeai as genai

app = Flask(__name__)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="You are a helpful WhatsApp assistant. Keep replies concise."
)

# Store chat sessions per phone number
chats = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")

    if from_number not in chats:
        chats[from_number] = model.start_chat(history=[])

    reply = chats[from_number].send_message(incoming_msg).text

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
