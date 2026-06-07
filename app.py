import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from groq import Groq

app = Flask(__name__)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Store conversation history per phone number
conversations = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.form.get("Body", "").strip()
    from_number = request.form.get("From", "")

    if from_number not in conversations:
        conversations[from_number] = [
            {"role": "system", "content": "You are a helpful WhatsApp assistant. Keep replies concise."}
        ]

    conversations[from_number].append({"role": "user", "content": incoming_msg})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=conversations[from_number]
    )

    reply = response.choices[0].message.content

    conversations[from_number].append({"role": "assistant", "content": reply})

    twilio_resp = MessagingResponse()
    twilio_resp.message(reply)
    return str(twilio_resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
