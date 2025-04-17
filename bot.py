import os
import discord
import openai
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()
# In-memory sessions for multi-step audits: keyed by (channel_id, user_id)
sessions = {}

# Prompt templates for summarization and analysis
SUMM_SYS = (
    "You are an elite debate referee and master summarizer. "
    "You see every nuance, ignore side-chatter, and distill only the heart of the argument."
)
SUMM_USER = (
    "Here is the last {n} messages of a channel (oldest→newest), speaker name prepended:\n\n"
    "{transcript}\n\n"
    "In no more than five sentences,\n"
    "- Identify the two main participants (by display name).\n"
    "- Summarize their key points of disagreement.\n"
    "- Do not mention anything else."
)
ANALYSIS_SYS = (
    "You are the world's most merciless debate critic. "
    "You cut through bullshit, expose every fallacy, and call out dishonesty in brutal detail. "
    "No fluff, no euphemisms."
)
ANALYSIS_USER = (
    "The full transcript of the debate is below (oldest→newest):\n\n"
    "{transcript}\n\n"
    "Evaluate, in a single readable report:\n"
    "1. Who won the debate and why (strongest logic, evidence, rhetoric).\n"
    "2. Who was factually accurate or inaccurate.\n"
    "3. Any dishonest tactics (straw-man, quote-mining, ad hominem, etc.).\n"
    "4. Formal logical fallacies employed.\n"
    "5. Instances of evasiveness or refusal to answer.\n"
    "6. Dramatic blood-sport highlights - moments of real knock-down arguments.\n\n"
    "Use bullet points or numbered sections, bold the verdict, and don't pull punches."
)

# Configure Discord intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"DebateAuditor online as {client.user} (ID: {client.user.id})")

@client.event
async def on_message(message):
    # Ignore messages from bots
    if message.author.bot:
        return

    content = message.content.lower().strip()
    session_key = (message.channel.id, message.author.id)

    # Step 1: Trigger audit session
    if client.user in message.mentions and "audit please" in content:
        # Fetch last 150 messages (exclude bots)
        msgs = []
        async for m in message.channel.history(limit=150):
            if not m.author.bot:
                msgs.append(m)
        msgs.reverse()
        transcript = "\n".join(f"{m.author.display_name}: {m.content}" for m in msgs)

        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            await message.channel.send("ERROR: OPENAI_API_KEY not set.")
            return

        # Summarize the debate
        try:
            summ = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": SUMM_SYS},
                    {"role": "user",   "content": SUMM_USER.format(n=150, transcript=transcript)},
                ],
                max_tokens=200,
            )
        except Exception as e:
            await message.channel.send(f"OpenAI error during summary: {e}")
            return
        summary = summ.choices[0].message.content.strip()

        # Store session state
        sessions[session_key] = {"state": "awaiting_confirmation", "transcript": transcript, "bad_count": 0}
        await message.channel.send(
            f"Confirm this is the debate you want to audit:\n\n{summary}\n\nPlease reply Good or Bad."
        )
        return

    # Step 2: Handle confirmation
    if session_key in sessions and sessions[session_key]["state"] == "awaiting_confirmation":
        if content == "good":
            # Deep analysis
            transcript = sessions[session_key]["transcript"]
            try:
                analysis = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": ANALYSIS_SYS},
                        {"role": "user",   "content": ANALYSIS_USER.format(transcript=transcript)},
                    ],
                    max_tokens=500,
                )
            except Exception as e:
                await message.channel.send(f"OpenAI analysis error: {e}")
                sessions.pop(session_key, None)
                return
            verdict = analysis.choices[0].message.content.strip()
            await message.channel.send(verdict)
            sessions.pop(session_key, None)
            return
        elif content == "bad":
            # First bad: expand to 300 messages and re-summarize
            bad_count = sessions[session_key].get("bad_count", 0)
            if bad_count == 0:
                # Fetch last 300 messages
                msgs = []
                async for m in message.channel.history(limit=300):
                    if not m.author.bot:
                        msgs.append(m)
                msgs.reverse()
                transcript = "\n".join(f"{m.author.display_name}: {m.content}" for m in msgs)
                # Re-summarize
                try:
                    summ = openai.ChatCompletion.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": SUMM_SYS},
                            {"role": "user",   "content": SUMM_USER.format(n=300, transcript=transcript)},
                        ],
                        max_tokens=300,
                    )
                except Exception as e:
                    await message.channel.send(f"OpenAI re-summary error: {e}")
                    sessions.pop(session_key, None)
                    return
                summary = summ.choices[0].message.content.strip()
                # Update session
                sessions[session_key]["transcript"] = transcript
                sessions[session_key]["bad_count"] = 1
                # Ask for confirmation again
                await message.channel.send(
                    f"Confirm this is the debate you want to audit:\n\n{summary}\n\nPlease reply Good or Bad."
                )
                return
            # Second bad: request manual transcript
            prompt = (
                "You indicated the summary is still incorrect. "
                "Please paste the full debate transcript in a direct reply to this message. "
                "I will read only your first reply."
            )
            bot_msg = await message.channel.send(prompt)
            sessions[session_key]["state"] = "awaiting_manual_transcript"
            sessions[session_key]["prompt_id"] = bot_msg.id
            return

    # Step 3: Handle manual transcript reply
    if session_key in sessions and sessions[session_key]["state"] == "awaiting_manual_transcript":
        # Accept only the first direct reply from the initiator
        ref = message.reference
        if ref and ref.message_id == sessions[session_key].get("prompt_id"):
            # Check for a .txt attachment; if present, download and use its contents
            manual_transcript = None
            for att in message.attachments:
                if att.filename.lower().endswith('.txt'):
                    try:
                        data = await att.read()
                        manual_transcript = data.decode('utf-8', errors='ignore')
                    except Exception:
                        # Fallback to message content if attachment fails
                        manual_transcript = None
                    break
            # If no valid attachment, use message content
            if not manual_transcript:
                manual_transcript = message.content
            openai.api_key = os.getenv("OPENAI_API_KEY")
            if not openai.api_key:
                await message.channel.send("ERROR: OPENAI_API_KEY not set.")
                sessions.pop(session_key, None)
                return
            try:
                analysis = openai.ChatCompletion.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": ANALYSIS_SYS},
                        {"role": "user",   "content": ANALYSIS_USER.format(transcript=manual_transcript)},
                    ],
                    max_tokens=500,
                )
            except Exception as e:
                await message.channel.send(f"OpenAI analysis error: {e}")
                sessions.pop(session_key, None)
                return
            verdict = analysis.choices[0].message.content.strip()
            await message.channel.send(verdict)
            sessions.pop(session_key, None)
        return

    # No other triggers
    return

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set.")
        exit(1)
    client.run(token)