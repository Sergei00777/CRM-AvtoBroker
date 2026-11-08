"""База данных CRM (SQLite, без внешних зависимостей)."""
import os
import sqlite3

from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get("CRM_DB", os.path.join(DATA_DIR, "crm.db"))
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

# ---------------------------------------------------------------- справочники
DEAL_KINDS = {
    "china": ("Заказ авто из Китая", "🇨🇳"),
    "japan": ("Заказ авто из Японии", "🇯🇵"),
    "korea": ("Заказ авто из Кореи", "🇰🇷"),
    "selection": ("Подбор автомобиля", "🔍"),
    "sale": ("Продажа автомобиля", "💰"),
    "purchase": ("Покупка авто (выкуп)", "🤝"),
    "commission": ("Комиссия авто", "📋"),
    "rent": ("Прокат", "🔑"),
}

DEAL_STAGES = [
    ("new", "Новая заявка"),
    ("consult", "Консультация"),
    ("calc", "Подбор / расчёт"),
    ("contract", "Договор / предоплата"),
    ("work", "В работе / в пути"),
    ("deal", "Выдача / сделка"),
    ("won", "Успешно"),
    ("lost", "Отказ"),
]

CLIENT_TEMPS = ["Холодный", "Тёплый", "Горячий", "Клиент", "Архив"]
CLIENT_SOURCES = ["Авито", "Drom", "Сайт", "Telegram", "WhatsApp", "Instagram", "VK",
                  "Рекомендация", "Повторный клиент", "Звонок", "Другое"]

CAR_ORIGINS = ["Склад", "Китай", "Япония", "Корея", "Выкуп", "Комиссия", "Прокат"]
CAR_STATUSES = ["В наличии", "В пути", "Резерв", "Продан", "В прокате", "На ремонте"]
TRANSMISSIONS = ["АКПП", "МКПП", "Робот", "Вариатор", "Электро"]
DRIVES = ["Передний", "Задний", "Полный"]
FUELS = ["Бензин", "Дизель", "Гибрид", "Электро", "Газ"]

RENT_STATUSES = ["Бронь", "Активна", "Завершена", "Отменена"]
TASK_STATUSES = ["Новая", "В работе", "Выполнена"]
TASK_PRIORITIES = {"low": "Низкий", "normal": "Обычный", "high": "Высокий"}
EVENT_KINDS = ["Встреча", "Осмотр авто", "Выдача авто", "Звонок", "Приём авто", "Другое"]

DOC_KINDS = {
    "dogovor": ("Договор-заявка на оказание услуг", "dogovor.html"),
    "akt_osmotra": ("Акт осмотра автомобиля", "akt_osmotra.html"),
    "akt_peredachi": ("Акт приёма-передачи автомобиля", None),
    "dogovor_prokata": ("Договор проката автомобиля", None),
}

ROLES = {"admin": "Администратор", "manager": "Менеджер", "viewer": "Наблюдатель"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'manager',
    phone TEXT, email TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone TEXT, phone2 TEXT, email TEXT, messenger TEXT, city TEXT,
    passport TEXT, birth_date TEXT, license TEXT,
    source TEXT, temp TEXT DEFAULT 'Холодный',
    next_call TEXT, notes TEXT,
    manager_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL, model TEXT, year INTEGER,
    vin TEXT, plate TEXT, color TEXT, mileage INTEGER,
    engine TEXT, fuel TEXT, transmission TEXT, drive TEXT, body TEXT,
    origin TEXT DEFAULT 'Склад', status TEXT DEFAULT 'В наличии',
    purchase_price INTEGER DEFAULT 0, costs INTEGER DEFAULT 0,
    sale_price INTEGER DEFAULT 0, rent_day_price INTEGER DEFAULT 0,
    owner_client_id INTEGER REFERENCES clients(id),
    arrival_date TEXT, photo TEXT, notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'new',
    title TEXT, car_wish TEXT,
    budget INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, fee INTEGER DEFAULT 0,
    prepaid INTEGER DEFAULT 0,
    car_id INTEGER REFERENCES cars(id),
    manager_id INTEGER REFERENCES users(id),
    deadline TEXT, notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    closed_at TEXT
);
CREATE TABLE IF NOT EXISTS rentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    car_id INTEGER NOT NULL REFERENCES cars(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    start_date TEXT NOT NULL, end_date TEXT NOT NULL,
    price_day INTEGER DEFAULT 0, total INTEGER DEFAULT 0,
    deposit INTEGER DEFAULT 0, paid INTEGER DEFAULT 0,
    mileage_out INTEGER, mileage_in INTEGER,
    status TEXT DEFAULT 'Бронь', notes TEXT,
    manager_id INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, description TEXT,
    due_date TEXT, due_time TEXT,
    priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'Новая',
    assignee_id INTEGER REFERENCES users(id),
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    deal_id INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL, kind TEXT DEFAULT 'Встреча',
    date TEXT NOT NULL, time TEXT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id),
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, number TEXT, title TEXT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    car_id INTEGER REFERENCES cars(id) ON DELETE SET NULL,
    deal_id INTEGER REFERENCES deals(id) ON DELETE SET NULL,
    rental_id INTEGER REFERENCES rentals(id) ON DELETE SET NULL,
    data TEXT,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    kind TEXT DEFAULT 'note', text TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, is_group INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER REFERENCES users(id),
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS chat_members (
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    last_read INTEGER NOT NULL DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    text TEXT, file TEXT, file_name TEXT,
    system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_msg_chat ON messages(chat_id, id);

CREATE INDEX IF NOT EXISTS ix_deals_client ON deals(client_id);
CREATE INDEX IF NOT EXISTS ix_tasks_due ON tasks(due_date);
CREATE INDEX IF NOT EXISTS ix_rent_dates ON rentals(start_date, end_date);
CREATE INDEX IF NOT EXISTS ix_activity_client ON activity(client_id);
"""

DEFAULT_SETTINGS = {
    "company_name": "АвтоБрокер",
    "company_city": "Иркутск",
    "company_legal": "ИП Пуховский Илья Дмитриевич",
    "company_phone": "",
    "company_site": "автоброкер38.рф",
    "company_requisites": "",
}


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.join(UPLOAD_DIR, "chat"), exist_ok=True)
    con = connect()
    con.executescript(SCHEMA)
    # миграции для баз, созданных прошлыми версиями
    cols = {r[1] for r in con.execute("PRAGMA table_info(users)")}
    if "photo" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN photo TEXT")
    for k, v in DEFAULT_SETTINGS.items():
        con.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
    con.commit()
    con.close()


# ---------------------------------------------------------------- helpers
def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def scalar(sql, args=()):
    row = get_db().execute(sql, args).fetchone()
    return row[0] if row and row[0] is not None else 0


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def insert(table, data: dict):
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))


def update(table, row_id, data: dict):
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*data.values(), row_id))


def get_settings():
    return {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}


def set_setting(key, value):
    execute("INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
