import mutagen
import mutagen.id3
import mutagen.mp3
from mutagen.easyid3 import EasyID3


TAGS_TO_PROCESS = ("title", "album")


def get_tags(filepath: str) -> dict[str, str | None]:
    try:
        audio = EasyID3(filepath)
    except mutagen.id3.ID3NoHeaderError:
        audio = mutagen.File(filepath, easy=True)
        if audio is None:
            return {}

    result = {}
    for tag in TAGS_TO_PROCESS:
        values = audio.get(tag)
        result[tag] = values[0] if values else None
    return result


def set_tags(filepath: str, tags: dict[str, str]) -> bool:
    try:
        audio = EasyID3(filepath)
    except mutagen.id3.ID3NoHeaderError:
        audio = mutagen.File(filepath, easy=True)
        if audio is None:
            return False

    changed = False
    for tag, value in tags.items():
        audio[tag] = value
        changed = True

    if changed:
        audio.save()
    return changed
