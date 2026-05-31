import argparse
import collections
import concurrent.futures
import json
import os
import sys
import urllib.error
import urllib.request

from normalizer import load_proper_nouns, normalize_case, save_proper_nouns
from mp3_handler import get_tags, set_tags, TAGS_TO_PROCESS

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
USER_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(__file__)
PROPER_NOUNS_PATH = os.path.join(RESOURCE_DIR, "proper_nouns.json")
NAMES_DICTIONARY_PATH = os.path.join(RESOURCE_DIR, "names_dictionary.json")
PLACES_DICTIONARY_PATH = os.path.join(RESOURCE_DIR, "places_dictionary.json")
DEEPSEEK_KEY_PATH = os.path.join(USER_DIR, "deepseek_api_key.txt")
APP_ICON_PNG_PATH = os.path.join(RESOURCE_DIR, "rap.png")
TAG_DUMP_FORMAT = "deni-tag-dump-v1"
TITLE_DUMP_FORMAT = "deni-title-dump-v1"
COMPACT_TITLE_DUMP_FORMAT = "deni-title-compact-v1"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"


def collect_mp3_paths(inputs: list[str]) -> list[str]:
    paths = []
    for p in inputs:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            if p.lower().endswith(".mp3"):
                paths.append(p)
        elif os.path.isdir(p):
            for dirpath, _, filenames in os.walk(p):
                for filename in filenames:
                    if filename.lower().endswith(".mp3"):
                        paths.append(os.path.join(dirpath, filename))
        else:
            print(f"[WARN] Пропущено (не существует): {p}", file=sys.stderr)
    return sorted(paths, key=str.lower)


def to_dump_path(filepath: str, root: str) -> str:
    return os.path.relpath(filepath, root).replace("\\", "/")


def to_json_path(path: str) -> str:
    return path.replace("\\", "/")


def collect_words_from_path(root: str, limit: int | None = None) -> collections.Counter:
    counter = collections.Counter()
    count = 0

    for filepath in collect_mp3_paths([root]):
        tags = get_tags(filepath)
        for tag in TAGS_TO_PROCESS:
            text = tags.get(tag)
            if not text:
                continue
            for word in text.split():
                clean = word.strip("""!"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~""")
                if clean:
                    counter[clean] += 1
        count += 1
        if limit and count >= limit:
            return counter
    return counter


def build_compact_title_dump(path: str, limit: int | None = None) -> dict:
    return build_compact_title_dump_for_paths([path], limit)


def build_compact_title_dump_for_paths(paths: list[str], limit: int | None = None) -> dict:
    dictionaries = load_title_dictionaries()
    roots = [os.path.abspath(path) for path in paths]
    common_root = os.path.commonpath(roots) if roots else os.getcwd()
    paths = collect_mp3_paths(roots)
    if limit:
        paths = paths[:limit]

    files = []
    for filepath in paths:
        tags = get_tags(filepath)
        title = tags.get("title") or ""
        files.append([
            to_dump_path(filepath, common_root),
            normalize_case(title, dictionaries),
        ])

    return {
        "format": COMPACT_TITLE_DUMP_FORMAT,
        "root": to_json_path(common_root),
        "files": files,
    }


def load_title_dictionaries() -> dict[str, str]:
    dictionaries = {}
    dictionaries.update(load_proper_nouns(PLACES_DICTIONARY_PATH))
    dictionaries.update(load_proper_nouns(NAMES_DICTIONARY_PATH))
    return dictionaries


def cmd_normalize(args):
    proper_nouns = load_proper_nouns(PROPER_NOUNS_PATH)
    paths = collect_mp3_paths(args.path)
    changed = 0
    skipped = 0

    for filepath in paths:
        tags = get_tags(filepath)
        new_tags = {}

        for tag in TAGS_TO_PROCESS:
            original = tags.get(tag)
            if not original:
                continue
            normalized = normalize_case(original, proper_nouns)
            if normalized != original:
                new_tags[tag] = normalized
                print(f"[DRY]" if args.dry else f"[UPD]", filepath)
                print(f"  {tag}: «{original}» -> «{normalized}»")

        if new_tags and not args.dry:
            set_tags(filepath, new_tags)
            changed += 1
        elif new_tags:
            changed += 1
        else:
            skipped += 1

    print(f"\nГотово: изменено {changed}, пропущено {skipped}")


def cmd_normalize_dict(args):
    dictionaries = load_title_dictionaries()
    paths = collect_mp3_paths(args.path)
    tags_to_process = ["title"]
    if args.album:
        tags_to_process.append("album")
    changed = 0
    skipped = 0

    for filepath in paths:
        tags = get_tags(filepath)
        new_tags = {}

        for tag in tags_to_process:
            original = tags.get(tag)
            if not original:
                continue
            normalized = normalize_case(original, dictionaries)
            if normalized != original:
                new_tags[tag] = normalized
                print(f"[DRY]" if args.dry else f"[UPD]", filepath)
                print(f"  {tag}: «{original}» -> «{normalized}»")

        if new_tags and not args.dry:
            set_tags(filepath, new_tags)
            changed += 1
        elif new_tags:
            changed += 1
        else:
            skipped += 1

    print(f"\nГотово: изменено {changed}, пропущено {skipped}")


def cmd_dump(args):
    output = build_compact_title_dump(args.path, args.limit)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Дамп сохранён: {args.output} ({len(output['files'])} MP3-файлов)")


def cmd_deepseek_fix(args):
    dump_data = build_compact_title_dump(args.path, args.limit)
    if not dump_data["files"]:
        print("MP3-файлы не найдены")
        return

    fixed_dump = deepseek_fix_dump_batched(dump_data, args, print)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(fixed_dump, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Исправленный дамп сохранён: {args.output}")

    apply_compact_title_dump(args, fixed_dump)


def deepseek_fix_dump_batched(dump_data: dict, args, progress=None) -> dict:
    files = dump_data.get("files", [])
    batch_size = max(1, int(getattr(args, "batch_size", 100) or 100))
    workers = max(1, int(getattr(args, "workers", 3) or 3))
    batches = []

    for start in range(0, len(files), batch_size):
        batches.append({
            "format": dump_data.get("format"),
            "root": dump_data.get("root"),
            "files": files[start:start + batch_size],
        })

    if progress:
        progress(f"DeepSeek batches: {len(batches)} x up to {batch_size} tracks, workers: {workers}")

    fixed_batches = [None] * len(batches)

    def run_batch(index: int, batch: dict):
        if progress:
            progress(f"Batch {index + 1}/{len(batches)} started ({len(batch['files'])} tracks)")
        fixed = deepseek_fix_dump(batch, args)
        validate_fixed_dump(batch, fixed)
        if progress:
            progress(f"Batch {index + 1}/{len(batches)} done")
        return index, fixed

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(batches))) as executor:
        futures = [executor.submit(run_batch, index, batch) for index, batch in enumerate(batches)]
        for future in concurrent.futures.as_completed(futures):
            index, fixed = future.result()
            fixed_batches[index] = fixed

    fixed_files = []
    for fixed in fixed_batches:
        fixed_files.extend(fixed["files"])

    fixed_dump = {
        "format": dump_data.get("format"),
        "root": dump_data.get("root"),
        "files": fixed_files,
    }
    validate_fixed_dump(dump_data, fixed_dump)
    return fixed_dump


def deepseek_fix_dump(dump_data: dict, args) -> dict:
    api_key = load_deepseek_api_key(args.api_key)
    if not api_key:
        raise SystemExit(
            "Нет API-ключа. Укажи --api-key, переменную DEEPSEEK_API_KEY "
            "или файл deepseek_api_key.txt рядом с deni.py."
        )

    dump_text = json.dumps(dump_data, ensure_ascii=False, separators=(",", ":"))
    prompt = (
        "Ты исправляешь JSON с MP3-тегами. В files каждый элемент имеет формат "
        "[\"path\",\"title\"]. Title в этом JSON уже предварительно приведён "
        "к нужному регистру. Исправь только очевидные опечатки, лишние пробелы "
        "и настоящие имена собственные. Для всех языков используй обычный sentence case: "
        "первая буква названия большая, остальные слова маленькими, кроме имён, "
        "географических названий, аббревиатур и устойчивых собственных названий. "
        "Не сохраняй английский title case только потому, что это английское название. "
        "Например, оставляй Smells like teen spirit, Come as you are, Drain you, "
        "Stay away; не возвращай Smells Like Teen Spirit, Come As You Are, Drain You. "
        "Не меняй path, root, format, "
        "порядок и количество элементов. "
        "Верни только валидный json в том же формате.\n\n"
        f"{dump_text}"
    )
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return valid json only. Preserve all file paths exactly. "
                    "Only edit song title strings."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "stream": False,
    }
    request = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"DeepSeek вернул HTTP {e.code}: {details}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Не удалось подключиться к DeepSeek: {e}") from e

    content = response_data["choices"][0]["message"]["content"]
    return json.loads(content)


def load_deepseek_api_key(cli_key: str | None) -> str | None:
    if cli_key:
        return cli_key.strip()
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key.strip()
    try:
        with open(DEEPSEEK_KEY_PATH, "r", encoding="utf-8") as f:
            key = f.read().strip()
    except FileNotFoundError:
        return None
    return key or None


def validate_fixed_dump(original: dict, fixed: dict):
    if fixed.get("format") != original.get("format"):
        raise SystemExit("DeepSeek изменил поле format. Применение остановлено.")
    if fixed.get("root") != original.get("root"):
        raise SystemExit("DeepSeek изменил поле root. Применение остановлено.")

    original_files = original.get("files", [])
    fixed_files = fixed.get("files", [])
    if len(original_files) != len(fixed_files):
        raise SystemExit("DeepSeek изменил количество файлов. Применение остановлено.")

    for index, (original_item, fixed_item) in enumerate(zip(original_files, fixed_files), start=1):
        if not isinstance(fixed_item, list) or len(fixed_item) < 2:
            raise SystemExit(f"DeepSeek испортил элемент files[{index}]. Применение остановлено.")
        if fixed_item[0] != original_item[0]:
            raise SystemExit(f"DeepSeek изменил path в files[{index}]. Применение остановлено.")


def cmd_dump_words(args):
    counter = collect_words_from_path(args.path, args.limit)
    words_dict = {}
    for word, count in counter.most_common():
        words_dict[word] = {"keep": False, "count": count}
    output = {"words": words_dict}
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Словарный дамп сохранён: {args.output} ({len(words_dict)} уникальных слов)")


def cmd_apply(args):
    with open(args.dump, "r", encoding="utf-8") as f:
        dump_data = json.load(f)

    if dump_data.get("format") == TAG_DUMP_FORMAT:
        apply_tag_dump(args, dump_data)
        return

    if dump_data.get("format") == TITLE_DUMP_FORMAT:
        apply_title_dump(args, dump_data)
        return

    if dump_data.get("format") == COMPACT_TITLE_DUMP_FORMAT:
        apply_compact_title_dump(args, dump_data)
        return

    apply_words_dump(dump_data)


def apply_compact_title_dump(args, dump_data):
    root = os.path.abspath(args.root or dump_data.get("root") or ".")
    changed = 0
    skipped = 0

    for item in dump_data.get("files", []):
        if not isinstance(item, list) or len(item) < 2:
            skipped += 1
            continue

        relpath = item[0]
        new_title = item[1]
        filepath = os.path.abspath(os.path.join(root, relpath))
        if not os.path.isfile(filepath):
            print(f"[WARN] Пропущено (файл не найден): {filepath}", file=sys.stderr)
            skipped += 1
            continue

        current_title = get_tags(filepath).get("title") or ""
        if str(new_title) == current_title:
            skipped += 1
            continue

        print(f"[DRY]" if args.dry else f"[UPD]", filepath)
        print(f"  title: «{current_title}» -> «{new_title}»")

        if not args.dry:
            set_tags(filepath, {"title": str(new_title)})
        changed += 1

    print(f"\nГотово: изменено {changed}, пропущено {skipped}")


def apply_title_dump(args, dump_data):
    root = os.path.abspath(args.root or dump_data.get("root") or ".")
    changed = 0
    skipped = 0

    for item in dump_data.get("files", []):
        relpath = item.get("path")
        if not relpath:
            skipped += 1
            continue

        filepath = os.path.abspath(os.path.join(root, relpath))
        if not os.path.isfile(filepath):
            print(f"[WARN] Пропущено (файл не найден): {filepath}", file=sys.stderr)
            skipped += 1
            continue

        new_title = item.get("title")
        if new_title is None:
            skipped += 1
            continue

        current_title = get_tags(filepath).get("title") or ""
        if str(new_title) == current_title:
            skipped += 1
            continue

        print(f"[DRY]" if args.dry else f"[UPD]", filepath)
        print(f"  title: «{current_title}» -> «{new_title}»")

        if not args.dry:
            set_tags(filepath, {"title": str(new_title)})
        changed += 1

    print(f"\nГотово: изменено {changed}, пропущено {skipped}")


def apply_tag_dump(args, dump_data):
    root = os.path.abspath(args.root or dump_data.get("root") or ".")
    changed = 0
    skipped = 0

    for item in dump_data.get("files", []):
        relpath = item.get("path")
        if not relpath:
            skipped += 1
            continue

        filepath = os.path.abspath(os.path.join(root, relpath))
        if not os.path.isfile(filepath):
            print(f"[WARN] Пропущено (файл не найден): {filepath}", file=sys.stderr)
            skipped += 1
            continue

        new_tags = {}
        for tag, info in item.get("tags", {}).items():
            if tag not in TAGS_TO_PROCESS or not isinstance(info, dict):
                continue
            value = info.get("value")
            original = info.get("original")
            if value is None or value == original:
                continue
            new_tags[tag] = str(value)

        if not new_tags:
            skipped += 1
            continue

        print(f"[DRY]" if args.dry else f"[UPD]", filepath)
        for tag, value in new_tags.items():
            original = item["tags"][tag].get("original")
            print(f"  {tag}: «{original}» -> «{value}»")

        if not args.dry:
            set_tags(filepath, new_tags)
        changed += 1

    print(f"\nГотово: изменено {changed}, пропущено {skipped}")


def apply_words_dump(dump_data):
    words = dump_data.get("words", {})
    proper_nouns = load_proper_nouns(PROPER_NOUNS_PATH)
    added = 0

    for word, info in words.items():
        key = word.lower()
        if info.get("keep") and key not in proper_nouns:
            proper_nouns[key] = key[0].upper() + key[1:]
            added += 1

    save_proper_nouns(PROPER_NOUNS_PATH, proper_nouns)
    print(f"Добавлено {added} новых имён собственных в proper_nouns.json")


def cmd_add(args):
    word_lower = args.word.lower()
    proper_nouns = load_proper_nouns(PROPER_NOUNS_PATH)
    proper_nouns[word_lower] = args.correct
    save_proper_nouns(PROPER_NOUNS_PATH, proper_nouns)
    print(f"Добавлено: «{word_lower}» -> «{args.correct}»")


def main():
    parser = argparse.ArgumentParser(
        prog="deni",
        description="Нормализация регистра ID3-тегов MP3-файлов",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_norm = sub.add_parser("normalize", help="Обработать MP3-файлы")
    p_norm.add_argument("path", nargs="+", help="Путь к MP3-файлу или папке")
    p_norm.add_argument("--dry", action="store_true", help="Только просмотр, без записи")
    p_norm.set_defaults(func=cmd_normalize)

    p_norm_dict = sub.add_parser("normalize-dict", help="Нормализовать title по словарям")
    p_norm_dict.add_argument("path", nargs="+", help="Путь к MP3-файлу или папке")
    p_norm_dict.add_argument("--dry", action="store_true", help="Только просмотр, без записи")
    p_norm_dict.add_argument("--album", action="store_true", help="Также обработать album")
    p_norm_dict.set_defaults(func=cmd_normalize_dict)

    p_dump = sub.add_parser("dump", help="Выгрузить теги MP3 для правки")
    p_dump.add_argument("path", help="Путь к папке с MP3")
    p_dump.add_argument("--limit", type=int, default=None, help="Макс. число файлов")
    p_dump.add_argument("-o", "--output", default="dump.json", help="Имя выходного файла")
    p_dump.set_defaults(func=cmd_dump)

    p_deepseek = sub.add_parser("deepseek-fix", help="Исправить title через DeepSeek и сразу применить")
    p_deepseek.add_argument("path", help="Путь к папке с MP3")
    p_deepseek.add_argument("--limit", type=int, default=None, help="Макс. число файлов")
    p_deepseek.add_argument("--dry", action="store_true", help="Показать изменения, но не записывать MP3")
    p_deepseek.add_argument("--output", help="Сохранить исправленный JSON-дамп")
    p_deepseek.add_argument("--root", help=argparse.SUPPRESS)
    p_deepseek.add_argument("--api-key", help="DeepSeek API key, если не задан DEEPSEEK_API_KEY")
    p_deepseek.add_argument("--model", default="deepseek-v4-flash", help="Модель DeepSeek")
    p_deepseek.add_argument("--max-tokens", type=int, default=30000, help="Лимит токенов ответа")
    p_deepseek.add_argument("--temperature", type=float, default=0.1, help="Температура модели")
    p_deepseek.add_argument("--timeout", type=int, default=120, help="Таймаут запроса в секундах")
    p_deepseek.add_argument("--batch-size", type=int, default=100, help="Треков в одном запросе DeepSeek")
    p_deepseek.add_argument("--workers", type=int, default=3, help="Параллельных запросов DeepSeek")
    p_deepseek.set_defaults(func=cmd_deepseek_fix)

    p_dump_words = sub.add_parser("dump-words", help="Выгрузить слова из MP3 для разметки")
    p_dump_words.add_argument("path", help="Путь к папке с MP3")
    p_dump_words.add_argument("--limit", type=int, default=50, help="Макс. число файлов")
    p_dump_words.add_argument("-o", "--output", default="words_dump.json", help="Имя выходного файла")
    p_dump_words.set_defaults(func=cmd_dump_words)

    p_apply = sub.add_parser("apply", help="Применить JSON-дамп")
    p_apply.add_argument("dump", help="Путь к JSON-дампу")
    p_apply.add_argument("--dry", action="store_true", help="Только просмотр, без записи")
    p_apply.add_argument("--root", help="Папка с MP3, если нужно заменить root из дампа")
    p_apply.set_defaults(func=cmd_apply)

    p_add = sub.add_parser("add", help="Добавить слово в proper_nouns.json вручную")
    p_add.add_argument("word", help="Слово в нижнем регистре")
    p_add.add_argument("correct", help="Правильное написание")
    p_add.set_defaults(func=cmd_add)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
