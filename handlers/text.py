import openai
from ..config import sessions
from ..prompts import SUMM_SYS, SUMM_USER, ANALYSIS_SYS, ANALYSIS_USER, ASSESS_SYS, ASSESS_USER
import asyncio

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
    if text:
        chunks.append(text)
    return chunks

async def send_long(channel, text, **kwargs):
    for chunk in chunk_text(text):
        await channel.send(chunk, **kwargs)

async def on_message(message, client):
    from ..config import sessions
    from ..prompts import SUMM_SYS, SUMM_USER, ANALYSIS_SYS, ANALYSIS_USER, ASSESS_SYS, ASSESS_USER
    import os
    # Ignore messages from bots
    if message.author.bot:
        return
    content = message.content.lower().strip()
    session_key = (message.channel.id, message.author.id)
    # Step 1: Trigger audit session via reply
    if client.user in message.mentions and "audit please" in content:
        # Must be a reply to specify the debate start
        ref = message.reference
        if not ref or not ref.message_id:
            await message.channel.send(
                "Please reply to the last message of the debate you want audited and include 'audit please'."
            )
            return
        # Fetch the referenced message
        try:
            start_msg = await message.channel.fetch_message(ref.message_id)
        except Exception:
            await message.channel.send(
                "Could not fetch the referenced message. Please try again."
            )
            return
        # Fetch the 100 messages preceding that message (exclude bots)
        msgs = []
        async for m in message.channel.history(limit=100, before=start_msg):
            if not m.author.bot:
                msgs.append(m)
        msgs.reverse()
        transcript = "\n".join(f"{m.author.display_name}: {m.content}" for m in msgs)
        openai.api_key = os.getenv("OPENAI_API_KEY")
        if not openai.api_key:
            await message.channel.send("ERROR: OPENAI_API_KEY not set.")
            return
        # Preliminary check: is this actually a debate?
        try:
            assessment = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": ASSESS_SYS},
                    {"role": "user",   "content": ASSESS_USER.format(transcript=transcript)},
                ],
                max_tokens=5,
            )
            answer = assessment.choices[0].message.content.strip().lower()
        except Exception:
            answer = "yes"
        if answer.startswith("n"):
            # No debate detected: prompt user for intent or broader context
            try:
                thread = await message.create_thread(
                    name=f"Audit Thread - {start_msg.author.display_name}",
                    auto_archive_duration=1440
                )
            except Exception:
                thread = message.channel
            sessions[(thread.id, message.author.id)] = {
                "state": "awaiting_confirmation",
                "transcript": transcript,
                "bad_count": 0,
                "start_message_id": start_msg.id,
            }
            await thread.send(
                "⚠️ I didn't detect an actual debate in those messages.\n\n"
                "What would you like to do next?\n"
                "- Reply `ANALYZE` to analyze the current transcript as-is.\n"
                "- Reply `EXPAND` to fetch more messages for broader context.\n"
                "If it still isn't a debate after expansion, you can paste a manual transcript."
            )
            return
        # Summarize the debate
        try:
            summ = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": SUMM_SYS},
                    {"role": "user",   "content": SUMM_USER.format(transcript=transcript)},
                ],
                max_tokens=200,
            )
        except Exception as e:
            await message.channel.send(f"OpenAI error during summary: {e}")
            return
        summary = summ.choices[0].message.content.strip()
        # Create a private thread for this audit
        thread = await message.create_thread(
            name=f"Audit Thread - {start_msg.author.display_name}",
            auto_archive_duration=1440
        )
        # Store session state under the thread channel
        sessions[(thread.id, message.author.id)] = {
            "state": "awaiting_analysis",
            "transcript": transcript,
            "summary": summary,
            "start_message_id": start_msg.id,
        }
        await thread.send(f"**Summary:**\n{summary}\n\nReply `ANALYZE` for full analysis or `EXPAND` for more context.")
        return
    # Step 2: Handle follow-up replies in audit session threads
    if hasattr(message.channel, "id") and (message.channel.id, message.author.id) in sessions:
        session = sessions[(message.channel.id, message.author.id)]
        state = session.get("state")
        if state == "awaiting_confirmation":
            content_upper = message.content.strip().upper()
            if content_upper == "ANALYZE":
                manual_transcript = session.get("transcript")
                openai.api_key = os.getenv("OPENAI_API_KEY")
                if not openai.api_key:
                    await message.channel.send("ERROR: OPENAI_API_KEY not set.")
                    sessions.pop((message.channel.id, message.author.id), None)
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
                    sessions.pop((message.channel.id, message.author.id), None)
                    return
                verdict = analysis.choices[0].message.content.strip()
                await send_long(message.channel, verdict)
                sessions.pop((message.channel.id, message.author.id), None)
                return
            elif content_upper == "EXPAND":
                # Fetch more messages for broader context
                start_message_id = session.get("start_message_id")
                try:
                    start_msg = await message.channel.fetch_message(start_message_id)
                except Exception:
                    await message.channel.send("Could not fetch the referenced message for expansion.")
                    return
                msgs = []
                async for m in message.channel.history(limit=200, before=start_msg):
                    if not m.author.bot:
                        msgs.append(m)
                msgs.reverse()
                transcript = "\n".join(f"{m.author.display_name}: {m.content}" for m in msgs)
                session["transcript"] = transcript
                await message.channel.send("Context expanded. Reply `ANALYZE` to analyze or paste a manual transcript.")
                return
        elif state == "awaiting_analysis":
            content_upper = message.content.strip().upper()
            if content_upper == "ANALYZE":
                transcript = session.get("transcript")
                openai.api_key = os.getenv("OPENAI_API_KEY")
                if not openai.api_key:
                    await message.channel.send("ERROR: OPENAI_API_KEY not set.")
                    sessions.pop((message.channel.id, message.author.id), None)
                    return
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
                    sessions.pop((message.channel.id, message.author.id), None)
                    return
                verdict = analysis.choices[0].message.content.strip()
                await send_long(message.channel, verdict)
                sessions.pop((message.channel.id, message.author.id), None)
                return
    # No other triggers
    return
