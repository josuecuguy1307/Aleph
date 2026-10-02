"""Shared language directives for prompt-driven LLM calls.

This helper centralizes the "stay in the requested language" instruction so
different modules can share the same behavior without depending on book-only
utilities.
"""

from __future__ import annotations

_LANGUAGE_LABELS: dict[str, str] = {
    "zh": "中文（简体）",
    "zh-cn": "中文（简体）",
    "zh-tw": "繁體中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "ru": "Русский",
    "pt": "Português",
    "it": "Italiano",
}


def normalize_language(language: str | None) -> str:
    return (language or "en").strip().lower() or "en"


def language_label(language: str | None) -> str:
    code = normalize_language(language)
    if code in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[code]
    base = code.split("-", 1)[0]
    return _LANGUAGE_LABELS.get(base, language or "English")


def language_directive(language: str | None) -> str:
    """Return a strict reader-facing language instruction for prompts."""
    code = normalize_language(language)
    label = language_label(code)
    if code.startswith("zh"):
        return (
            "\n\n[语言要求 / Language] "
            f"请严格使用{label}撰写所有面向读者的文本（标题、正文、解释、提示、过渡句、"
            "题干、选项等），即使参考资料、JSON 字段名或英文术语出现在 prompt 中也"
            "不得切换语言；保留必要的专有名词原文（如人名、产品名、公式中的变量符号"
            f"等）即可，其余一律使用{label}。采用用户的语气和语言风格：尊重其正式程度、技术深度和简洁程度。"
        )
    if code == "en":
        return (
            "\n\n[Language] Write ALL reader-facing text (titles, prose, "
            "explanations, hints, transitions, quiz stems, options, etc.) in "
            "English. Do NOT switch languages even if the source material, "
            "JSON keys, or examples in this prompt are in another language. "
            "Keep proper nouns (people, products, formula symbols) in their "
            "original form. Match the user's tone and register: preserve their "
            "level of formality, technical depth, and brevity."
        )
    return (
        f"\n\n[Language] Write ALL reader-facing text strictly in {label}. "
        "Do NOT switch languages even if the source material, JSON keys, or "
        "examples in this prompt are in a different language. Keep proper "
        "nouns (people, products, formula symbols) in their original form. "
        "Match the user's tone and register: preserve their level of formality, "
        "technical depth, and brevity."
    )


def append_language_directive(system_prompt: str | None, language: str | None) -> str:
    """Append the language directive to an existing system prompt."""
    base = (system_prompt or "").rstrip()
    directive = language_directive(language).strip()
    if not base:
        return directive
    return f"{base}\n\n{directive}"


def append_conversation_language_directive(
    system_prompt: str | None, language: str | None,
) -> str:
    """Chat follows the latest user message; UI language is only a fallback.

    Content-generation workflows keep the strict directive above. A chat must
    not force its interface language onto a user who switches languages.
    """
    base = (system_prompt or "").rstrip()
    directive = (
        "[Conversation language, tone and register] Write ALL reader-facing text "
        "in the language of the user's latest message, unless they explicitly "
        "request another output language. The interface language and the language "
        "of sources, examples, tools or earlier messages do not override that choice. "
        f"If the latest message gives no language signal, use {language_label(language)}. "
        "Match the user's tone, technical depth and brevity. In Spanish, use neutral "
        "Spanish without regional voseo; preserve formal usted when the user uses "
        "or requests it, and tú for informal conversation. Keep proper nouns, "
        "tool identifiers, API paths and formula symbols in their original form."
    )
    return f"{base}\n\n{directive}" if base else directive


__all__ = [
    "append_conversation_language_directive",
    "append_language_directive",
    "language_directive",
    "language_label",
    "normalize_language",
]
