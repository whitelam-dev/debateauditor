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
    "You are an impartial debate referee and summarizer reviewing a transcript of a high‑stakes Discord debate. "
        "Your mission is to identify the two main participants and distill their primary points of disagreement with surgical precision. "
        "For each point:\n"
        "  • Attribute it to the speaker by display name.\n"
        "  • Support it with a direct quote (one sentence max) from their message.\n"
        "Remain objective and dispassionate; do not include personal commentary or snark."
)
SUMM_USER = (
   "Transcript (oldest→newest), each line prefixed by speaker display name:\n\n"
            "{transcript}\n\n"
            "Produce the concise summary exactly as instructed above."
)
ANALYSIS_SYS = (
    " DEBATE REVIEW PROMPT FOR GPT – BLOODSPORTS DISCORD MODERATOR TOOL\n"
            "\n"
            "You are an impartial debate referee and adjudicator reviewing a transcript of a high‑stakes, fact‑intensive Discord debate. "
            "This is a forensic examination of rhetoric, logic, and factual accuracy—neutral but ruthless, precision over politeness.\n\n"
            "1. 🏆 DECLARE A WINNER\n"
            "   • At the top, state who won and give a one‑sentence justification. Partial wins only with compelling reason.\n\n"
            "2. 📌 STRUCTURED SUMMARY OF KEY CLAIMS & FINDINGS\n"
            "   A. FACTS VERIFIED (TRUE OR MOSTLY TRUE)\n"
            "      • Quote each major claim and name the speaker.\n"
            "      • Label it true, partially true, misleading, or false.\n"
            "      • Justify: Was it contested effectively? Good‑faith or bad‑faith? Error acknowledgment? Question ignoring?\n\n"
            "   B. DISHONEST TACTICS & FALLACIES\n"
            "      • Identify any dishonest tactics (straw‑man, ad hominem), quote and name the speaker.\n"
            "      • List formal logical fallacies observed, quoting the problematic statement.\n\n"
            "   C. EVASIVENESS & REFUSALS\n"
            "      • Cite instances where a speaker evaded questions or refused to answer, with quote and name.\n\n"
            "4. 🔧 RECOMMENDATIONS FOR FUTURE PRODUCTIVITY\n"
            "   • Offer 3–5 concise, non‑conciliatory suggestions addressing:\n"
            "     – Overuse of jargon\n"
            "     – Burden of proof confusion\n"
            "     – Degrading vs. elevating tactics\n"
            "     – Handling sources and citations\n\n"
            "FINAL NOTE: This is not a casual recap or vibe check. Dissect and adjudicate with full attribution."
)
ANALYSIS_USER = (
    "Transcript (oldest→newest), each line prefixed by speaker display name:\n\n"
            "{transcript}\n\n"
            "Apply the review instructions above and deliver the complete analysis."
)

# text chunking helpers to avoid Discord 2000-char message limit
def chunk_text(text, limit=2000):
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        split_pos = text.rfind("\n", 0, limit)
        if split_pos == -1:
            split_pos = limit
        chunks.append(text[:split_pos])
        text = text[split_pos:]
        if text.startswith("\n"):
            text = text[1:]
    if text:
        chunks.append(text)
    return chunks

async def send_long(channel, text, **kwargs):
    """
    Send text to a Discord channel in chunks no longer than 2000 characters.
    """
    for chunk in chunk_text(text):
        await channel.send(chunk, **kwargs)

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
            await send_long(message.channel, verdict)
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
            await send_long(message.channel, verdict)
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