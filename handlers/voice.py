import io
import wave
import openai
from ..config import live_sessions
import asyncio

async def _recording_callback(sink, guild_id):
    from .voice import process_audio_segment
    await process_audio_segment(sink, guild_id)

async def live_recording(guild_id):
    session = live_sessions.get(guild_id)
    if not session:
        return
    voice_client = session["voice_client"]
    from discord.sinks import WaveSink
    while session.get("recording"):
        sink = WaveSink()
        session["current_sink"] = sink
        voice_client.start_recording(sink, _recording_callback, guild_id)
        await asyncio.sleep(180)
        voice_client.stop_recording()
    session.pop("current_sink", None)

async def process_audio_segment(sink, guild_id):
    session = live_sessions.get(guild_id)
    if not session:
        return
    thread = session["thread"]
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
