import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import anthropic

app = Flask(__name__)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Store conversation history per phone number
conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")

    if from_number not in conversations:
        conversations[from_number] = []

    conversations[from_number].append({
        "role": "user",
        "content": incoming_msg
    })

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="You are a helpful WhatsApp assistant. Keep replies concise.",
        messages=conversations[from_number]
    )

    reply = response.content[0].text

    conversations[from_number].append({
        "role": "assistant",
        "content": reply
    })

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
