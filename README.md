# Deni

**Deni** is a small command-line tool for cleaning MP3 `title` tags in bulk.
It can recursively scan folders, create compact JSON dumps for AI editing,
normalize titles with local dictionaries, or send titles directly to DeepSeek
and apply the corrected tags back to the files.

**Deni** — маленькая консольная утилита для массового исправления MP3-тегов
`title`. Она рекурсивно обходит папки, создаёт компактные JSON-дампы для
нейронок, нормализует названия по локальным словарям или сразу отправляет
названия в DeepSeek и применяет результат обратно к файлам.

## Features / Возможности

- Recursive MP3 scanning across nested folders.
- Compact JSON dump format: each track is just `["path","title"]`.
- Safe preview mode with `--dry`.
- Local dictionary normalization for names, cities and countries.
- DeepSeek integration for automatic title cleanup.
- Windows-friendly paths using `/` in JSON, so AI tools do not break `\`.

- Рекурсивный поиск MP3 во всех подпапках.
- Компактный JSON-формат: каждый трек — это `["path","title"]`.
- Безопасный просмотр изменений через `--dry`.
- Локальные словари для имён, городов и стран.
- Интеграция с DeepSeek для автоматического исправления названий.
- Пути в JSON через `/`, чтобы нейронки не ломали Windows-слеши.

## Installation / Установка

```bash
pip install -r requirements.txt
```

## One-click Windows app / Windows-приложение в один клик

You can run the graphical app without typing commands:

```bash
python deni_gui.py
```

Or build a standalone executable:

```bat
build_exe.bat
```

The generated app will be available at `dist/Deni.exe`.
Put `deepseek_api_key.txt` next to `Deni.exe` if you want the exe to call
DeepSeek without environment variables.

Можно запустить графическое окно без командной работы:

```bash
python deni_gui.py
```

Или собрать самостоятельный `.exe`:

```bat
build_exe.bat
```

Готовая программа появится в `dist/Deni.exe`.
Положи `deepseek_api_key.txt` рядом с `Deni.exe`, чтобы exe мог обращаться к
DeepSeek без переменных окружения.

## DeepSeek key / Ключ DeepSeek

Use one of these options:

1. Pass `--api-key`.
2. Set `DEEPSEEK_API_KEY`.
3. Create `deepseek_api_key.txt` next to `deni.py`.

Используй один из вариантов:

1. Передай `--api-key`.
2. Задай переменную `DEEPSEEK_API_KEY`.
3. Создай `deepseek_api_key.txt` рядом с `deni.py`.

`deepseek_api_key.txt` is ignored by Git. Do not commit real API keys.

`deepseek_api_key.txt` игнорируется Git. Не коммить реальные API-ключи.

## Usage / Использование

Create a compact dump:

```bash
python deni.py dump "C:/Music" -o dump.json
```

Создать компактный дамп:

```bash
python deni.py dump "C:/Music" -o dump.json
```

Apply a corrected dump:

```bash
python deni.py apply dump.json --dry
python deni.py apply dump.json
```

Применить исправленный дамп:

```bash
python deni.py apply dump.json --dry
python deni.py apply dump.json
```

Normalize with local dictionaries:

```bash
python deni.py normalize-dict "C:/Music" --dry
python deni.py normalize-dict "C:/Music"
```

Нормализовать по локальным словарям:

```bash
python deni.py normalize-dict "C:/Music" --dry
python deni.py normalize-dict "C:/Music"
```

Fix titles through DeepSeek and apply them:

```bash
python deni.py deepseek-fix "C:/Music" --dry --output fixed_dump.json
python deni.py deepseek-fix "C:/Music" --output fixed_dump.json
```

Исправить названия через DeepSeek и применить:

```bash
python deni.py deepseek-fix "C:/Music" --dry --output fixed_dump.json
python deni.py deepseek-fix "C:/Music" --output fixed_dump.json
```

## JSON dump format / Формат JSON

```json
{"format":"deni-title-compact-v1","root":"C:/Music","files":[["Album/01.mp3","Song title"]]}
```

When editing with an AI model, change only the second item in each pair:

```json
["path/to/file.mp3","title to edit"]
```

При правке через нейронку меняй только второй элемент пары:

```json
["path/to/file.mp3","название для правки"]
```

## Dictionaries / Словари

- `names_dictionary.json` stores names and artists.
- `places_dictionary.json` stores cities, countries and places.

- `names_dictionary.json` хранит имена и артистов.
- `places_dictionary.json` хранит города, страны и места.

Dictionary format:

```json
{
  "егор": "Егор",
  "омск": "Омск"
}
```

## Safety / Безопасность

Always run with `--dry` first when processing a large collection.

Всегда сначала запускай с `--dry`, особенно на большой музыкальной коллекции.
