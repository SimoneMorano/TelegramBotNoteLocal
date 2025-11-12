import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Mapping, Optional, Tuple

import httpx

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
try:  # pragma: no cover - workaround bug PTB <=20.8
    from telegram.ext import _updater
except ImportError:  # pragma: no cover
    _updater = None

try:
    from config import BOT_TOKEN, TODOIST_API_TOKEN, TODOIST_PROJECT_ID
except ImportError:
    BOT_TOKEN = ""
    TODOIST_API_TOKEN = ""
    TODOIST_PROJECT_ID = ""

if _updater is not None:  # pragma: no cover - workaround runtime
    slots = getattr(_updater.Updater, "__slots__", ())
    if "__polling_cleanup_cb" not in slots:
        _updater.Updater.__slots__ = tuple(slots) + ("__polling_cleanup_cb",)

from trascrivi import trascrivi

TODOIST_API_BASE = "https://api.todoist.com/rest/v2"
TODOIST_PROJECTS_CACHE_TTL = 600
TODOIST_PROJECTS_CACHE_KEY = "todoist_projects_cache"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        (
            "Ciao! Inviami un messaggio vocale o un file audio e proverò a trascriverlo.\n"
            "Usa /progetti per scegliere il progetto Todoist di default."
        )
    )


def _extract_audio_info(update: Update) -> Tuple[Optional[str], Optional[str]]:
    """
    Restituisce (file_id, suffix) dal messaggio ricevuto.
    """
    message = update.message
    if message is None:
        return None, None

    if message.voice:
        suffix = ".ogg"
        return message.voice.file_id, suffix

    if message.audio:
        suffix = Path(message.audio.file_name or ".ogg").suffix or ".ogg"
        return message.audio.file_id, suffix

    if message.document and message.document.mime_type:
        if message.document.mime_type.startswith("audio/"):
            suffix = Path(message.document.file_name or ".ogg").suffix or ".ogg"
            return message.document.file_id, suffix

    return None, None


def _todoist_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {TODOIST_API_TOKEN}",
        "Content-Type": "application/json",
    }


async def _fetch_todoist_projects_from_api() -> List[Mapping[str, Any]]:
    if not TODOIST_API_TOKEN:
        return []

    headers = _todoist_headers()

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{TODOIST_API_BASE}/projects",
            headers=headers,
        )

    if response.status_code >= 300:
        logging.error(
            "Recupero progetti Todoist fallito (%s): %s",
            response.status_code,
            response.text,
        )
        return []

    data = response.json()
    if not isinstance(data, list):
        logging.error("Formato risposta progetti Todoist inatteso: %s", data)
        return []
    return data


async def _get_todoist_projects(
    bot_data: Dict[str, Any], force_refresh: bool = False
) -> List[Mapping[str, Any]]:
    now = time.time()
    cache_entry = bot_data.get(TODOIST_PROJECTS_CACHE_KEY)
    if (
        not force_refresh
        and cache_entry
        and cache_entry.get("expires_at", 0) > now
    ):
        return cache_entry.get("projects", [])

    projects = await _fetch_todoist_projects_from_api()
    bot_data[TODOIST_PROJECTS_CACHE_KEY] = {
        "projects": projects,
        "expires_at": now + TODOIST_PROJECTS_CACHE_TTL,
    }
    return projects


def _resolve_user_project(context: ContextTypes.DEFAULT_TYPE) -> Tuple[Optional[str], Optional[str]]:
    user_project_id = context.user_data.get("todoist_project_id")
    user_project_name = context.user_data.get("todoist_project_name")
    if user_project_id:
        return user_project_id, user_project_name

    if TODOIST_PROJECT_ID:
        # Prova a reperire il nome dal cache progetti se disponibile
        cache_entry = context.bot_data.get(TODOIST_PROJECTS_CACHE_KEY, {})
        projects = cache_entry.get("projects", [])
        default_project = next(
            (proj for proj in projects if str(proj.get("id")) == str(TODOIST_PROJECT_ID)),
            None,
        )
        default_name = default_project.get("name") if default_project else None
        return str(TODOIST_PROJECT_ID), default_name

    return None, None


async def _send_to_todoist(content: str, project_id: Optional[str]) -> tuple[bool, str]:
    """
    Invia una nuova attività a Todoist con il contenuto trascritto.
    Restituisce una tupla (successo, messaggio).
    """
    if not TODOIST_API_TOKEN:
        return False, "Token Todoist non configurato."

    payload = {"content": content.strip() or "(trascrizione vuota)"}
    if project_id:
        payload["project_id"] = project_id

    headers = _todoist_headers()

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{TODOIST_API_BASE}/tasks",
            headers=headers,
            json=payload,
        )

    if response.status_code >= 300:
        logging.error(
            "Creazione task Todoist fallita (%s): %s",
            response.status_code,
            response.text,
        )
        return False, f"Todoist ha risposto con errore {response.status_code}."

    task = response.json()
    return True, f"Attività creata su Todoist (id: {task.get('id')})."


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return

    file_id, suffix = _extract_audio_info(update)
    if not file_id:
        await message.reply_text("Non riesco a trovare un file audio in questo messaggio.")
        return

    waiting_message = await message.reply_text("Ricevuto! Scarico l'audio e avvio la trascrizione...")

    temp_path: Optional[str] = None
    try:
        telegram_file = await context.bot.get_file(file_id)
        with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
        await telegram_file.download_to_drive(custom_path=temp_path)

        loop = asyncio.get_running_loop()
        trascritto = await loop.run_in_executor(
            None, lambda: trascrivi(temp_path, verbose=False)
        )

        todoist_status = ""
        project_id, project_name = _resolve_user_project(context)
        if trascritto:
            _ok, todoist_status = await _send_to_todoist(trascritto, project_id)
        else:
            _ok, todoist_status = False, "Trascrizione vuota, nulla da inviare a Todoist."

        base_message = "<b>Trascrizione completata!</b>\n\n"
        base_message += trascritto or "(nessun testo riconosciuto)"
        if todoist_status:
            base_message += f"\n\n<code>{todoist_status}</code>"
        if project_name:
            base_message += f"\n\n<code>Progetto: {project_name}</code>"
        elif project_id:
            base_message += f"\n\n<code>Progetto ID: {project_id}</code>"

        await waiting_message.edit_text(
            base_message,
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Errore durante la trascrizione Telegram: %s", exc)
        await waiting_message.edit_text(
            "Si è verificato un errore durante la trascrizione. Riprova più tardi."
        )
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


async def choose_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    if not TODOIST_API_TOKEN:
        await message.reply_text("Per usare i progetti Todoist, configura TODOIST_API_TOKEN.")
        return

    force_refresh = message.text and message.text.strip().endswith("!")
    projects = await _get_todoist_projects(context.bot_data, force_refresh=force_refresh)
    if not projects:
        await message.reply_text("Non riesco a recuperare i progetti Todoist. Riprova più tardi.")
        return

    keyboard: List[List[InlineKeyboardButton]] = []
    for project in projects:
        name = project.get("name", "Senza nome")
        project_id = str(project.get("id"))
        keyboard.append(
            [InlineKeyboardButton(name, callback_data=f"proj:{project_id}")]
        )

    current_id = context.user_data.get("todoist_project_id")
    current_name = context.user_data.get("todoist_project_name")
    current_text = (
        f"Progetto corrente: {current_name} ({current_id})"
        if current_id and current_name
        else f"Progetto corrente: {current_id}"
        if current_id
        else "Nessun progetto impostato. Verrà usato il default configurato."
    )

    await message.reply_text(
        f"{current_text}\n\nScegli il progetto Todoist:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def project_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    data = query.data or ""
    if not data.startswith("proj:"):
        return

    project_id = data.split("proj:", 1)[1]
    projects = await _get_todoist_projects(context.bot_data)
    selected = next(
        (proj for proj in projects if str(proj.get("id")) == project_id),
        None,
    )

    project_name = selected.get("name") if selected else None
    context.user_data["todoist_project_id"] = project_id
    if project_name:
        context.user_data["todoist_project_name"] = project_name

    text = (
        f"Progetto Todoist aggiornato: {project_name} ({project_id})."
        if project_name
        else f"Progetto Todoist aggiornato: {project_id}."
    )
    await query.edit_message_text(text)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or BOT_TOKEN
    if not token:
        raise RuntimeError(
            "Specifica il token del bot: imposta TELEGRAM_BOT_TOKEN oppure "
            "compila BOT_TOKEN in config.py."
        )

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg non trovato nel PATH di sistema. "
            "Installa ffmpeg e aggiungi la cartella bin (es. C:\\ffmpeg\\bin) al PATH."
        )

    application = Application.builder().token(token).build()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("progetti", choose_project))
    application.add_handler(CallbackQueryHandler(project_selection, pattern=r"^proj:"))
    application.add_handler(
        MessageHandler(
            filters.VOICE | filters.AUDIO | filters.Document.AUDIO,
            handle_audio,
        )
    )

    application.run_polling()


if __name__ == "__main__":
    main()

