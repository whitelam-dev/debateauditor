from config import client
from handlers.text import on_message as text_on_message
from handlers.voice import live_recording, process_audio_segment

# Attach event handlers
@client.event
async def on_ready():
    print(f"DebateAuditor online as {client.user} (ID: {client.user.id})")

from config import client
from handlers.text import on_message as text_on_message
from handlers.voice import live_recording, process_audio_segment

@client.event
def on_ready():
    print(f"DebateAuditor online as {client.user} (ID: {client.user.id})")

@client.event
def on_message(message):
    # Only dispatch text commands; voice commands are invoked by text handler as needed
    import asyncio
    asyncio.create_task(text_on_message(message, client))

if __name__ == "__main__":
    import os
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set.")
        exit(1)
    client.run(token)
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
            "state": "awaiting_confirmation",
            "transcript": transcript,
            "bad_count": 0,
            "start_message_id": start_msg.id,
        }
        # Send the brief summary and prompt for full analysis
        await thread.send(
            f"Here is a brief summary of the key points and disagreements:\n\n{summary}\n\n"
            "What would you like to do next?\n"
            "- Reply `ANALYZE` to perform a full debate analysis on this transcript.\n"
            "- Reply `EXPAND` to fetch more messages (up to 300) for additional context."
        )
        return

    # Step 2: Handle confirmation
    if session_key in sessions and sessions[session_key]["state"] == "awaiting_confirmation":
        # Handle user choice: ANALYZE or EXPAND
        if content == "analyze":
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
        elif content == "expand":
            # First bad: expand to 300 messages and re-summarize
            bad_count = sessions[session_key].get("bad_count", 0)
            if bad_count == 0:
                # Expand to 300 messages before the original start point
                start_id = sessions[session_key].get("start_message_id")
                start_msg = None
                if start_id:
                    try:
                        start_msg = await message.channel.fetch_message(start_id)
                    except Exception:
                        start_msg = None
                msgs = []
                if start_msg:
                    async for m in message.channel.history(limit=300, before=start_msg):
                        if not m.author.bot:
                            msgs.append(m)
                else:
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
                            {"role": "user",   "content": SUMM_USER.format(transcript=transcript)},
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
                await message.channel.send(
                    f"Here is an expanded summary of the key points and disagreements:\n\n{summary}\n\n"
                    "What would you like to do next?\n"
                    "- Reply `ANALYZE` to perform a full debate analysis on this expanded transcript.\n"
                    "- Reply `EXPAND` to fetch even more context or paste a manual transcript when prompted."
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

# --- Live voice debate recording and summarization ---
async def _recording_callback(sink, guild_id):
    # Called when a recording chunk finishes; process that segment
    await process_audio_segment(sink, guild_id)

async def live_recording(guild_id):
    session = live_sessions.get(guild_id)
    if not session:
        return
    voice_client = session["voice_client"]
    while session.get("recording"):
        sink = WaveSink()
        # keep track of the current sink for any final processing if needed
        session["current_sink"] = sink
        # start recording; callback must be a coroutine function
        voice_client.start_recording(sink, _recording_callback, guild_id)
        # record for 3 minutes
        await asyncio.sleep(180)
        # stop current chunk; this will trigger _recording_callback
        voice_client.stop_recording()
    # clear the current sink reference when done
    session.pop("current_sink", None)

async def process_audio_segment(sink, guild_id):
    session = live_sessions.get(guild_id)
    if not session:
        return
    thread = session["thread"]
    # Collect raw audio frames
    if hasattr(sink, "buffers"):
        chunks = sink.buffers
    elif hasattr(sink, "audio_data"):
        chunks = sink.audio_data
    else:
        await thread.send("Unsupported sink; cannot process audio.")
        return
    transcripts = []
    for user_id, frames in chunks.items():
        if not frames:
            continue
        buffer = io.BytesIO()
        wf = wave.open(buffer, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"".join(frames))
        wf.close()
        buffer.seek(0)
        try:
            resp = openai.Audio.transcribe("whisper-1", buffer)
            text = resp.get("text") if isinstance(resp, dict) else getattr(resp, "text", "")
        except Exception as e:
            await thread.send(f"Error during transcription for <@{user_id}>: {e}")
            continue
        member = session["voice_client"].guild.get_member(user_id)
        name = member.display_name if member else str(user_id)
        transcripts.append(f"{name}: {text}")
    if not transcripts:
        return
    session["full_transcript"] += "\n".join(transcripts) + "\n"
    try:
        summ = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an impartial debate referee summarizing a live segment of a debate. Provide a concise summary of the main points made in the following transcript."},
                {"role": "user", "content": "Transcript:\n" + "\n".join(transcripts)},
            ],
            max_tokens=150,
        )
        summary = summ.choices[0].message.content.strip()
    except Exception as e:
        await thread.send(f"Error during summary: {e}")
        return
    await thread.send(f"**Live summary (last 3 minutes):**\n{summary}")

if __name__ == "__main__":
    import os
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN not set.")
        exit(1)
    client.run(token)