"""Runtime settings, read from environment variables and an optional .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    # Gnani speech APIs: Prisma (speech to text) and Timbre (text to speech)
    gnani_api_key: str
    gnani_base_url: str
    prisma_model: str
    prisma_format: str
    prisma_lock_language: bool
    prisma_keyterms_max: int
    timbre_model: str
    timbre_voice_rider: str
    timbre_voice_customer: str
    timbre_sample_rate: int
    # Evon, served behind an OpenAI-compatible endpoint (vLLM, SGLang or llama.cpp)
    evon_base_url: str
    evon_model: str
    evon_api_key: str
    evon_json_mode: bool
    evon_timeout_s: float
    evon_reasoning: bool
    evon_reasoning_tokens: int
    # Mock switches, so the UI can be built before keys and a GPU are ready
    mock_prisma: bool
    mock_timbre: bool
    mock_evon: bool
    # Data files
    data_dir: Path
    places_file: Path
    orders_file: Path
    script_file: Path
    notes_file: Path
    audio_dir: Path
    setup_file: Path
    places_osm_file: Path
    places_custom_file: Path
    # Map search tuning (metres)
    search_radius_m: int
    cluster_radius_m: int
    feature_radius_m: int
    near_pin_m: int
    arrive_radius_m: int

    def modes(self) -> dict[str, str]:
        return {
            "prisma": "mock" if self.mock_prisma else "live",
            "evon": "mock" if self.mock_evon else "live",
            "timbre": "mock" if self.mock_timbre else "live",
        }


def load_settings() -> Settings:
    data_dir = _path("PATA_DATA_DIR", BASE_DIR / "data")
    key = os.getenv("GNANI_API_KEY", "").strip()
    evon_url = os.getenv("EVON_BASE_URL", "").strip().rstrip("/")
    return Settings(
        gnani_api_key=key,
        gnani_base_url=os.getenv("GNANI_BASE_URL", "https://api.vachana.ai").rstrip("/"),
        prisma_model=os.getenv("PRISMA_MODEL", "prisma-v3.0"),
        prisma_format=os.getenv("PRISMA_FORMAT", "transcribe"),
        prisma_lock_language=_flag("PRISMA_LOCK_LANGUAGE", False),
        prisma_keyterms_max=int(os.getenv("PRISMA_KEYTERMS_MAX", "60")),
        timbre_model=os.getenv("TIMBRE_MODEL", "timbre-v3.0"),
        timbre_voice_rider=os.getenv("TIMBRE_VOICE_RIDER", "Yashraj"),
        timbre_voice_customer=os.getenv("TIMBRE_VOICE_CUSTOMER", "Shivani"),
        timbre_sample_rate=int(os.getenv("TIMBRE_SAMPLE_RATE", "44100")),
        evon_base_url=evon_url,
        evon_model=os.getenv("EVON_MODEL", "model"),
        evon_api_key=os.getenv("EVON_API_KEY", "EMPTY"),
        evon_json_mode=_flag("EVON_JSON_MODE", True),
        evon_timeout_s=float(os.getenv("EVON_TIMEOUT_S", "120")),
        evon_reasoning=_flag("EVON_REASONING", True),
        evon_reasoning_tokens=int(os.getenv("EVON_REASONING_TOKENS", "3000")),
        mock_prisma=_flag("MOCK_PRISMA", default=not key),
        mock_timbre=_flag("MOCK_TIMBRE", default=not key),
        mock_evon=_flag("MOCK_EVON", default=not evon_url),
        data_dir=data_dir,
        places_file=_path("PLACES_FILE", data_dir / "places_demo.json"),
        orders_file=_path("ORDERS_FILE", data_dir / "orders_demo.json"),
        script_file=_path("SCRIPT_FILE", data_dir / "demo_script.json"),
        notes_file=_path("NOTES_FILE", data_dir / "doorstep_notes.json"),
        audio_dir=_path("AUDIO_DIR", data_dir / "audio_cache"),
        setup_file=_path("SETUP_FILE", data_dir / "demo_setup.json"),
        places_osm_file=_path("PLACES_OSM_FILE", data_dir / "places_osm.json"),
        places_custom_file=_path("PLACES_CUSTOM_FILE", data_dir / "places_custom.json"),
        search_radius_m=int(os.getenv("SEARCH_RADIUS_M", "1500")),
        cluster_radius_m=int(os.getenv("CLUSTER_RADIUS_M", "120")),
        feature_radius_m=int(os.getenv("FEATURE_RADIUS_M", "150")),
        near_pin_m=int(os.getenv("NEAR_PIN_M", "150")),
        arrive_radius_m=int(os.getenv("ARRIVE_RADIUS_M", "40")),
    )
