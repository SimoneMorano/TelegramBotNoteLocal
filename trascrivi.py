import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

import ffmpeg
from faster_whisper import WhisperModel
from huggingface_hub import snapshot_download

try:
    from config import (
        WHISPER_COMPUTE_TYPE,
        WHISPER_DEVICE,
        WHISPER_MODEL_LOCAL_DIR,
        WHISPER_MODEL_REPO,
    )
except ImportError:
    WHISPER_MODEL_REPO = "Systran/faster-whisper-small"
    WHISPER_MODEL_LOCAL_DIR = "models/faster-whisper-small"
    WHISPER_COMPUTE_TYPE = "int8"
    WHISPER_DEVICE = "cpu"


MODEL_PRESETS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def convert_to_wav(input_path: str) -> str:
    """
    Converte l'audio fornito in WAV mono 16kHz, restituendo il percorso del nuovo file.
    Il file WAV viene salvato accanto all'originale.
    """
    output_path = os.path.splitext(input_path)[0] + ".wav"
    (
        ffmpeg.input(input_path)
        .output(output_path, ac=1, ar="16000", acodec="pcm_s16le", loglevel="error")
        .overwrite_output()
        .run()
    )
    return output_path


def _ensure_local_model(repo_id: str, local_dir: Path) -> Path:
    """
    Scarica (se necessario) il modello Whisper dal repo indicato all'interno di local_dir.
    """
    local_dir = local_dir.resolve()
    marker = local_dir / "model.bin"
    if marker.exists():
        return local_dir

    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"Scarico il modello Whisper '{repo_id}' in {local_dir} ...")
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        allow_patterns=["*.bin", "*.json", "*.txt", "*.model"],
    )
    return local_dir


def _resolve_model_source(modello: Optional[str]) -> Union[str, Path]:
    """
    Determina il percorso (locale) o l'identificativo del modello da utilizzare.
    """
    if modello and Path(modello).exists():
        return Path(modello)

    repo_id = WHISPER_MODEL_REPO
    if modello:
        repo_id = MODEL_PRESETS.get(modello, modello)

    if "/" not in repo_id:
        # Se il valore non è un repo valido, ricadiamo sulla configurazione di default.
        repo_id = WHISPER_MODEL_REPO

    if modello and repo_id != WHISPER_MODEL_REPO:
        local_dir = Path("models") / repo_id.split("/")[-1]
    else:
        local_dir = Path(WHISPER_MODEL_LOCAL_DIR)

    return _ensure_local_model(repo_id, local_dir)


@lru_cache(maxsize=2)
def _load_model(modello: Optional[str] = None) -> WhisperModel:
    """
    Carica e memorizza nella cache un modello Whisper per evitare ricaricamenti ripetuti.
    Il modello viene scaricato localmente alla prima esecuzione.
    """
    source = _resolve_model_source(modello)
    return WhisperModel(
        str(source),
        device=WHISPER_DEVICE,
        compute_type=WHISPER_COMPUTE_TYPE,
    )


def trascrivi(
    audio_file: str,
    modello: Optional[str] = None,
    verbose: bool = True,
    cleanup: bool = True,
) -> str:
    """
    Trascrive un file audio utilizzando faster-whisper.

    Args:
        audio_file: percorso del file da trascrivere (ogg/opus/mp3/etc.).
        modello: nome o percorso del modello Whisper da usare. Se None usa quello configurato.
        verbose: se True stampa informazioni di avanzamento.
        cleanup: se True rimuove il WAV temporaneo generato.
    """
    if verbose:
        print(f"Converto {audio_file} in WAV...")
    wav = convert_to_wav(audio_file)
    if verbose:
        print("Carico modello locale...")
    model = _load_model(modello)
    if verbose:
        print("Trascrivo...")
    segments, _info = model.transcribe(wav, language="it", vad_filter=True)
    testo = "".join(seg.text for seg in segments)
    if cleanup:
        try:
            os.remove(wav)
        except FileNotFoundError:
            pass
    if verbose:
        print("\n--- TESTO TRASCRITTO ---\n")
        print(testo)
        print("\n-------------------------\n")
    return testo


if __name__ == "__main__":
    file_audio = input("Trascina qui il file audio Telegram (.ogg/.opus): ").strip('"')
    trascrivi(file_audio)

