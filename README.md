# debateauditor
## Voice Debate Live Transcription

  - `!startdebate`: Bot joins your current voice channel and begins live transcription and summarization every 3 minutes. Summaries are posted in a "DEBATE LIVE NOTES" thread in text.
  - `!enddebate`: Bot stops recording, generates a full debate analysis of the complete transcript, and posts it in the live notes thread.

## Usage

1. Setup
   - Create a `.env` file at the project root with:
     ```
     DISCORD_TOKEN=your_discord_bot_token
     OPENAI_API_KEY=your_openai_api_key
     ```
   - Install standard dependencies:
     ```bash
     pip install -r requirements.txt
     ```
   - (Optional) For voice-based live transcription, first remove any existing discord.py and then install the upstream build with voice‑receive support and PyNaCl:
    ```bash
    pip uninstall -y discord.py
    pip install -U git+https://github.com/Rapptz/discord.py PyNaCl
    ```
   - Run the bot:
     ```bash
     python bot.py
     ```

2. Text-based Debate Audit
   - In a Discord text channel, start an audit by replying to the last message of the debate and mentioning the bot with `audit please` (e.g. `@DebateAuditor audit please`).
   - The bot will fetch the preceding messages and post a concise summary in a private thread.
    - Reply `ANALYZE` to receive a full analysis, or `EXPAND` to fetch more messages (up to 300) for additional context. If the expanded context still isn't a debate, you'll be prompted to paste a manual transcript.

3. Voice-based Live Debate
   - Use `!startdebate` in any text channel while in a voice channel. The bot will join your voice channel and begin transcription, posting live summaries every 3 minutes in a thread named "DEBATE LIVE NOTES".
   - When the debate ends, use `!enddebate` to stop recording. The bot will generate a full analysis of the entire debate transcript and post it in the live notes thread.

Enjoy using DebateAuditor to get structured, impartial insights on your debates!