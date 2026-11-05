"""Centralized configuration and environment settings for the agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _parse_reference_date(date_str: str | None) -> date:
    """Parse reference date from YYYY-MM-DD string, defaulting to 2026-03-23."""
    if not date_str:
        return date(2026, 3, 23)
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return date(2026, 3, 23)


@dataclass
class AgentConfig:
    """Configuration container for Empório da Música AI Agent."""

    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    session_db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "sessions.db")

    # LLM Provider settings ("auto", "groq", "ollama", "openai", "gemini", "offline")
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "auto").strip().lower()
    )

    # Groq settings (Primary recommended free cloud API)
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    )
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Ollama settings (Primary local free provider)
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2").strip()
    )

    # OpenAI settings
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip())
    openai_model: str = field(
        default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
    )

    # Gemini OpenAI-compatible settings
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip())
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    )
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Reference date for deterministic order & return window evaluation
    reference_date: date = field(
        default_factory=lambda: _parse_reference_date(os.getenv("REFERENCE_DATE"))
    )

    # Store constants (normalized from manual)
    store_name: str = "Empório da Música"
    store_slogan: str = "Sua música começa aqui."
    store_address: str = "Rua 14 de Maio, 3200 — Centro, Campo Grande - MS, CEP 79202-333"
    store_phone_landline: str = "(67) 3341-4444"
    store_whatsapp: str = "(67) 3321-4500"
    store_email: str = "contato@emporiodamusica.com.br"
    store_cnpj: str = "12.345.678/0001-90"

    def has_valid_key(self, key: str) -> bool:
        """Check whether an API key string is populated and not a placeholder."""
        if not key:
            return False
        placeholders = {"your_groq_api_key_here", "your_openai_api_key_here", "your_gemini_api_key_here"}
        return key not in placeholders and len(key) > 10
