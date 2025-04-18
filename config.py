import os
from dotenv import load_dotenv
import discord

# Load environment variables from .env file if present
load_dotenv()

# In-memory sessions for multi-step audits: keyed by (channel_id, user_id)
sessions = {}
# In-memory live debate voice sessions: keyed by guild_id
live_sessions = {}

# Configure Discord intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
