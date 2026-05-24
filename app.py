from flask import Flask, request
import plivo
from openai import OpenAI
import os

app = Flask(__name__)

# ── Clients ──────────────────────────────────────────────────────────────────
plivo_client = plivo.RestClient(
    auth_id=os.environ["PLIVO_AUTH_ID"],
    auth_token=os.environ["PLIVO_AUTH_TOKEN"]
)
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

# ── AI Personality ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a professional and empathetic collections representative for IrisInsights.
Your goal is to help people resolve their outstanding balances in a respectful, compliant manner.

Guidelines:
- Always be polite, calm, and professional
- Never threaten, harass, or use aggressive language
- Offer payment plan options when appropriate
- Keep replies short and clear (under 300 characters when possible)
- If someone disputes the debt, let them know they can call us to resolve it
- If someone says STOP or asks not to be contacted, confirm they are opted out
- Always follow FDCPA (Fair Debt Collection Practices Act) guidelines
- Do not disclose account details unless the person confirms their identity"""

# ── Conversation Memory (per phone number) ────────────────────────────────────
conversations = {}

# ── Webhook ───────────────────────────────────────────────────────────────────
@app.route("/sms", methods=["POST"])
def handle_sms():
    from_number = request.form.get("From")
    to_number   = request.form.get("To")
    text        = request.form.get("Text", "").strip()

    print(f"📩 Incoming SMS from {from_number}: {text}")

    # Handle opt-out keywords
    if text.upper() in ["STOP", "UNSUBSCRIBE", "QUIT", "CANCEL", "END", "OPTOUT"]:
        send_sms(to_number, from_number,
                 "You have been unsubscribed and will receive no further messages. "
                 "Reply START to resubscribe.")
        conversations.pop(from_number, None)
        return "OK", 200

    # Handle opt-in keywords
    if text.upper() in ["START", "SUBSCRIBE"]:
        send_sms(to_number, from_number,
                 "You are now subscribed to IrisInsights messages. "
                 "Reply STOP at any time to unsubscribe.")
        return "OK", 200

    # Build conversation history for this contact
    if from_number not in conversations:
        conversations[from_number] = []

    conversations[from_number].append({"role": "user", "content": text})

    # Keep only last 10 messages to stay within token limits
    if len(conversations[from_number]) > 10:
        conversations[from_number] = conversations[from_number][-10:]

    # Call OpenAI
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}]
                     + conversations[from_number],
            max_tokens=300,
            temperature=0.7
        )
        ai_reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ OpenAI error: {e}")
        ai_reply = ("We're experiencing a brief issue. Please call us directly "
                    "or try again shortly.")

    # Save AI reply to conversation history
    conversations[from_number].append({"role": "assistant", "content": ai_reply})

    # Send reply via Plivo
    send_sms(to_number, from_number, ai_reply)
    print(f"📤 Replied to {from_number}: {ai_reply}")

    return "OK", 200


def send_sms(src, dst, text):
    """Send an SMS via Plivo."""
    try:
        plivo_client.messages.create(src=src, dst=dst, text=text)
    except Exception as e:
        print(f"❌ Plivo send error: {e}")


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return "✅ IrisInsights SMS Agent is running.", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
