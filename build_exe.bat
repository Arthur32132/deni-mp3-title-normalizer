@echo off
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name Deni --add-data "names_dictionary.json;." --add-data "places_dictionary.json;." --add-data "proper_nouns.json;." deni_gui.py
echo.
echo Done: dist\Deni.exe
pause
