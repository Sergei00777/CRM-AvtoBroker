"""
Акт осмотра автомобиля — АвтоБрокер
Настольная программа: окно с заполняемым бланком (akt_osmotra.html).

Запуск без сборки:  python app.py
Сборка в .exe:      запустите build.bat
"""
import os
import sys

import webview

APP_TITLE = "Акт осмотра автомобиля — АвтоБрокер"


def resource_path(name: str) -> str:
    """Путь к файлу рядом с программой (работает и внутри собранного .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def acts_folder() -> str:
    """Папка по умолчанию для сохранённых актов: Документы\\Акты осмотра."""
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    folder = os.path.join(docs, "Акты осмотра")
    os.makedirs(folder, exist_ok=True)
    return folder


def data_folder() -> str:
    """Папка для черновика (чтобы не терять данные при закрытии окна)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "AvtoBroker", "AktOsmotra")
    os.makedirs(folder, exist_ok=True)
    return folder


# Совместимость с разными версиями pywebview
_FD = getattr(webview, "FileDialog", None)
SAVE = _FD.SAVE if _FD else webview.SAVE_DIALOG
OPEN = _FD.OPEN if _FD else webview.OPEN_DIALOG
FILE_TYPES = ("Акт осмотра (*.json)", "Все файлы (*.*)")


class Api:
    """Методы, которые вызывает бланк через window.pywebview.api."""

    def __init__(self):
        self.window = None

    def save(self, data: str, suggested_name: str):
        result = self.window.create_file_dialog(
            SAVE,
            directory=acts_folder(),
            save_filename=suggested_name or "Акт осмотра.json",
            file_types=FILE_TYPES,
        )
        if not result:
            return False
        path = result if isinstance(result, str) else result[0]
        if not path.lower().endswith(".json"):
            path += ".json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        return os.path.basename(path)

    def open(self):
        result = self.window.create_file_dialog(
            OPEN,
            directory=acts_folder(),
            allow_multiple=False,
            file_types=FILE_TYPES,
        )
        if not result:
            return None
        path = result if isinstance(result, str) else result[0]
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


def main():
    api = Api()
    window = webview.create_window(
        APP_TITLE,
        url=resource_path("akt_osmotra.html"),
        js_api=api,
        width=1120,
        height=900,
        min_size=(900, 600),
        background_color="#E7E9EC",
    )
    api.window = window
    webview.start(private_mode=False, storage_path=data_folder())


if __name__ == "__main__":
    main()
