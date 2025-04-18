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

# The on_message handler will be imported and attached in bot.py
async def on_message(message, client):
    # Place the full on_message logic here, referencing config and prompts as needed
    pass
