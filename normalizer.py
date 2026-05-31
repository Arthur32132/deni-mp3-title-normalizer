import json
import re


def load_proper_nouns(filepath: str) -> dict[str, str]:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        result[key] = value
    return result


def save_proper_nouns(filepath: str, proper_nouns: dict[str, str]):
    metadata = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            existing = json.load(f)
        for key, value in existing.items():
            if key.startswith("_"):
                metadata[key] = value
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    output = {**metadata, **proper_nouns}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


WORD_RE = re.compile(r"(\W+)", re.UNICODE)


def _split_keep_delimiters(text: str) -> list[str]:
    parts = WORD_RE.split(text)
    result = []
    for part in parts:
        if part:
            result.append(part)
    return result


def normalize_case(text: str, proper_nouns: dict[str, str] | None = None) -> str:
    if not text or not text.strip():
        return text

    if proper_nouns is None:
        proper_nouns = {}

    normalized = text[0].upper() + text[1:].lower() if len(text) > 1 else text.upper()

    if not proper_nouns:
        return normalized

    for key, value in sorted(proper_nouns.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(r"\W", key, re.UNICODE):
            pattern = re.compile(rf"(?<!\w){re.escape(key)}(?!\w)", re.IGNORECASE | re.UNICODE)
            normalized = pattern.sub(value, normalized)

    tokens = _split_keep_delimiters(normalized)

    for i, token in enumerate(tokens):
        lower = token.lower()
        if lower in proper_nouns:
            tokens[i] = proper_nouns[lower]

    return "".join(tokens)
