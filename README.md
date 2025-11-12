## Telegram Todoist Voice Notes Bot

This project is a Telegram bot that turns voice messages or audio files into Todoist tasks.  
Incoming audio is transcribed locally using [`faster-whisper`](https://github.com/guillaumekln/faster-whisper); the resulting text is sent to Todoist as a new task in the project you choose.

### Features
- `/start` greets the user and explains the available commands.
- `/progetti` shows inline buttons with all Todoist projects and lets you set your default destination per user (remains active until changed).
- Automatically downloads Telegram voice notes (`.ogg/.opus`) and audio files, converts them to WAV, runs transcription, and posts the result to Todoist.
- Falls back to the project set in `config.py` when the user has not chosen one.
- Displays the Todoist creation status and the project name/ID in the bot reply.

### Requirements
- Python 3.10+ recommended.
- [`ffmpeg`](https://ffmpeg.org/download.html) accessible in your system `PATH`.
- A Telegram bot token from [BotFather](https://core.telegram.org/bots#botfather).
- A Todoist REST API token from the Todoist settings page.
- Internet access to download the Whisper model the first time the bot runs.

### Project Structure
```
bot.py          # Telegram entry point and message handling
trascrivi.py    # Audio conversion and transcription helper
config.py       # Local configuration (tokens, model settings)
```

### Installation
1. Clone or copy the repository into your workspace.
2. (Recommended) create a virtual environment and activate it:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate
   ```
3. Install dependencies (for example from `requirements.txt` if provided):
   ```powershell
   pip install -r requirements.txt
   ```
   If you do not have a requirements file, install the minimum packages manually:
   ```powershell
   pip install python-telegram-bot[httpx] faster-whisper ffmpeg-python httpx huggingface_hub
   ```
4. Ensure `ffmpeg` is installed and reachable (e.g. `where ffmpeg` in PowerShell should find it).

### Configuration
All configuration lives in `config.py`. Update the following values:

- `BOT_TOKEN`: Telegram bot token.
- `TODOIST_API_TOKEN`: Todoist REST token.
- `TODOIST_PROJECT_ID` (optional): default Todoist project ID used when the user has not selected one through `/progetti`.
- Whisper-related options let you choose the model, local cache directory, device, and compute type.

You can also override the bot token at runtime with the `TELEGRAM_BOT_TOKEN` environment variable.

### Running the Bot
From the project root:
```powershell
python bot.py
```

The bot starts polling Telegram updates. Stop it with `Ctrl+C`.

### Usage Flow
1. Open a chat with your bot on Telegram.
2. Send `/start` once to get a welcome message.
3. Send `/progetti` to fetch your Todoist projects and tap the button of the project you want as default. The selection persists for that Telegram user until changed.
4. Send a voice note or attach an audio file.  
   - The bot downloads it, converts it to WAV, and transcribes it.
   - The transcription text becomes the content of a Todoist task under the selected project.
   - The bot replies with the transcription plus the Todoist result message.

If transcription fails or returns empty text, the bot informs you and avoids creating a Todoist task.

### Troubleshooting
- **Missing `ffmpeg`**: Install it and add the `bin` folder to your `PATH`.
- **Model download issues**: verify your internet connection and that the Hugging Face model ID defined in `config.py` exists.
- **Todoist errors**: check the bot logs for HTTP status codes (e.g. 401 for invalid token).
- **Performance**: choose a smaller Whisper model (e.g. `tiny` or `base`) in `config.py` if CPU resources are limited.

### Extending
- Add new commands or handlers in `bot.py` for extra automation.
- Replace the default transcription language by editing the `trascrivi` call in `bot.py`.
- Integrate other task managers by adapting `_send_to_todoist`.

### License
No license is specified. Add one if you plan to distribute the project.

