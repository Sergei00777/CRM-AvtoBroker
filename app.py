"""
CRM АвтоБрокер — система учёта для автоброкера.

Запуск:  python app.py      → откройте http://127.0.0.1:5000
При первом запуске программа попросит создать администратора.
"""
import csv
import io
import json
import os
import re
import secrets
import sys
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

import db
from db import (CAR_ORIGINS, CAR_STATUSES, CLIENT_SOURCES, CLIENT_TEMPS, DEAL_KINDS, DEAL_STAGES,
                DOC_KINDS, DRIVES, EVENT_KINDS, FUELS, RENT_STATUSES, ROLES, TASK_PRIORITIES,
                TASK_STATUSES, TRANSMISSIONS, execute, insert, q, scalar, update)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024


def _secret_key():
    path = os.path.join(db.DATA_DIR, "secret.key")
    os.makedirs(db.DATA_DIR, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


app.secret_key = _secret_key()
app.teardown_appcontext(db.close_db)
db.init_db()

STAGE_NAMES = dict(DEAL_STAGES)
OPEN_STAGES = [s for s, _ in DEAL_STAGES if s not in ("won", "lost")]
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
          "сентябрь", "октябрь", "ноябрь", "декабрь"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


# ================================================================ утилиты
def today():
    return date.today()


def iso(d):
    return d.isoformat() if d else None


def parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def to_int(v):
    if v is None:
        return 0
    s = re.sub(r"[^\d\-]", "", str(v))
    try:
        return int(s) if s not in ("", "-") else 0
    except ValueError:
        return 0


def form_get(fields, money=(), ints=()):
    out = {}
    for f in fields:
        v = request.form.get(f, "").strip()
        if f in money or f in ints:
            out[f] = to_int(v) if v else (0 if f in money else None)
        else:
            out[f] = v or None
    return out


def initials(name):
    parts = (name or "?").split()
    return "".join(p[0] for p in parts[:2]).upper()


def first_name(full):
    p = (full or "").split()
    return p[1] if len(p) == 3 else (p[0] if p else "")


def short_name(full):
    p = (full or "").split()
    if len(p) >= 2:
        return p[0] + " " + " ".join(x[0] + "." for x in p[1:3])
    return full or ""


def car_title(c):
    if not c:
        return ""
    t = " ".join(str(x) for x in (c["brand"], c["model"]) if x)
    if c["year"]:
        t += f", {c['year']}"
    return t


app.add_template_filter(lambda v: short_name(v), "short")


@app.template_filter("money")
def f_money(v, short=False):
    v = v or 0
    if short and abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " млн ₽"
    if short and abs(v) >= 10_000:
        return f"{round(v / 1000):,}".replace(",", " ") + " тыс ₽"
    return f"{int(v):,}".replace(",", " ") + " ₽"


@app.template_filter("num")
def f_num(v):
    return f"{int(v or 0):,}".replace(",", " ")


@app.template_filter("dt")
def f_dt(v, fmt="full"):
    if not v:
        return ""
    s = str(v)
    try:
        d = datetime.fromisoformat(s) if len(s) > 10 else datetime.combine(date.fromisoformat(s), datetime.min.time())
    except ValueError:
        return s
    if fmt == "short":
        return d.strftime("%d.%m")
    if fmt == "human":
        return f"{d.day} {MONTHS_GEN[d.month - 1]}"
    if fmt == "time":
        return d.strftime("%d.%m.%Y %H:%M")
    return d.strftime("%d.%m.%Y")


@app.template_filter("initials")
def f_initials(v):
    return initials(v)


@app.template_filter("phone_link")
def f_phone_link(v):
    return "tel:" + re.sub(r"[^\d+]", "", v or "")


# ================================================================ авторизация
def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = q("SELECT * FROM users WHERE id = ? AND active = 1", (uid,), one=True) if uid else None
    return g.user


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login", next=request.full_path))
        return fn(*a, **kw)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if current_user()["role"] != "admin":
            abort(403)
        return fn(*a, **kw)
    return wrapper


def can_edit():
    u = current_user()
    return u and u["role"] in ("admin", "manager")


def edit_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*a, **kw):
        if not can_edit():
            abort(403)
        return fn(*a, **kw)
    return wrapper


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def before():
    if request.endpoint in ("static", "setup") or request.endpoint is None:
        return
    if not scalar("SELECT COUNT(*) FROM users"):
        return redirect(url_for("setup"))
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if not token or token != session.get("csrf"):
            abort(400, "Форма устарела, обновите страницу")


app.jinja_env.globals.update(DEAL_KINDS=DEAL_KINDS, STAGE_NAMES=STAGE_NAMES, TASK_PRIORITIES=TASK_PRIORITIES,
                             DOC_KINDS=DOC_KINDS, ROLES=ROLES)


@app.context_processor
def inject():
    u = current_user() if session.get("uid") else None
    ctx = dict(user=u, csrf_token=csrf_token, ROLES=ROLES, DEAL_KINDS=DEAL_KINDS,
               STAGE_NAMES=STAGE_NAMES, can_edit=can_edit(), car_title=car_title,
               TASK_PRIORITIES=TASK_PRIORITIES, DOC_KINDS=DOC_KINDS, today_iso=iso(today()))
    if u:
        ctx["settings"] = db.get_settings()
        ctx["counts"] = sidebar_counts()
    return ctx


def sidebar_counts():
    t = iso(today())
    return {
        "tasks": scalar("SELECT COUNT(*) FROM tasks WHERE status != 'Выполнена' AND (assignee_id = ? OR assignee_id IS NULL)",
                        (current_user()["id"],)),
        "deals": scalar(f"SELECT COUNT(*) FROM deals WHERE stage IN ({','.join('?' * len(OPEN_STAGES))})", OPEN_STAGES),
        "clients": scalar("SELECT COUNT(*) FROM clients WHERE temp != 'Архив'"),
        "stock": scalar("SELECT COUNT(*) FROM cars WHERE origin = 'Склад' AND status != 'Продан'"),
        "transit": scalar("SELECT COUNT(*) FROM cars WHERE origin IN ('Китай','Япония','Корея') AND status != 'Продан'"),
        "buyout": scalar("SELECT COUNT(*) FROM cars WHERE origin = 'Выкуп' AND status != 'Продан'"),
        "commission": scalar("SELECT COUNT(*) FROM cars WHERE origin = 'Комиссия' AND status != 'Продан'"),
        "fleet": scalar("SELECT COUNT(*) FROM cars WHERE origin = 'Прокат'"),
        "rent_active": scalar("SELECT COUNT(*) FROM rentals WHERE status IN ('Бронь','Активна') AND end_date >= ?", (t,)),
        "docs": scalar("SELECT COUNT(*) FROM documents"),
        "users": scalar("SELECT COUNT(*) FROM users WHERE active = 1"),
        "chat": chat_unread_total(current_user()["id"]),
    }


@app.route("/setup", methods=["GET", "POST"])
def setup():
    if scalar("SELECT COUNT(*) FROM users"):
        return redirect(url_for("login"))
    if request.method == "POST":
        if request.form.get("_csrf") != session.get("csrf"):
            abort(400)
        name = request.form.get("full_name", "").strip()
        login_ = request.form.get("username", "").strip().lower()
        pw = request.form.get("password", "")
        if not name or not login_ or len(pw) < 6:
            flash("Заполните все поля, пароль не короче 6 символов", "error")
        elif pw != request.form.get("password2"):
            flash("Пароли не совпадают", "error")
        else:
            uid = insert("users", dict(username=login_, full_name=name, role="admin",
                                       password_hash=generate_password_hash(pw)))
            session["uid"] = uid
            if request.form.get("demo"):
                import seed
                seed.load_demo(uid)
            flash("Администратор создан. Добро пожаловать!", "ok")
            return redirect(url_for("dashboard"))
    return render_template("login.html", setup=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE username = ?", (request.form.get("username", "").strip().lower(),), one=True)
        if u and u["active"] and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session["uid"] = u["id"]
            session.permanent = bool(request.form.get("remember"))
            update("users", u["id"], {"last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Неверный логин или пароль" if not (u and not u["active"]) else "Учётная запись отключена", "error")
    return render_template("login.html", setup=False)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    u = current_user()
    if request.method == "POST":
        if not check_password_hash(u["password_hash"], request.form.get("old", "")):
            flash("Текущий пароль неверный", "error")
        elif len(request.form.get("new", "")) < 6:
            flash("Новый пароль не короче 6 символов", "error")
        elif request.form.get("new") != request.form.get("new2"):
            flash("Пароли не совпадают", "error")
        else:
            update("users", u["id"], {"password_hash": generate_password_hash(request.form["new"])})
            flash("Пароль изменён", "ok")
            return redirect(url_for("dashboard"))
    return render_template("profile.html")


# ================================================================ дашборд
@app.route("/")
@login_required
def dashboard():
    t = today()
    ti = iso(t)
    u = current_user()
    hour = datetime.now().hour
    greet = "Доброй ночи" if hour < 5 else "Доброе утро" if hour < 12 else "Добрый день" if hour < 18 else "Добрый вечер"

    calls = q("""SELECT c.*, (SELECT budget FROM deals d WHERE d.client_id = c.id ORDER BY id DESC LIMIT 1) AS budget,
                        (SELECT car_wish FROM deals d WHERE d.client_id = c.id ORDER BY id DESC LIMIT 1) AS car_wish
                 FROM clients c WHERE next_call IS NOT NULL AND next_call <= ? AND temp != 'Архив'
                 ORDER BY next_call LIMIT 8""", (ti,))
    tasks = q("""SELECT t.*, u.full_name AS assignee, c.full_name AS client FROM tasks t
                 LEFT JOIN users u ON u.id = t.assignee_id LEFT JOIN clients c ON c.id = t.client_id
                 WHERE t.status != 'Выполнена' ORDER BY t.due_date IS NULL, t.due_date, t.priority = 'high' DESC LIMIT 8""")
    rent_today = q("""SELECT r.*, c.full_name AS client, k.brand, k.model, k.plate FROM rentals r
                      JOIN clients c ON c.id = r.client_id JOIN cars k ON k.id = r.car_id
                      WHERE r.status IN ('Бронь','Активна') AND r.end_date >= ?
                      ORDER BY r.start_date LIMIT 6""", (ti,))

    stock_where = "status IN ('В наличии','Резерв','В пути','На ремонте') AND origin != 'Прокат'"
    fleet = scalar("SELECT COUNT(*) FROM cars WHERE origin = 'Прокат'")
    rented = scalar("SELECT COUNT(DISTINCT car_id) FROM rentals WHERE status IN ('Активна','Бронь') AND start_date <= ? AND end_date >= ?", (ti, ti))
    m_start, m_end = t.replace(day=1), t.replace(day=monthrange(t.year, t.month)[1])
    kpi = {
        "cars": scalar(f"SELECT COUNT(*) FROM cars WHERE {stock_where}"),
        "stock_value": scalar(f"SELECT SUM(sale_price) FROM cars WHERE {stock_where}"),
        "stock_priced": scalar(f"SELECT COUNT(*) FROM cars WHERE {stock_where} AND sale_price > 0"),
        "margin": scalar(f"SELECT SUM(sale_price - purchase_price - costs) FROM cars WHERE {stock_where} AND sale_price > 0"),
        "fleet": fleet, "rented": rented,
        "load": round(rented * 100 / fleet) if fleet else 0,
        "rent_month": scalar("SELECT SUM(total) FROM rentals WHERE status != 'Отменена' AND start_date BETWEEN ? AND ?", (iso(m_start), iso(m_end))),
        "rent_month_n": scalar("SELECT COUNT(*) FROM rentals WHERE status != 'Отменена' AND start_date BETWEEN ? AND ?", (iso(m_start), iso(m_end))),
        "budgets": scalar(f"SELECT SUM(budget) FROM deals WHERE stage IN ({','.join('?' * len(OPEN_STAGES))})", OPEN_STAGES),
        "new_clients": scalar("SELECT COUNT(*) FROM clients WHERE created_at >= ?", (iso(m_start),)),
        "fee_month": scalar("SELECT SUM(fee) FROM deals WHERE stage = 'won' AND closed_at >= ?", (iso(m_start),)),
        "won_month": scalar("SELECT COUNT(*) FROM deals WHERE stage = 'won' AND closed_at >= ?", (iso(m_start),)),
    }

    funnel = []
    for code in OPEN_STAGES:
        r = q("SELECT COUNT(*) n, COALESCE(SUM(budget),0) s FROM deals WHERE stage = ?", (code,), one=True)
        funnel.append({"code": code, "name": STAGE_NAMES[code], "n": r["n"], "sum": r["s"]})
    fmax = max([f["n"] for f in funnel] + [1])

    kinds = []
    for code, (name, icon) in DEAL_KINDS.items():
        n = scalar(f"SELECT COUNT(*) FROM deals WHERE kind = ? AND stage IN ({','.join('?' * len(OPEN_STAGES))})", (code, *OPEN_STAGES))
        kinds.append({"code": code, "name": name, "icon": icon, "n": n})
    kmax = max([k["n"] for k in kinds] + [1])

    revenue = []
    y, m = t.year, t.month
    for _ in range(6):
        s = date(y, m, 1)
        e = date(y, m, monthrange(y, m)[1])
        revenue.append({"label": MONTHS[m - 1][:3], "sum": scalar(
            "SELECT SUM(total) FROM rentals WHERE status != 'Отменена' AND start_date BETWEEN ? AND ?", (iso(s), iso(e)))})
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    revenue.reverse()
    rmax = max([r["sum"] for r in revenue] + [1])

    recent = q("""SELECT a.*, c.full_name AS client, u.full_name AS author FROM activity a
                  LEFT JOIN clients c ON c.id = a.client_id LEFT JOIN users u ON u.id = a.user_id
                  ORDER BY a.id DESC LIMIT 6""")

    return render_template("dashboard.html", greet=greet, first_name=first_name(u["full_name"]),
                           date_line=f"Сегодня {WEEKDAYS[t.weekday()]}, {t.day} {MONTHS_GEN[t.month - 1]}",
                           calls=calls, tasks=tasks, rent_today=rent_today, kpi=kpi, funnel=funnel, fmax=fmax,
                           kinds=kinds, kmax=kmax, revenue=revenue, rmax=rmax, recent=recent)


@app.route("/search")
@login_required
def search():
    s = request.args.get("q", "").strip()
    res = {"clients": [], "cars": [], "deals": []}
    if s:
        like = f"%{s}%"
        digits = re.sub(r"\D", "", s)
        dlike = f"%{digits}%" if len(digits) >= 3 else like
        res["clients"] = q("""SELECT * FROM clients WHERE full_name LIKE ? OR email LIKE ? OR messenger LIKE ?
                              OR REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'(',''),')',''),'+','') LIKE ?
                              OR phone LIKE ? OR full_name LIKE ? LIMIT 30""",
                           (like, like, like, dlike, like, f"%{s.capitalize()}%"))
        res["cars"] = q("""SELECT * FROM cars WHERE brand LIKE ? OR model LIKE ? OR vin LIKE ? OR plate LIKE ?
                           OR (brand || ' ' || model) LIKE ? OR UPPER(plate) LIKE ? OR UPPER(vin) LIKE ? LIMIT 30""",
                        (like, like, like, like, like, f"%{s.upper()}%", f"%{s.upper()}%"))
        res["deals"] = q("""SELECT d.*, c.full_name AS client FROM deals d JOIN clients c ON c.id = d.client_id
                            WHERE d.title LIKE ? OR d.car_wish LIKE ? LIMIT 30""", (like, like))
    if request.args.get("format") == "json":
        return jsonify({
            "clients": [{"title": c["full_name"], "sub": c["phone"] or "", "url": url_for("client_view", cid=c["id"])} for c in res["clients"][:6]],
            "cars": [{"title": car_title(c), "sub": " · ".join(x for x in (c["plate"], c["vin"], c["status"]) if x), "url": url_for("car_view", car_id=c["id"])} for c in res["cars"][:6]],
        })
    return render_template("search.html", s=s, res=res)


@app.route("/api/notifications")
@login_required
def notifications():
    ti = iso(today())
    items = []
    for t in q("SELECT id, title, due_date FROM tasks WHERE status != 'Выполнена' AND due_date IS NOT NULL AND due_date <= ? ORDER BY due_date LIMIT 10", (ti,)):
        items.append({"icon": "task", "title": t["title"], "sub": ("Просрочена с " + f_dt(t["due_date"], "short")) if t["due_date"] < ti else "Срок сегодня",
                      "url": url_for("task_edit", tid=t["id"]), "warn": t["due_date"] < ti})
    for c in q("SELECT id, full_name, next_call FROM clients WHERE next_call IS NOT NULL AND next_call <= ? AND temp != 'Архив' ORDER BY next_call LIMIT 10", (ti,)):
        items.append({"icon": "phone", "title": "Позвонить: " + c["full_name"], "sub": "с " + f_dt(c["next_call"], "short"),
                      "url": url_for("client_view", cid=c["id"]), "warn": c["next_call"] < ti})
    for r in q("""SELECT r.id, r.end_date, k.brand, k.model, c.full_name FROM rentals r JOIN cars k ON k.id = r.car_id
                  JOIN clients c ON c.id = r.client_id WHERE r.status = 'Активна' AND r.end_date <= ?""", (ti,)):
        items.append({"icon": "key", "title": f"Возврат: {r['brand']} {r['model'] or ''}", "sub": r["full_name"] + " · до " + f_dt(r["end_date"], "short"),
                      "url": url_for("rental_edit", rid=r["id"]), "warn": r["end_date"] < ti})
    n = chat_unread_total(current_user()["id"])
    if n:
        items.insert(0, {"icon": "chat", "title": f"Новые сообщения в чате: {n}", "sub": "Открыть чат",
                         "url": url_for("chat"), "warn": False})
    return jsonify(items)


# ================================================================ клиенты
CLIENT_FIELDS = ["full_name", "phone", "phone2", "email", "messenger", "city", "passport", "birth_date",
                 "license", "source", "temp", "next_call", "notes", "manager_id"]


def users_list():
    return q("SELECT id, full_name, role FROM users WHERE active = 1 ORDER BY full_name")


def log(client_id, text, kind="system"):
    if client_id:
        insert("activity", {"client_id": client_id, "user_id": current_user()["id"], "kind": kind, "text": text})


@app.route("/clients")
@login_required
def clients():
    temp = request.args.get("temp", "")
    kind = request.args.get("kind", "")
    s = request.args.get("q", "").strip()
    where, args = ["1=1"], []
    if temp:
        where.append("c.temp = ?"); args.append(temp)
    elif not s:
        where.append("c.temp != 'Архив'")
    if kind:
        where.append("EXISTS (SELECT 1 FROM deals d WHERE d.client_id = c.id AND d.kind = ?)"); args.append(kind)
    if s:
        where.append("(c.full_name LIKE ? OR c.phone LIKE ? OR c.email LIKE ?)"); args += [f"%{s}%"] * 3
    rows = q(f"""SELECT c.*, u.full_name AS manager,
                 (SELECT GROUP_CONCAT(kind) FROM deals d WHERE d.client_id = c.id AND d.stage NOT IN ('won','lost')) AS kinds,
                 (SELECT COALESCE(SUM(budget),0) FROM deals d WHERE d.client_id = c.id AND d.stage NOT IN ('won','lost')) AS budget
                 FROM clients c LEFT JOIN users u ON u.id = c.manager_id
                 WHERE {' AND '.join(where)} ORDER BY c.id DESC""", args)
    temp_counts = {r["temp"]: r["n"] for r in q("SELECT temp, COUNT(*) n FROM clients GROUP BY temp")}
    return render_template("clients.html", rows=rows, temp=temp, kind=kind, s=s, temps=CLIENT_TEMPS, temp_counts=temp_counts)


@app.route("/clients/export.csv")
@login_required
def clients_export():
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["ID", "ФИО", "Телефон", "Телефон 2", "Email", "Мессенджер", "Город", "Источник", "Статус",
                "Перезвонить", "Менеджер", "Создан", "Заметки"])
    for c in q("SELECT c.*, u.full_name AS manager FROM clients c LEFT JOIN users u ON u.id = c.manager_id ORDER BY c.id"):
        w.writerow([c["id"], c["full_name"], c["phone"], c["phone2"], c["email"], c["messenger"], c["city"],
                    c["source"], c["temp"], c["next_call"], c["manager"], c["created_at"], c["notes"]])
    return Response("﻿" + out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=clients.csv"})


@app.route("/clients/new", methods=["GET", "POST"])
@edit_required
def client_new():
    if request.method == "POST":
        data = form_get(CLIENT_FIELDS, ints=("manager_id",))
        if not data["full_name"]:
            flash("Укажите ФИО клиента", "error")
        else:
            data["manager_id"] = data["manager_id"] or current_user()["id"]
            dup = q("SELECT id, full_name FROM clients WHERE phone = ? AND phone IS NOT NULL", (data["phone"],), one=True) if data["phone"] else None
            cid = insert("clients", data)
            log(cid, "Клиент создан")
            budget = to_int(request.form.get("deal_budget"))
            wish = request.form.get("deal_car_wish", "").strip() or None
            for kind in request.form.getlist("kinds"):
                if kind in DEAL_KINDS:
                    did = insert("deals", {"client_id": cid, "kind": kind, "stage": "new", "budget": budget,
                                           "car_wish": wish, "title": DEAL_KINDS[kind][0],
                                           "manager_id": data["manager_id"]})
                    log(cid, f"Заявка: {DEAL_KINDS[kind][0]}" + (f" · {wish}" if wish else ""))
            if dup:
                flash(f"Внимание: телефон уже есть у клиента «{dup['full_name']}»", "warn")
            flash("Клиент добавлен", "ok")
            return redirect(url_for("client_view", cid=cid))
    return render_template("client_form.html", c=request.form if request.method == "POST" else {"temp": "Холодный", "manager_id": current_user()["id"]},
                           users=users_list(), sources=CLIENT_SOURCES, temps=CLIENT_TEMPS,
                           preselect=request.values.getlist("kinds") or request.args.getlist("kind"), is_new=True)


@app.route("/clients/<int:cid>/edit", methods=["GET", "POST"])
@edit_required
def client_edit(cid):
    c = q("SELECT * FROM clients WHERE id = ?", (cid,), one=True) or abort(404)
    if request.method == "POST":
        data = form_get(CLIENT_FIELDS, ints=("manager_id",))
        if not data["full_name"]:
            flash("Укажите ФИО клиента", "error")
        else:
            if data["temp"] != c["temp"]:
                log(cid, f"Статус: {c['temp']} → {data['temp']}")
            update("clients", cid, data)
            flash("Сохранено", "ok")
            return redirect(url_for("client_view", cid=cid))
    return render_template("client_form.html", c=c, users=users_list(), sources=CLIENT_SOURCES, temps=CLIENT_TEMPS,
                           preselect=[], is_new=False)


@app.route("/clients/<int:cid>")
@login_required
def client_view(cid):
    c = q("SELECT c.*, u.full_name AS manager FROM clients c LEFT JOIN users u ON u.id = c.manager_id WHERE c.id = ?", (cid,), one=True) or abort(404)
    deals = q("SELECT d.*, u.full_name AS manager FROM deals d LEFT JOIN users u ON u.id = d.manager_id WHERE client_id = ? ORDER BY d.id DESC", (cid,))
    tasks = q("SELECT t.*, u.full_name AS assignee FROM tasks t LEFT JOIN users u ON u.id = t.assignee_id WHERE client_id = ? ORDER BY status = 'Выполнена', due_date", (cid,))
    rentals = q("SELECT r.*, k.brand, k.model, k.plate FROM rentals r JOIN cars k ON k.id = r.car_id WHERE client_id = ? ORDER BY start_date DESC", (cid,))
    docs = q("SELECT * FROM documents WHERE client_id = ? ORDER BY id DESC", (cid,))
    cars = q("SELECT * FROM cars WHERE owner_client_id = ? ORDER BY id DESC", (cid,))
    acts = q("SELECT a.*, u.full_name AS author FROM activity a LEFT JOIN users u ON u.id = a.user_id WHERE client_id = ? ORDER BY a.id DESC LIMIT 100", (cid,))
    events = q("SELECT * FROM events WHERE client_id = ? AND date >= ? ORDER BY date, time", (cid, iso(today())))
    return render_template("client_view.html", c=c, deals=deals, tasks=tasks, rentals=rentals, docs=docs, cars=cars,
                           acts=acts, events=events, stages=DEAL_STAGES)


@app.route("/clients/<int:cid>/note", methods=["POST"])
@edit_required
def client_note(cid):
    text = request.form.get("text", "").strip()
    kind = request.form.get("kind", "note")
    if text:
        log(cid, text, kind if kind in ("note", "call", "meet") else "note")
    nc = request.form.get("next_call")
    if nc is not None:
        update("clients", cid, {"next_call": nc or None})
    return redirect(url_for("client_view", cid=cid) + "#timeline")


@app.route("/clients/<int:cid>/called", methods=["POST"])
@edit_required
def client_called(cid):
    update("clients", cid, {"next_call": None})
    log(cid, "Звонок выполнен", "call")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/clients/<int:cid>/delete", methods=["POST"])
@admin_required
def client_delete(cid):
    if scalar("SELECT COUNT(*) FROM rentals WHERE client_id = ?", (cid,)):
        flash("У клиента есть аренды — переведите его в «Архив» вместо удаления", "error")
        return redirect(url_for("client_view", cid=cid))
    execute("UPDATE cars SET owner_client_id = NULL WHERE owner_client_id = ?", (cid,))
    execute("DELETE FROM clients WHERE id = ?", (cid,))
    flash("Клиент удалён", "ok")
    return redirect(url_for("clients"))


# ================================================================ сделки / воронка
DEAL_FIELDS = ["client_id", "kind", "stage", "title", "car_wish", "budget", "amount", "fee", "prepaid",
               "car_id", "manager_id", "deadline", "notes"]


@app.route("/deals")
@login_required
def deals():
    kind = request.args.get("kind", "")
    mine = request.args.get("mine")
    where, args = ["1=1"], []
    if kind:
        where.append("d.kind = ?"); args.append(kind)
    if mine:
        where.append("d.manager_id = ?"); args.append(current_user()["id"])
    rows = q(f"""SELECT d.*, c.full_name AS client, c.phone, c.temp, u.full_name AS manager,
                 k.brand, k.model, k.year FROM deals d JOIN clients c ON c.id = d.client_id
                 LEFT JOIN users u ON u.id = d.manager_id LEFT JOIN cars k ON k.id = d.car_id
                 WHERE {' AND '.join(where)} AND (d.stage NOT IN ('won','lost') OR d.closed_at >= ?)
                 ORDER BY d.id DESC""", (*args, iso(today() - timedelta(days=30))))
    cols = {s: [] for s, _ in DEAL_STAGES}
    for r in rows:
        cols.setdefault(r["stage"], []).append(r)
    sums = {s: sum(r["budget"] or 0 for r in v) for s, v in cols.items()}
    return render_template("deals.html", cols=cols, sums=sums, stages=DEAL_STAGES, kind=kind, mine=mine)


@app.route("/api/deals/<int:did>/stage", methods=["POST"])
@edit_required
def deal_stage(did):
    d = q("SELECT * FROM deals WHERE id = ?", (did,), one=True) or abort(404)
    stage = (request.get_json(silent=True) or {}).get("stage") or request.form.get("stage")
    if stage not in STAGE_NAMES:
        abort(400)
    if stage != d["stage"]:
        update("deals", did, {"stage": stage, "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if stage in ("won", "lost") else None})
        log(d["client_id"], f"{DEAL_KINDS.get(d['kind'], ('Сделка',))[0]}: {STAGE_NAMES[d['stage']]} → {STAGE_NAMES[stage]}")
        if stage == "won" and d["car_id"]:
            if d["kind"] in ("sale", "china", "japan", "korea", "commission"):
                update("cars", d["car_id"], {"status": "Продан"})
    if request.is_json:
        return jsonify(ok=True)
    return redirect(request.referrer or url_for("deals"))


def deal_form_ctx():
    return dict(clients=q("SELECT id, full_name, phone FROM clients WHERE temp != 'Архив' OR 1 ORDER BY full_name"),
                cars=q("SELECT * FROM cars WHERE status != 'Продан' ORDER BY brand, model"),
                users=users_list(), stages=DEAL_STAGES)


@app.route("/deals/new", methods=["GET", "POST"])
@edit_required
def deal_new():
    if request.method == "POST":
        data = form_get(DEAL_FIELDS, money=("budget", "amount", "fee", "prepaid"), ints=("client_id", "car_id", "manager_id"))
        if not data["client_id"] or data["kind"] not in DEAL_KINDS:
            flash("Выберите клиента и тип сделки", "error")
        else:
            data["title"] = data["title"] or DEAL_KINDS[data["kind"]][0]
            data["stage"] = data["stage"] or "new"
            did = insert("deals", data)
            log(data["client_id"], f"Новая сделка: {data['title']}")
            flash("Сделка создана", "ok")
            return redirect(request.form.get("back") or url_for("deals"))
    d = {"client_id": to_int(request.args.get("client_id")) or None, "kind": request.args.get("kind", "selection"),
         "stage": "new", "manager_id": current_user()["id"], "car_id": to_int(request.args.get("car_id")) or None}
    return render_template("deal_form.html", d=d, is_new=True, back=request.referrer, **deal_form_ctx())


@app.route("/deals/<int:did>/edit", methods=["GET", "POST"])
@edit_required
def deal_edit(did):
    d = q("SELECT * FROM deals WHERE id = ?", (did,), one=True) or abort(404)
    if request.method == "POST":
        data = form_get(DEAL_FIELDS, money=("budget", "amount", "fee", "prepaid"), ints=("client_id", "car_id", "manager_id"))
        if data["stage"] != d["stage"]:
            data["closed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if data["stage"] in ("won", "lost") else None
            log(d["client_id"], f"{data['title'] or 'Сделка'}: {STAGE_NAMES[d['stage']]} → {STAGE_NAMES[data['stage']]}")
        update("deals", did, data)
        flash("Сделка сохранена", "ok")
        return redirect(request.form.get("back") or url_for("deals"))
    return render_template("deal_form.html", d=d, is_new=False, back=request.referrer, **deal_form_ctx())


@app.route("/deals/<int:did>/delete", methods=["POST"])
@admin_required
def deal_delete(did):
    execute("DELETE FROM deals WHERE id = ?", (did,))
    flash("Сделка удалена", "ok")
    return redirect(url_for("deals"))


# ================================================================ склад авто
CAR_FIELDS = ["brand", "model", "year", "vin", "plate", "color", "mileage", "engine", "fuel", "transmission",
              "drive", "body", "origin", "status", "purchase_price", "costs", "sale_price", "rent_day_price",
              "owner_client_id", "arrival_date", "notes"]
CAR_VIEWS = {
    "all": ("Все автомобили", None),
    "stock": ("Автомобили на складе", "origin = 'Склад' AND status != 'Продан'"),
    "transit": ("Заказ: Китай · Япония · Корея", "origin IN ('Китай','Япония','Корея') AND status != 'Продан'"),
    "china": ("Из Китая", "origin = 'Китай' AND status != 'Продан'"),
    "japan": ("Из Японии", "origin = 'Япония' AND status != 'Продан'"),
    "korea": ("Из Кореи", "origin = 'Корея' AND status != 'Продан'"),
    "buyout": ("Выкуп", "origin = 'Выкуп' AND status != 'Продан'"),
    "commission": ("Комиссия", "origin = 'Комиссия' AND status != 'Продан'"),
    "fleet": ("Прокатный автопарк", "origin = 'Прокат'"),
    "sold": ("Проданные", "status = 'Продан'"),
}


@app.route("/cars")
@login_required
def cars():
    view = request.args.get("view", "all")
    title, cond = CAR_VIEWS.get(view, CAR_VIEWS["all"])
    s = request.args.get("q", "").strip()
    st = request.args.get("status", "")
    where, args = [cond or ("status != 'Продан'" if not st else "1=1")], []
    if s:
        where.append("(brand LIKE ? OR model LIKE ? OR vin LIKE ? OR plate LIKE ?)"); args += [f"%{s}%"] * 4
    if st:
        where.append("status = ?"); args.append(st)
    rows = q(f"""SELECT k.*, c.full_name AS owner,
                 (SELECT r.end_date FROM rentals r WHERE r.car_id = k.id AND r.status = 'Активна' ORDER BY r.end_date DESC LIMIT 1) AS rent_until
                 FROM cars k LEFT JOIN clients c ON c.id = k.owner_client_id
                 WHERE {' AND '.join(where)} ORDER BY k.id DESC""", args)
    totals = {"n": len(rows), "buy": sum((r["purchase_price"] or 0) + (r["costs"] or 0) for r in rows),
              "sale": sum(r["sale_price"] or 0 for r in rows),
              "margin": sum((r["sale_price"] or 0) - (r["purchase_price"] or 0) - (r["costs"] or 0) for r in rows if r["sale_price"])}
    return render_template("cars.html", rows=rows, view=view, title=title, views=CAR_VIEWS, s=s, st=st,
                           statuses=CAR_STATUSES, totals=totals, layout=request.args.get("layout", request.cookies.get("cars_layout", "grid")))


def car_form_ctx():
    return dict(origins=CAR_ORIGINS, statuses=CAR_STATUSES, transmissions=TRANSMISSIONS, drives=DRIVES, fuels=FUELS,
                clients=q("SELECT id, full_name FROM clients ORDER BY full_name"))


def save_photo(car_id):
    name = save_image("photo", f"car{car_id}")
    if name:
        update("cars", car_id, {"photo": name})


@app.route("/uploads/<path:name>")
@login_required
def uploads(name):
    if name.startswith("chat/"):
        ok = q("""SELECT 1 FROM messages m JOIN chat_members c ON c.chat_id = m.chat_id AND c.user_id = ?
                  WHERE m.file = ?""", (current_user()["id"], name), one=True)
        if not ok:
            abort(404)
    return send_from_directory(db.UPLOAD_DIR, name)


@app.route("/cars/new", methods=["GET", "POST"])
@edit_required
def car_new():
    if request.method == "POST":
        data = form_get(CAR_FIELDS, money=("purchase_price", "costs", "sale_price", "rent_day_price"),
                        ints=("year", "mileage", "owner_client_id"))
        data["vin"] = (data["vin"] or "").upper() or None
        data["plate"] = (data["plate"] or "").upper() or None
        if not data["brand"]:
            flash("Укажите марку", "error")
        else:
            car_id = insert("cars", data)
            save_photo(car_id)
            if data["owner_client_id"]:
                log(data["owner_client_id"], f"Авто принято: {car_title(data)} ({data['origin']})")
            flash("Автомобиль добавлен", "ok")
            return redirect(url_for("car_view", car_id=car_id))
    view = request.args.get("view", "")
    origin = {"stock": "Склад", "china": "Китай", "japan": "Япония", "korea": "Корея", "transit": "Китай",
              "buyout": "Выкуп", "commission": "Комиссия", "fleet": "Прокат"}.get(view, "Склад")
    status = "В пути" if origin in ("Китай", "Япония", "Корея") else "В наличии"
    return render_template("car_form.html", k={"origin": origin, "status": status,
                                               "owner_client_id": to_int(request.args.get("client_id")) or None},
                           is_new=True, **car_form_ctx())


@app.route("/cars/<int:car_id>/edit", methods=["GET", "POST"])
@edit_required
def car_edit(car_id):
    k = q("SELECT * FROM cars WHERE id = ?", (car_id,), one=True) or abort(404)
    if request.method == "POST":
        data = form_get(CAR_FIELDS, money=("purchase_price", "costs", "sale_price", "rent_day_price"),
                        ints=("year", "mileage", "owner_client_id"))
        data["vin"] = (data["vin"] or "").upper() or None
        data["plate"] = (data["plate"] or "").upper() or None
        if not data["brand"]:
            flash("Укажите марку", "error")
        else:
            update("cars", car_id, data)
            save_photo(car_id)
            if request.form.get("remove_photo"):
                update("cars", car_id, {"photo": None})
            flash("Сохранено", "ok")
            return redirect(url_for("car_view", car_id=car_id))
    return render_template("car_form.html", k=k, is_new=False, **car_form_ctx())


@app.route("/cars/<int:car_id>")
@login_required
def car_view(car_id):
    k = q("SELECT k.*, c.full_name AS owner FROM cars k LEFT JOIN clients c ON c.id = k.owner_client_id WHERE k.id = ?", (car_id,), one=True) or abort(404)
    rentals = q("SELECT r.*, c.full_name AS client FROM rentals r JOIN clients c ON c.id = r.client_id WHERE car_id = ? ORDER BY start_date DESC", (car_id,))
    deals = q("SELECT d.*, c.full_name AS client FROM deals d JOIN clients c ON c.id = d.client_id WHERE car_id = ? ORDER BY d.id DESC", (car_id,))
    docs = q("SELECT * FROM documents WHERE car_id = ? ORDER BY id DESC", (car_id,))
    rent_income = sum(r["total"] or 0 for r in rentals if r["status"] != "Отменена")
    return render_template("car_view.html", k=k, rentals=rentals, deals=deals, docs=docs, rent_income=rent_income)


@app.route("/cars/<int:car_id>/delete", methods=["POST"])
@admin_required
def car_delete(car_id):
    if scalar("SELECT COUNT(*) FROM rentals WHERE car_id = ?", (car_id,)):
        flash("У автомобиля есть история проката — поставьте статус «Продан» вместо удаления", "error")
        return redirect(url_for("car_view", car_id=car_id))
    execute("UPDATE deals SET car_id = NULL WHERE car_id = ?", (car_id,))
    execute("DELETE FROM cars WHERE id = ?", (car_id,))
    flash("Автомобиль удалён", "ok")
    return redirect(url_for("cars"))


# ================================================================ прокат
RENT_FIELDS = ["car_id", "client_id", "start_date", "end_date", "price_day", "total", "deposit", "paid",
               "mileage_out", "mileage_in", "status", "notes", "manager_id"]


@app.route("/rentals")
@login_required
def rentals():
    span = to_int(request.args.get("days")) or 21
    start = parse_date(request.args.get("from")) or (today() - timedelta(days=3))
    end = start + timedelta(days=span - 1)
    fleet = q("SELECT * FROM cars WHERE origin = 'Прокат' OR rent_day_price > 0 ORDER BY brand, model")
    rents = q("""SELECT r.*, c.full_name AS client, c.phone FROM rentals r JOIN clients c ON c.id = r.client_id
                 WHERE r.status != 'Отменена' AND r.start_date <= ? AND r.end_date >= ?""", (iso(end), iso(start)))
    bars = {}
    for r in rents:
        s = max(parse_date(r["start_date"]), start)
        e = min(parse_date(r["end_date"]), end)
        bars.setdefault(r["car_id"], []).append({"r": r, "left": (s - start).days, "width": (e - s).days + 1})
    days = [start + timedelta(days=i) for i in range(span)]
    status = request.args.get("status", "")
    where, args = ["1=1"], []
    if status:
        where.append("r.status = ?"); args.append(status)
    else:
        where.append("r.status IN ('Бронь','Активна')")
    lst = q(f"""SELECT r.*, c.full_name AS client, c.phone, k.brand, k.model, k.plate FROM rentals r
                JOIN clients c ON c.id = r.client_id JOIN cars k ON k.id = r.car_id
                WHERE {' AND '.join(where)} ORDER BY r.start_date DESC LIMIT 200""", args)
    return render_template("rentals.html", fleet=fleet, bars=bars, days=days, start=start, span=span, lst=lst,
                           status=status, statuses=RENT_STATUSES, prev=iso(start - timedelta(days=7)),
                           next=iso(start + timedelta(days=7)), t=today())


def rent_form_ctx():
    return dict(cars=q("SELECT * FROM cars WHERE (origin = 'Прокат' OR rent_day_price > 0) AND status != 'Продан' ORDER BY brand"),
                clients=q("SELECT id, full_name, phone FROM clients ORDER BY full_name"), users=users_list(),
                statuses=RENT_STATUSES)


def rent_conflict(data, rid=None):
    return q("""SELECT r.*, c.full_name AS client FROM rentals r JOIN clients c ON c.id = r.client_id
                WHERE r.car_id = ? AND r.status IN ('Бронь','Активна') AND r.id != ?
                AND r.start_date <= ? AND r.end_date >= ?""",
             (data["car_id"], rid or 0, data["end_date"], data["start_date"]), one=True)


def rent_save(rid=None):
    data = form_get(RENT_FIELDS, money=("price_day", "total", "deposit", "paid"),
                    ints=("car_id", "client_id", "mileage_out", "mileage_in", "manager_id"))
    s, e = parse_date(data["start_date"]), parse_date(data["end_date"])
    if not (data["car_id"] and data["client_id"] and s and e):
        flash("Выберите авто, клиента и даты", "error"); return None
    if e < s:
        flash("Дата возврата раньше даты выдачи", "error"); return None
    if data["status"] in ("Бронь", "Активна"):
        c = rent_conflict(data, rid)
        if c:
            flash(f"Авто уже занято: {c['client']} {f_dt(c['start_date'], 'short')}–{f_dt(c['end_date'], 'short')}", "error")
            return None
    if not data["total"]:
        data["total"] = ((e - s).days or 1) * (data["price_day"] or 0)
    if rid:
        update("rentals", rid, data)
    else:
        rid = insert("rentals", data)
        log(data["client_id"], f"Прокат: бронь {f_dt(data['start_date'], 'short')}–{f_dt(data['end_date'], 'short')}")
    car = q("SELECT * FROM cars WHERE id = ?", (data["car_id"],), one=True)
    if data["status"] == "Активна" and car["status"] != "В прокате":
        update("cars", car["id"], {"status": "В прокате"})
    elif data["status"] in ("Завершена", "Отменена") and car["status"] == "В прокате":
        if not scalar("SELECT COUNT(*) FROM rentals WHERE car_id = ? AND status = 'Активна'", (car["id"],)):
            update("cars", car["id"], {"status": "В наличии"})
    if data["status"] == "Завершена" and data["mileage_in"]:
        update("cars", car["id"], {"mileage": data["mileage_in"]})
    return rid


@app.route("/rentals/new", methods=["GET", "POST"])
@edit_required
def rental_new():
    if request.method == "POST":
        rid = rent_save()
        if rid:
            flash("Аренда оформлена", "ok")
            return redirect(url_for("rentals"))
        r = request.form
    else:
        car_id = to_int(request.args.get("car_id")) or None
        car = q("SELECT * FROM cars WHERE id = ?", (car_id,), one=True) if car_id else None
        sd = request.args.get("start") or iso(today())
        r = {"car_id": car_id, "client_id": to_int(request.args.get("client_id")) or None, "start_date": sd,
             "end_date": iso(parse_date(sd) + timedelta(days=1)), "price_day": car["rent_day_price"] if car else "",
             "status": "Бронь", "manager_id": current_user()["id"]}
    return render_template("rental_form.html", r=r, is_new=True, **rent_form_ctx())


@app.route("/rentals/<int:rid>/edit", methods=["GET", "POST"])
@edit_required
def rental_edit(rid):
    r = q("SELECT * FROM rentals WHERE id = ?", (rid,), one=True) or abort(404)
    if request.method == "POST":
        if rent_save(rid):
            flash("Аренда сохранена", "ok")
            return redirect(url_for("rentals"))
        r = request.form
    return render_template("rental_form.html", r=r, rid=rid, is_new=False, **rent_form_ctx())


@app.route("/rentals/<int:rid>/delete", methods=["POST"])
@admin_required
def rental_delete(rid):
    execute("DELETE FROM rentals WHERE id = ?", (rid,))
    flash("Аренда удалена", "ok")
    return redirect(url_for("rentals"))


# ================================================================ задачи
TASK_FIELDS = ["title", "description", "due_date", "due_time", "priority", "status", "assignee_id", "client_id", "deal_id"]


@app.route("/tasks")
@login_required
def tasks():
    flt = request.args.get("f", "open")
    who = request.args.get("who", "")
    ti = iso(today())
    where, args = ["1=1"], []
    if flt == "open":
        where.append("t.status != 'Выполнена'")
    elif flt == "today":
        where.append("t.status != 'Выполнена' AND t.due_date <= ?"); args.append(ti)
    elif flt == "overdue":
        where.append("t.status != 'Выполнена' AND t.due_date < ?"); args.append(ti)
    elif flt == "done":
        where.append("t.status = 'Выполнена'")
    if who == "me":
        where.append("t.assignee_id = ?"); args.append(current_user()["id"])
    rows = q(f"""SELECT t.*, u.full_name AS assignee, c.full_name AS client FROM tasks t
                 LEFT JOIN users u ON u.id = t.assignee_id LEFT JOIN clients c ON c.id = t.client_id
                 WHERE {' AND '.join(where)}
                 ORDER BY t.status = 'Выполнена', t.due_date IS NULL, t.due_date, t.due_time,
                          CASE t.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END
                 LIMIT 500""", args)
    groups = {"overdue": [], "today": [], "week": [], "later": [], "nodate": [], "done": []}
    wk = iso(today() + timedelta(days=7))
    for t in rows:
        if t["status"] == "Выполнена":
            groups["done"].append(t)
        elif not t["due_date"]:
            groups["nodate"].append(t)
        elif t["due_date"] < ti:
            groups["overdue"].append(t)
        elif t["due_date"] == ti:
            groups["today"].append(t)
        elif t["due_date"] <= wk:
            groups["week"].append(t)
        else:
            groups["later"].append(t)
    return render_template("tasks.html", groups=groups, flt=flt, who=who, users=users_list())


def task_ctx():
    return dict(users=users_list(), clients=q("SELECT id, full_name FROM clients ORDER BY full_name"),
                statuses=TASK_STATUSES, priorities=TASK_PRIORITIES)


@app.route("/tasks/new", methods=["GET", "POST"])
@edit_required
def task_new():
    if request.method == "POST":
        data = form_get(TASK_FIELDS, ints=("assignee_id", "client_id", "deal_id"))
        if not data["title"]:
            flash("Введите название задачи", "error")
        else:
            data["created_by"] = current_user()["id"]
            data["priority"] = data["priority"] or "normal"
            data["status"] = data["status"] or "Новая"
            insert("tasks", data)
            log(data["client_id"], f"Задача: {data['title']}")
            flash("Задача создана", "ok")
            return redirect(request.form.get("back") or url_for("tasks"))
    t = {"due_date": request.args.get("date") or iso(today()), "priority": "normal", "status": "Новая",
         "assignee_id": current_user()["id"], "client_id": to_int(request.args.get("client_id")) or None,
         "title": request.args.get("title", "")}
    return render_template("task_form.html", t=t, is_new=True, back=request.referrer, **task_ctx())


@app.route("/tasks/<int:tid>/edit", methods=["GET", "POST"])
@edit_required
def task_edit(tid):
    t = q("SELECT * FROM tasks WHERE id = ?", (tid,), one=True) or abort(404)
    if request.method == "POST":
        data = form_get(TASK_FIELDS, ints=("assignee_id", "client_id", "deal_id"))
        if data["status"] == "Выполнена" and t["status"] != "Выполнена":
            data["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update("tasks", tid, data)
        flash("Задача сохранена", "ok")
        return redirect(request.form.get("back") or url_for("tasks"))
    return render_template("task_form.html", t=t, tid=tid, is_new=False, back=request.referrer, **task_ctx())


@app.route("/tasks/<int:tid>/toggle", methods=["POST"])
@edit_required
def task_toggle(tid):
    t = q("SELECT * FROM tasks WHERE id = ?", (tid,), one=True) or abort(404)
    if t["status"] == "Выполнена":
        update("tasks", tid, {"status": "Новая", "done_at": None})
    else:
        update("tasks", tid, {"status": "Выполнена", "done_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        log(t["client_id"], f"Задача выполнена: {t['title']}")
    if request.is_json or request.headers.get("X-CSRF"):
        return jsonify(ok=True)
    return redirect(request.referrer or url_for("tasks"))


@app.route("/tasks/<int:tid>/delete", methods=["POST"])
@edit_required
def task_delete(tid):
    execute("DELETE FROM tasks WHERE id = ?", (tid,))
    flash("Задача удалена", "ok")
    return redirect(url_for("tasks"))


# ================================================================ календарь
def calendar_items(start, end):
    s, e = iso(start), iso(end)
    items = []
    for t in q("SELECT t.*, c.full_name AS client FROM tasks t LEFT JOIN clients c ON c.id = t.client_id WHERE due_date BETWEEN ? AND ?", (s, e)):
        items.append({"date": t["due_date"], "time": t["due_time"] or "", "title": t["title"], "type": "task",
                      "done": t["status"] == "Выполнена", "sub": t["client"] or "", "url": url_for("task_edit", tid=t["id"])})
    for ev in q("SELECT e.*, c.full_name AS client FROM events e LEFT JOIN clients c ON c.id = e.client_id WHERE date BETWEEN ? AND ?", (s, e)):
        items.append({"date": ev["date"], "time": ev["time"] or "", "title": ev["title"], "type": "event", "kind": ev["kind"],
                      "sub": ev["client"] or ev["kind"], "url": url_for("event_edit", eid=ev["id"])})
    for c in q("SELECT id, full_name, next_call FROM clients WHERE next_call BETWEEN ? AND ?", (s, e)):
        items.append({"date": c["next_call"], "time": "", "title": "Звонок: " + short_name(c["full_name"]), "type": "call",
                      "sub": "", "url": url_for("client_view", cid=c["id"])})
    for r in q("""SELECT r.*, c.full_name AS client, k.brand, k.model FROM rentals r JOIN clients c ON c.id = r.client_id
                  JOIN cars k ON k.id = r.car_id WHERE r.status IN ('Бронь','Активна')
                  AND (r.start_date BETWEEN ? AND ? OR r.end_date BETWEEN ? AND ?)""", (s, e, s, e)):
        car = f"{r['brand']} {r['model'] or ''}".strip()
        if s <= r["start_date"] <= e:
            items.append({"date": r["start_date"], "time": "", "title": f"Выдача: {car}", "type": "rent_out",
                          "sub": short_name(r["client"]), "url": url_for("rental_edit", rid=r["id"])})
        if s <= r["end_date"] <= e:
            items.append({"date": r["end_date"], "time": "", "title": f"Возврат: {car}", "type": "rent_in",
                          "sub": short_name(r["client"]), "url": url_for("rental_edit", rid=r["id"])})
    for d in q("SELECT d.*, c.full_name AS client FROM deals d JOIN clients c ON c.id = d.client_id WHERE deadline BETWEEN ? AND ? AND stage NOT IN ('won','lost')", (s, e)):
        items.append({"date": d["deadline"], "time": "", "title": f"Срок: {d['title']}", "type": "deal",
                      "sub": short_name(d["client"]), "url": url_for("deal_edit", did=d["id"])})
    items.sort(key=lambda x: (x["date"], x["time"] or "99"))
    return items


@app.route("/calendar")
@login_required
def calendar_view():
    t = today()
    y = to_int(request.args.get("y")) or t.year
    m = to_int(request.args.get("m")) or t.month
    first = date(y, m, 1)
    grid_start = first - timedelta(days=first.weekday())
    weeks = []
    d = grid_start
    while True:
        weeks.append([d + timedelta(days=i) for i in range(7)])
        d += timedelta(days=7)
        if d.month != m and d > first:
            break
    items = calendar_items(weeks[0][0], weeks[-1][-1])
    by_day = {}
    for it in items:
        by_day.setdefault(it["date"], []).append(it)
    sel = request.args.get("d") or iso(t)
    pm = (first - timedelta(days=1))
    nm = (first + timedelta(days=32)).replace(day=1)
    return render_template("calendar.html", weeks=weeks, by_day=by_day, y=y, m=m, month_name=MONTHS[m - 1].capitalize(),
                           prev=(pm.year, pm.month), next=(nm.year, nm.month), t=t, sel=sel,
                           sel_items=by_day.get(sel) or calendar_items(parse_date(sel) or t, parse_date(sel) or t),
                           sel_date=parse_date(sel) or t, weekdays=WEEKDAYS, months_gen=MONTHS_GEN)


@app.route("/api/calendar")
@login_required
def api_calendar():
    y = to_int(request.args.get("y")) or today().year
    m = to_int(request.args.get("m")) or today().month
    s = date(y, m, 1)
    e = date(y, m, monthrange(y, m)[1])
    out = {}
    for it in calendar_items(s, e):
        out.setdefault(it["date"], set()).add(it["type"])
    return jsonify({k: sorted(v) for k, v in out.items()})


EVENT_FIELDS = ["title", "kind", "date", "time", "client_id", "user_id", "notes"]


@app.route("/events/new", methods=["GET", "POST"])
@edit_required
def event_new():
    if request.method == "POST":
        data = form_get(EVENT_FIELDS, ints=("client_id", "user_id"))
        if not data["title"] or not data["date"]:
            flash("Укажите название и дату", "error")
        else:
            insert("events", data)
            log(data["client_id"], f"{data['kind']}: {data['title']} — {f_dt(data['date'])} {data['time'] or ''}")
            flash("Событие добавлено", "ok")
            return redirect(url_for("calendar_view", d=data["date"], y=data["date"][:4], m=int(data["date"][5:7])))
    e = {"date": request.args.get("date") or iso(today()), "kind": "Встреча", "user_id": current_user()["id"],
         "client_id": to_int(request.args.get("client_id")) or None}
    return render_template("event_form.html", e=e, is_new=True, kinds=EVENT_KINDS, users=users_list(),
                           clients=q("SELECT id, full_name FROM clients ORDER BY full_name"))


@app.route("/events/<int:eid>/edit", methods=["GET", "POST"])
@edit_required
def event_edit(eid):
    e = q("SELECT * FROM events WHERE id = ?", (eid,), one=True) or abort(404)
    if request.method == "POST":
        if request.form.get("delete"):
            execute("DELETE FROM events WHERE id = ?", (eid,))
            flash("Событие удалено", "ok")
        else:
            update("events", eid, form_get(EVENT_FIELDS, ints=("client_id", "user_id")))
            flash("Событие сохранено", "ok")
        return redirect(url_for("calendar_view", d=e["date"], y=e["date"][:4], m=int(e["date"][5:7])))
    return render_template("event_form.html", e=e, eid=eid, is_new=False, kinds=EVENT_KINDS, users=users_list(),
                           clients=q("SELECT id, full_name FROM clients ORDER BY full_name"))


# ================================================================ документы
def next_doc_number(kind):
    n = scalar("SELECT COUNT(*) FROM documents WHERE kind = ?", (kind,)) + 1
    return f"{n:04d}"


@app.route("/documents")
@login_required
def documents():
    kind = request.args.get("kind", "")
    where, args = ["1=1"], []
    if kind:
        where.append("d.kind = ?"); args.append(kind)
    rows = q(f"""SELECT d.*, c.full_name AS client, k.brand, k.model, k.year, u.full_name AS author FROM documents d
                 LEFT JOIN clients c ON c.id = d.client_id LEFT JOIN cars k ON k.id = d.car_id
                 LEFT JOIN users u ON u.id = d.created_by WHERE {' AND '.join(where)} ORDER BY d.id DESC""", args)
    return render_template("documents.html", rows=rows, kind=kind,
                           clients=q("SELECT id, full_name FROM clients ORDER BY full_name"),
                           cars=q("SELECT * FROM cars ORDER BY brand, model"),
                           rentals=q("""SELECT r.id, r.start_date, c.full_name, k.brand, k.model FROM rentals r
                                        JOIN clients c ON c.id = r.client_id JOIN cars k ON k.id = r.car_id
                                        WHERE r.status != 'Отменена' ORDER BY r.id DESC LIMIT 50"""))


@app.route("/documents/new", methods=["GET", "POST"])
@edit_required
def document_new():
    src = request.values
    kind = src.get("kind")
    if kind not in DOC_KINDS:
        abort(400)
    client_id = to_int(src.get("client_id")) or None
    car_id = to_int(src.get("car_id")) or None
    rental_id = to_int(src.get("rental_id")) or None
    deal_id = to_int(src.get("deal_id")) or None
    if rental_id:
        r = q("SELECT * FROM rentals WHERE id = ?", (rental_id,), one=True)
        if r:
            client_id, car_id = client_id or r["client_id"], car_id or r["car_id"]
    if deal_id:
        d = q("SELECT * FROM deals WHERE id = ?", (deal_id,), one=True)
        if d:
            client_id, car_id = client_id or d["client_id"], car_id or d["car_id"]
    number = next_doc_number(kind)
    client = q("SELECT full_name FROM clients WHERE id = ?", (client_id,), one=True) if client_id else None
    title = f"{DOC_KINDS[kind][0]} №{number}" + (f" — {short_name(client['full_name'])}" if client else "")
    did = insert("documents", {"kind": kind, "number": number, "title": title, "client_id": client_id, "car_id": car_id,
                               "rental_id": rental_id, "deal_id": deal_id, "created_by": current_user()["id"]})
    log(client_id, f"Документ создан: {title}")
    return redirect(url_for("document_view", did=did))


def doc_prefill(d):
    c = q("SELECT * FROM clients WHERE id = ?", (d["client_id"],), one=True) if d["client_id"] else None
    k = q("SELECT * FROM cars WHERE id = ?", (d["car_id"],), one=True) if d["car_id"] else None
    deal = q("SELECT * FROM deals WHERE id = ?", (d["deal_id"],), one=True) if d["deal_id"] else None
    if not deal and d["client_id"]:
        deal = q("SELECT * FROM deals WHERE client_id = ? ORDER BY id DESC LIMIT 1", (d["client_id"],), one=True)
    p = {}
    if d["kind"] == "dogovor":
        p["#docNo"] = d["number"]
        if c:
            p.update({"#cName": c["full_name"], "#cPhone": c["phone"] or "", "#cMail": c["email"] or "",
                      "#cPass": c["passport"] or ""})
        if k:
            p["#carModel"] = car_title(k)
        elif deal and deal["car_wish"]:
            p["#carModel"] = deal["car_wish"]
        p["#actNo"] = d["number"]
    elif d["kind"] == "akt_osmotra":
        p["#actNo"] = d["number"]
        if c:
            p.update({"Клиент (ФИО)": c["full_name"], "Телефон": c["phone"] or ""})
        if deal and deal["budget"]:
            p["Бюджет"] = f_money(deal["budget"])
        if k:
            p.update({"#carModel": car_title(k).split(",")[0], "Год": str(k["year"] or ""), "Госномер": k["plate"] or "",
                      "Цвет": k["color"] or "", "Пробег, км": f_num(k["mileage"]) if k["mileage"] else "",
                      "Двигатель, л / л.с.": k["engine"] or "",
                      "Цена продавца": f_money(k["purchase_price"]) if k["purchase_price"] else ""})
            if k["vin"]:
                p["@vin"] = k["vin"]
    return p


@app.route("/documents/<int:did>")
@login_required
def document_view(did):
    d = q("""SELECT d.*, c.full_name AS client, u.full_name AS author FROM documents d
             LEFT JOIN clients c ON c.id = d.client_id LEFT JOIN users u ON u.id = d.created_by WHERE d.id = ?""", (did,), one=True) or abort(404)
    if DOC_KINDS[d["kind"]][1]:
        car = q("SELECT * FROM cars WHERE id = ?", (d["car_id"],), one=True) if d["car_id"] else None
        return render_template("document_view.html", d=d, car=car)
    return render_print_doc(d)


def render_print_doc(d):
    c = q("SELECT * FROM clients WHERE id = ?", (d["client_id"],), one=True) if d["client_id"] else None
    k = q("SELECT * FROM cars WHERE id = ?", (d["car_id"],), one=True) if d["car_id"] else None
    r = q("SELECT * FROM rentals WHERE id = ?", (d["rental_id"],), one=True) if d["rental_id"] else None
    saved = json.loads(d["data"]) if d["data"] else {}
    days = None
    if r:
        days = max((parse_date(r["end_date"]) - parse_date(r["start_date"])).days, 1)
    st = db.get_settings()
    signer = short_name(re.sub(r"^(ИП|ООО)\s+", "", st.get("company_legal") or ""))
    return render_template("print_doc.html", d=d, c=c, k=k, r=r, days=days, saved=saved, s=st, signer=signer)


@app.route("/documents/<int:did>/form")
@login_required
def document_form(did):
    d = q("SELECT * FROM documents WHERE id = ?", (did,), one=True) or abort(404)
    fname = DOC_KINDS[d["kind"]][1]
    if not fname:
        abort(404)
    # Берём бланк из папки программы (если вы его правите — CRM сразу видит изменения), иначе копию из static/docs
    src_dirs = {"dogovor.html": "Договор - программа", "akt_osmotra.html": "Акт осмотра - программа"}
    path = os.path.join(db.BASE_DIR, src_dirs.get(fname, ""), fname)
    if not os.path.exists(path):
        path = os.path.join(app.static_folder, "docs", fname)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    key = f"crm-doc-{did}"
    html = re.sub(r"const KEY = '[^']*';", f"const KEY = '{key}';", html, count=1)
    html = html.replace("localStorage.setItem(KEY, JSON.stringify(collect()));",
                        "localStorage.setItem(KEY, JSON.stringify(collect())); window.__crmSync && window.__crmSync(collect());")
    bridge = render_template("_doc_bridge.html", did=did, key=key,
                             saved=json.loads(d["data"]) if d["data"] else None,
                             prefill=None if d["data"] else doc_prefill(d),
                             readonly=not can_edit())
    html = html.replace("</head>", bridge + "\n</head>", 1)
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/documents/<int:did>", methods=["GET", "POST"])
@login_required
def document_data(did):
    d = q("SELECT * FROM documents WHERE id = ?", (did,), one=True) or abort(404)
    if request.method == "GET":
        return Response(d["data"] or "{}", mimetype="application/json")
    if not can_edit():
        abort(403)
    body = request.get_json(silent=True) or {}
    upd = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    if "data" in body:
        upd["data"] = json.dumps(body["data"], ensure_ascii=False)
    if body.get("title"):
        upd["title"] = body["title"][:200]
    update("documents", did, upd)
    return jsonify(ok=True, saved=upd["updated_at"])


@app.route("/documents/<int:did>/meta", methods=["POST"])
@edit_required
def document_meta(did):
    data = form_get(["title", "number", "client_id", "car_id"], ints=("client_id", "car_id"))
    if request.form.get("save_print"):
        fields = {k[2:]: v for k, v in request.form.items() if k.startswith("f_")}
        update("documents", did, {"data": json.dumps(fields, ensure_ascii=False),
                                  "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        flash("Документ сохранён", "ok")
        return redirect(url_for("document_view", did=did))
    update("documents", did, {k: v for k, v in data.items() if v is not None or k in ("client_id", "car_id")})
    flash("Сохранено", "ok")
    return redirect(url_for("document_view", did=did))


@app.route("/documents/<int:did>/delete", methods=["POST"])
@edit_required
def document_delete(did):
    execute("DELETE FROM documents WHERE id = ?", (did,))
    flash("Документ удалён", "ok")
    return redirect(url_for("documents"))


# ================================================================ администрирование
@app.route("/admin/users")
@admin_required
def admin_users():
    rows = q("""SELECT u.*, (SELECT COUNT(*) FROM clients c WHERE c.manager_id = u.id) AS n_clients,
                (SELECT COUNT(*) FROM deals d WHERE d.manager_id = u.id AND d.stage NOT IN ('won','lost')) AS n_deals,
                (SELECT COUNT(*) FROM tasks t WHERE t.assignee_id = u.id AND t.status != 'Выполнена') AS n_tasks
                FROM users u ORDER BY u.active DESC, u.role, u.full_name""")
    return render_template("admin_users.html", rows=rows)


def gen_password():
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


@app.route("/admin/users/new", methods=["GET", "POST"])
@app.route("/admin/users/<int:uid>", methods=["GET", "POST"])
@admin_required
def admin_user(uid=None):
    u = q("SELECT * FROM users WHERE id = ?", (uid,), one=True) if uid else None
    if uid and not u:
        abort(404)
    if request.method == "POST":
        data = form_get(["full_name", "username", "role", "phone", "email"])
        data["username"] = (data["username"] or "").lower()
        pw = request.form.get("password", "").strip()
        active = 1 if request.form.get("active") else 0
        err = None
        if not data["full_name"] or not data["username"]:
            err = "Укажите имя и логин"
        elif not re.fullmatch(r"[a-z0-9._\-]{3,32}", data["username"]):
            err = "Логин: латиница, цифры, точка, дефис (3–32 символа)"
        elif q("SELECT id FROM users WHERE username = ? AND id != ?", (data["username"], uid or 0), one=True):
            err = "Такой логин уже занят"
        elif not uid and len(pw) < 6:
            err = "Пароль не короче 6 символов"
        elif uid and pw and len(pw) < 6:
            err = "Пароль не короче 6 символов"
        elif data["role"] not in ROLES:
            err = "Выберите роль"
        elif uid == current_user()["id"] and (data["role"] != "admin" or not active):
            err = "Нельзя снять с себя права администратора или отключить себя"
        if err:
            flash(err, "error")
            return render_template("admin_user_form.html", u=request.form, uid=uid, gen=pw or gen_password())
        data["active"] = active
        photo = save_image("photo", "user")
        if photo:
            data["photo"] = photo
        elif request.form.get("remove_photo"):
            data["photo"] = None
        if pw:
            data["password_hash"] = generate_password_hash(pw)
        if uid:
            update("users", uid, data)
        else:
            uid = insert("users", data)
        if pw:
            session["new_credentials"] = {"login": data["username"], "password": pw, "name": data["full_name"]}
        flash("Пользователь сохранён", "ok")
        return redirect(url_for("admin_users"))
    return render_template("admin_user_form.html", u=u or {"role": "manager", "active": 1}, uid=uid, gen=gen_password())


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for k in db.DEFAULT_SETTINGS:
            db.set_setting(k, request.form.get(k, "").strip())
        flash("Настройки сохранены", "ok")
        return redirect(url_for("admin_settings"))
    stats = {t: scalar(f"SELECT COUNT(*) FROM {t}") for t in ("clients", "deals", "cars", "rentals", "tasks", "documents")}
    return render_template("admin_settings.html", s=db.get_settings(), stats=stats, db_path=db.DB_PATH)


@app.route("/admin/backup")
@admin_required
def admin_backup():
    return send_from_directory(os.path.dirname(db.DB_PATH), os.path.basename(db.DB_PATH), as_attachment=True,
                               download_name=f"crm-backup-{today().isoformat()}.db")


@app.route("/admin/demo", methods=["POST"])
@admin_required
def admin_demo():
    import seed
    seed.load_demo(current_user()["id"])
    flash("Демо-данные загружены", "ok")
    return redirect(url_for("dashboard"))


# ================================================================ изображения и фото сотрудников
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def save_image(field, prefix, subdir=""):
    f = request.files.get(field)
    if not f or not f.filename:
        return None
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in IMG_EXT:
        flash("Фото: допустимы JPG, PNG, WEBP, GIF", "error")
        return None
    name = f"{prefix}_{uuid.uuid4().hex[:10]}{ext}"
    f.save(os.path.join(db.UPLOAD_DIR, subdir, name))
    return (subdir + "/" + name) if subdir else name


def user_photo(key):
    """URL фото сотрудника по id или ФИО (для аватаров)."""
    if key is None:
        return None
    if "photos" not in g:
        g.photos = {}
        for r in q("SELECT id, full_name, photo FROM users WHERE photo IS NOT NULL AND photo != ''"):
            u = url_for("uploads", name=r["photo"])
            g.photos[r["id"]] = u
            g.photos[r["full_name"]] = u
    return g.photos.get(key)


app.jinja_env.globals["user_photo"] = user_photo


@app.route("/profile/photo", methods=["POST"])
@login_required
def profile_photo():
    uid = current_user()["id"]
    if request.form.get("remove"):
        update("users", uid, {"photo": None})
        flash("Фото удалено", "ok")
    else:
        name = save_image("photo", f"user{uid}")
        if name:
            update("users", uid, {"photo": name})
            flash("Фото обновлено", "ok")
    return redirect(url_for("profile"))


# ================================================================ ценники
TAG_FILES = {"v": ("cenik_v.html", "chiauto_cenik_current_v1", "chiauto_cenik_keep_v1", "Вертикальный A4"),
             "h": ("cenik_h.html", "chiauto_cenik_h_current_v1", "chiauto_cenik_h_keep_v1", "Горизонтальный A4")}


def car_tag_state(k, layout):
    origin = {"Китай": "Из Китая", "Япония": "Из Японии", "Корея": "Из Кореи"}.get(k["origin"], "")
    status = {"В наличии": "В наличии", "В пути": "В пути", "Резерв": "Забронирован"}.get(k["status"], "")
    eng = (k["engine"] or "").strip()
    m = re.match(r"\s*(\d+[.,]?\d*)\s*(?:л\.?)?\s*(?:/\s*(\d+))?", eng)
    vol = m.group(1).replace(",", ".") if m else ""
    power = (m.group(2) or "") if m else ""
    fuel = (k["fuel"] or "").lower()
    low = lambda v: (v or "").lower()
    price = str(k["sale_price"] or "") if k["sale_price"] else ""
    if layout == "v":
        return {
            "drom": "", "brand": k["brand"] or "", "model": k["model"] or "", "trim": "", "status": status, "origin": origin,
            "price": price, "oldPrice": "", "priceNote": "", "year": str(k["year"] or ""),
            "mileage": str(k["mileage"] or ""), "power": power,
            "engine": (vol + " л") if vol else eng, "fuel": fuel,
            "specs": [["КПП", low(k["transmission"])], ["Привод", low(k["drive"])], ["Кузов", low(k["body"])],
                      ["Цвет", low(k["color"])], ["Руль", "левый"], ["Владельцы", ""], ["Пробег по РФ", ""]],
            "feats": "", "featText": "",
        }
    return {
        "brand": k["brand"] or "", "model": k["model"] or "", "year": str(k["year"] or ""), "trim": "",
        "status": status, "origin": origin,
        "specs": [["Двигатель", " ".join(x for x in ((vol + " л") if vol else eng, fuel) if x).capitalize()],
                  ["Мощность", (power + " л.с.") if power else ""], ["Коробка передач", k["transmission"] or ""],
                  ["Привод", k["drive"] or ""], ["Пробег", (f_num(k["mileage"]) + " км") if k["mileage"] else ""],
                  ["Комплектация", ""]],
        "price": price, "oldPrice": "", "orderPrice": "", "orderFrom": True, "priceNote": "",
        "showDate": True, "date": iso(today()),
    }


@app.route("/pricetags")
@login_required
def pricetags():
    rows = q("""SELECT * FROM cars WHERE status != 'Продан' AND origin != 'Прокат'
                ORDER BY CASE status WHEN 'В наличии' THEN 0 WHEN 'Резерв' THEN 1 WHEN 'В пути' THEN 2 ELSE 3 END, brand, model""")
    return render_template("pricetags.html", rows=rows)


@app.route("/pricetags/<layout>")
@login_required
def pricetag(layout):
    if layout not in TAG_FILES:
        abort(404)
    fname, ls_cur, ls_keep, _ = TAG_FILES[layout]
    with open(os.path.join(app.static_folder, "tags", fname), encoding="utf-8") as f:
        html = f.read()
    car_id = to_int(request.args.get("car_id"))
    k = q("SELECT * FROM cars WHERE id = ?", (car_id,), one=True) if car_id else None
    bridge = render_template("_tag_bridge.html", ls_cur=ls_cur, ls_keep=ls_keep,
                             state=car_tag_state(k, layout) if k else None,
                             phone=db.get_settings().get("company_phone") or "",
                             back=url_for("car_view", car_id=k["id"]) if k else url_for("pricetags"),
                             car=car_title(k) if k else "")
    html = html.replace("</head>", bridge + "\n</head>", 1)
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ================================================================ чат
def chat_member(cid, uid=None):
    return q("SELECT * FROM chat_members WHERE chat_id = ? AND user_id = ?", (cid, uid or current_user()["id"]), one=True)


def chat_info(c, uid):
    """Название и аватар чата с точки зрения пользователя."""
    if c["is_group"]:
        return {"title": c["title"] or "Группа", "photo": None, "peer": None}
    peer = q("""SELECT u.* FROM chat_members m JOIN users u ON u.id = m.user_id
                WHERE m.chat_id = ? AND m.user_id != ? LIMIT 1""", (c["id"], uid), one=True)
    if not peer:
        return {"title": "Заметки для себя", "photo": user_photo(uid), "peer": None}
    return {"title": peer["full_name"], "photo": user_photo(peer["id"]), "peer": peer}


def my_chats(uid):
    rows = q("""SELECT c.*, m.last_read,
                  (SELECT COUNT(*) FROM messages x WHERE x.chat_id = c.id AND x.id > m.last_read
                     AND (x.user_id IS NULL OR x.user_id != ?)) AS unread,
                  (SELECT MAX(id) FROM messages x WHERE x.chat_id = c.id) AS last_id
                FROM chats c JOIN chat_members m ON m.chat_id = c.id AND m.user_id = ?
                ORDER BY COALESCE(last_id, 0) DESC, c.id DESC""", (uid, uid))
    out = []
    for c in rows:
        last = q("SELECT m.*, u.full_name FROM messages m LEFT JOIN users u ON u.id = m.user_id WHERE m.id = ?",
                 (c["last_id"],), one=True) if c["last_id"] else None
        info = chat_info(c, uid)
        preview = ""
        if last:
            preview = last["text"] or ("📎 " + (last["file_name"] or "файл"))
            if c["is_group"] and last["full_name"] and not last["system"]:
                preview = ("Вы" if last["user_id"] == uid else last["full_name"].split()[0 if len(last["full_name"].split()) < 3 else 1]) + ": " + preview
        out.append({"id": c["id"], "is_group": c["is_group"], "title": info["title"], "photo": info["photo"],
                    "unread": c["unread"], "preview": preview[:80], "time": last["created_at"] if last else c["created_at"],
                    "members": scalar("SELECT COUNT(*) FROM chat_members WHERE chat_id = ?", (c["id"],))})
    return out


def chat_unread_total(uid):
    return scalar("""SELECT COUNT(*) FROM messages x JOIN chat_members m ON m.chat_id = x.chat_id AND m.user_id = ?
                     WHERE x.id > m.last_read AND (x.user_id IS NULL OR x.user_id != ?)""", (uid, uid))


def can_manage_chat(c):
    u = current_user()
    return c["is_group"] and (c["created_by"] == u["id"] or u["role"] == "admin")


def sys_msg(cid, text):
    insert("messages", {"chat_id": cid, "text": text, "system": 1})


@app.route("/chat")
@app.route("/chat/<int:cid>")
@login_required
def chat(cid=None):
    u = current_user()
    active = members = None
    if cid:
        c = q("SELECT * FROM chats WHERE id = ?", (cid,), one=True)
        if not c or not chat_member(cid):
            abort(404)
        info = chat_info(c, u["id"])
        members = q("""SELECT u.id, u.full_name, u.role, u.active FROM chat_members m JOIN users u ON u.id = m.user_id
                       WHERE m.chat_id = ? ORDER BY u.full_name""", (cid,))
        active = {"id": cid, "is_group": c["is_group"], "title": info["title"], "photo": info["photo"],
                  "peer": info["peer"], "can_manage": can_manage_chat(c), "created_by": c["created_by"]}
    staff = q("SELECT id, full_name, role FROM users WHERE active = 1 AND id != ? ORDER BY full_name", (u["id"],))
    return render_template("chat.html", chats=my_chats(u["id"]), active=active, members=members, staff=staff,
                           member_ids=[m["id"] for m in members] if members else [])


@app.route("/chat/dm/<int:uid>")
@login_required
def chat_dm(uid):
    me = current_user()["id"]
    other = q("SELECT id, full_name FROM users WHERE id = ?", (uid,), one=True) or abort(404)
    row = q("""SELECT c.id FROM chats c WHERE c.is_group = 0
               AND EXISTS (SELECT 1 FROM chat_members WHERE chat_id = c.id AND user_id = ?)
               AND EXISTS (SELECT 1 FROM chat_members WHERE chat_id = c.id AND user_id = ?)
               AND (SELECT COUNT(*) FROM chat_members WHERE chat_id = c.id) = ?""",
            (me, uid, 1 if me == uid else 2), one=True)
    if row:
        return redirect(url_for("chat", cid=row["id"]))
    cid = insert("chats", {"is_group": 0, "created_by": me})
    insert("chat_members", {"chat_id": cid, "user_id": me})
    if uid != me:
        insert("chat_members", {"chat_id": cid, "user_id": uid})
    return redirect(url_for("chat", cid=cid))


@app.route("/chat/group/new", methods=["POST"])
@login_required
def chat_group_new():
    me = current_user()
    title = request.form.get("title", "").strip()[:80]
    ids = {to_int(x) for x in request.form.getlist("members") if to_int(x)}
    if not title:
        flash("Введите название группы", "error")
        return redirect(url_for("chat"))
    cid = insert("chats", {"title": title, "is_group": 1, "created_by": me["id"]})
    for uid in ids | {me["id"]}:
        if q("SELECT id FROM users WHERE id = ? AND active = 1", (uid,), one=True):
            insert("chat_members", {"chat_id": cid, "user_id": uid})
    sys_msg(cid, f"{me['full_name']} создал(а) группу «{title}»")
    return redirect(url_for("chat", cid=cid))


@app.route("/chat/<int:cid>/manage", methods=["POST"])
@login_required
def chat_manage(cid):
    me = current_user()
    c = q("SELECT * FROM chats WHERE id = ?", (cid,), one=True)
    if not c or not chat_member(cid):
        abort(404)
    action = request.form.get("action")
    if action == "leave" and c["is_group"]:
        execute("DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?", (cid, me["id"]))
        sys_msg(cid, f"{me['full_name']} вышел(ла) из группы")
        flash("Вы вышли из группы", "ok")
        return redirect(url_for("chat"))
    if not can_manage_chat(c):
        abort(403)
    if action == "rename":
        title = request.form.get("title", "").strip()[:80]
        if title and title != c["title"]:
            update("chats", cid, {"title": title})
            sys_msg(cid, f"{me['full_name']} переименовал(а) группу в «{title}»")
    elif action == "add":
        for uid in {to_int(x) for x in request.form.getlist("members") if to_int(x)}:
            u = q("SELECT * FROM users WHERE id = ? AND active = 1", (uid,), one=True)
            if u and not chat_member(cid, uid):
                insert("chat_members", {"chat_id": cid, "user_id": uid,
                                        "last_read": scalar("SELECT MAX(id) FROM messages WHERE chat_id = ?", (cid,))})
                sys_msg(cid, f"{me['full_name']} добавил(а) {u['full_name']}")
    elif action == "remove":
        uid = to_int(request.form.get("user_id"))
        u = q("SELECT * FROM users WHERE id = ?", (uid,), one=True)
        if u and uid != c["created_by"]:
            execute("DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?", (cid, uid))
            sys_msg(cid, f"{me['full_name']} удалил(а) {u['full_name']} из группы")
    elif action == "delete":
        execute("DELETE FROM chats WHERE id = ?", (cid,))
        flash("Группа удалена", "ok")
        return redirect(url_for("chat"))
    return redirect(url_for("chat", cid=cid))


def msg_json(m, uid):
    f = m["file"]
    return {"id": m["id"], "user_id": m["user_id"], "author": m["full_name"] or "", "initials": initials(m["full_name"]),
            "photo": user_photo(m["user_id"]), "text": m["text"] or "", "system": bool(m["system"]),
            "file": url_for("uploads", name=f) if f else None, "file_name": m["file_name"] or "",
            "is_image": bool(f and os.path.splitext(f)[1].lower() in IMG_EXT),
            "time": m["created_at"][11:16], "date": m["created_at"][:10], "mine": m["user_id"] == uid}


@app.route("/api/chat/<int:cid>/messages")
@login_required
def chat_messages(cid):
    uid = current_user()["id"]
    if not chat_member(cid):
        abort(404)
    after = to_int(request.args.get("after"))
    rows = q("""SELECT * FROM (SELECT m.*, u.full_name FROM messages m LEFT JOIN users u ON u.id = m.user_id
                WHERE m.chat_id = ? AND m.id > ? ORDER BY m.id DESC LIMIT 300) ORDER BY id""", (cid, after))
    if rows:
        execute("UPDATE chat_members SET last_read = MAX(last_read, ?) WHERE chat_id = ? AND user_id = ?", (rows[-1]["id"], cid, uid))
    return jsonify([msg_json(m, uid) for m in rows])


@app.route("/api/chat/<int:cid>/send", methods=["POST"])
@login_required
def chat_send(cid):
    uid = current_user()["id"]
    if not chat_member(cid):
        abort(404)
    text = (request.form.get("text") or "").strip()[:4000]
    data = {"chat_id": cid, "user_id": uid, "text": text or None}
    f = request.files.get("file")
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext in (".exe", ".bat", ".cmd", ".js", ".vbs", ".ps1", ".msi", ".scr", ".html", ".htm", ".svg"):
            return jsonify(error="Такой тип файла отправлять нельзя"), 400
        name = f"chat/{uuid.uuid4().hex}{ext}"
        f.save(os.path.join(db.UPLOAD_DIR, name))
        data.update(file=name, file_name=os.path.basename(f.filename)[:120])
    if not data["text"] and not data.get("file"):
        return jsonify(error="Пустое сообщение"), 400
    mid = insert("messages", data)
    execute("UPDATE chat_members SET last_read = ? WHERE chat_id = ? AND user_id = ?", (mid, cid, uid))
    m = q("SELECT m.*, u.full_name FROM messages m LEFT JOIN users u ON u.id = m.user_id WHERE m.id = ?", (mid,), one=True)
    return jsonify(msg_json(m, uid))


@app.route("/api/chat/unread")
@login_required
def chat_unread():
    uid = current_user()["id"]
    per = {str(r["chat_id"]): r["n"] for r in q("""SELECT x.chat_id, COUNT(*) n FROM messages x
              JOIN chat_members m ON m.chat_id = x.chat_id AND m.user_id = ?
              WHERE x.id > m.last_read AND (x.user_id IS NULL OR x.user_id != ?) GROUP BY x.chat_id""", (uid, uid))}
    return jsonify(total=sum(per.values()), chats=per)


@app.errorhandler(400)
def e400(e):
    if request.endpoint == "login":
        flash("Страница устарела — попробуйте войти ещё раз", "error")
        return redirect(url_for("login"))
    return render_template("error.html", code=400, msg=getattr(e, "description", "") or "Неверный запрос"), 400


@app.errorhandler(403)
def e403(_):
    return render_template("error.html", code=403, msg="Недостаточно прав для этого действия"), 403


@app.errorhandler(404)
def e404(_):
    return render_template("error.html", code=404, msg="Страница не найдена"), 404


if __name__ == "__main__":
    host = "0.0.0.0" if "--lan" in sys.argv else "127.0.0.1"
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  CRM АвтоБрокер запущена: http://127.0.0.1:{port}\n"
          + ("  Доступ из локальной сети включён (--lan)\n" if host == "0.0.0.0" else ""))
    if "--no-browser" not in sys.argv:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host=host, port=port, debug=False)
