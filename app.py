import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from google import genai
from google.genai import types

app = Flask(__name__)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Store conversation history per phone number
conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")

    if from_number not in conversations:
        conversations[from_number] = []

    conversations[from_number].append(
        types.Content(role="user", parts=[types.Part(text=incoming_msg)])
    )

    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        config=types.GenerateContentConfig(
            system_instruction="You are a helpful WhatsApp assistant. Keep replies concise."
        ),
        contents=conversations[from_number]
    )

    reply = response.text

    conversations[from_number].append(
        types.Content(role="model", parts=[types.Part(text=reply)])
    )

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
