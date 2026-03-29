"""Internationalization support for littledl."""

import gettext as _gettext_module
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path

__all__ = ["get_translator", "set_language", "get_available_languages", "gettext", "LANGUAGE_ENV_VAR"]


LANGUAGE_ENV_VAR = "LITTLELDL_LANGUAGE"
DEFAULT_LANGUAGE = "en"

AVAILABLE_LANGUAGES = {
    "en": "English",
    "zh": "中文",
}


class Language(Enum):
    EN = "en"
    ZH = "zh"


_current_language: str = DEFAULT_LANGUAGE
_translator: _gettext_module.GNUTranslations | None = None


def _get_translation_dir() -> Path:
    module_path = Path(__file__).parent.parent
    return module_path / "i18n"


def _load_translations(language: str) -> _gettext_module.GNUTranslations | None:
    try:
        if language == "en":
            return None
        lang_dir = _get_translation_dir()
        return _gettext_module.translation(
            domain="messages",
            localedir=str(lang_dir),
            languages=[language],
        )
    except FileNotFoundError:
        return None


@lru_cache(maxsize=2)
def get_translator(language: str | None = None) -> _gettext_module.GNUTranslations:
    global _current_language, _translator

    if language is None:
        language = os.environ.get(LANGUAGE_ENV_VAR, DEFAULT_LANGUAGE)

    if language != _current_language or _translator is None:
        _current_language = language
        _translator = _load_translations(language)

    return _translator or _gettext_module.NullTranslations()


def set_language(language: str) -> bool:
    if language not in AVAILABLE_LANGUAGES:
        return False
    os.environ[LANGUAGE_ENV_VAR] = language
    get_translator.cache_clear()
    return True


def get_current_language() -> str:
    return os.environ.get(LANGUAGE_ENV_VAR, DEFAULT_LANGUAGE)


def get_available_languages() -> dict[str, str]:
    return AVAILABLE_LANGUAGES.copy()


def gettext(msgid: str) -> str:
    translator = get_translator()
    if translator is None:
        return msgid
    return translator.gettext(msgid)


def ngettext(singular: str, plural: str, n: int) -> str:
    translator = get_translator()
    if translator is None:
        return singular if n == 1 else plural
    return translator.ngettext(singular, plural, n)


def pgettext(context: str, msgid: str) -> str:
    translator = get_translator()
    if translator is None:
        return msgid
    try:
        return translator.pgettext(context, msgid)
    except AttributeError:
        return msgid


def detect_system_language() -> str:
    import locale

    try:
        lang, _ = locale.getlocale()
        if lang and lang.startswith("zh"):
            return "zh"
        elif lang and lang.startswith("en"):
            return "en"
    except Exception:
        pass

    return DEFAULT_LANGUAGE


def init_language() -> None:
    if LANGUAGE_ENV_VAR not in os.environ:
        detected = detect_system_language()
        if detected in AVAILABLE_LANGUAGES:
            os.environ[LANGUAGE_ENV_VAR] = detected
