"""Демо-данные, чтобы посмотреть CRM в работе. Загружаются из «Настройки → Демо-данные»."""
import random
from datetime import date, timedelta

from db import insert, scalar

CLIENTS = [
    ("Иванов Сергей Петрович", "+7 914 123-45-67", "Авито", "Горячий"),
    ("Смирнова Анна Викторовна", "+7 902 555-12-34", "Сайт", "Тёплый"),
    ("Кузнецов Дмитрий Олегович", "+7 950 777-88-99", "Рекомендация", "Горячий"),
    ("Попова Елена Игоревна", "+7 908 222-33-44", "Telegram", "Холодный"),
    ("Васильев Артём Николаевич", "+7 964 111-22-33", "Drom", "Тёплый"),
    ("Петров Максим Андреевич", "+7 924 333-44-55", "WhatsApp", "Клиент"),
    ("Соколова Ольга Сергеевна", "+7 983 444-55-66", "Instagram", "Холодный"),
    ("Михайлов Игорь Валерьевич", "+7 904 666-77-88", "Повторный клиент", "Клиент"),
    ("Новиков Роман Евгеньевич", "+7 914 888-99-00", "Авито", "Тёплый"),
    ("Фёдорова Мария Алексеевна", "+7 952 101-20-30", "VK", "Горячий"),
]

STOCK = [
    ("Toyota", "Camry", 2021, "Склад", "В наличии", 2_350_000, 60_000, 2_690_000, 0, "A001AA138"),
    ("Mazda", "CX-5", 2020, "Склад", "В наличии", 2_100_000, 45_000, 2_390_000, 0, "M555MM38"),
    ("Kia", "Sportage", 2022, "Склад", "Резерв", 2_450_000, 30_000, 2_790_000, 0, "K777KK38"),
    ("Geely", "Monjaro", 2024, "Китай", "В пути", 3_200_000, 280_000, 3_890_000, 0, None),
    ("Changan", "UNI-K", 2024, "Китай", "В пути", 2_650_000, 250_000, 3_150_000, 0, None),
    ("Li Auto", "L7", 2024, "Китай", "В пути", 4_100_000, 350_000, 4_890_000, 0, None),
    ("Toyota", "Harrier", 2020, "Япония", "В пути", 2_700_000, 320_000, 3_350_000, 0, None),
    ("Honda", "Vezel", 2021, "Япония", "В наличии", 1_750_000, 210_000, 2_190_000, 0, "H123HH138"),
    ("Hyundai", "Palisade", 2022, "Корея", "В пути", 3_900_000, 300_000, 4_590_000, 0, None),
    ("Kia", "K5", 2021, "Корея", "В наличии", 1_950_000, 220_000, 2_450_000, 0, "K505KK138"),
    ("Toyota", "Corolla", 2017, "Выкуп", "В наличии", 1_150_000, 40_000, 1_390_000, 0, "C017CC38"),
    ("Lexus", "RX 300", 2019, "Комиссия", "В наличии", 0, 0, 4_300_000, 0, "L300LL138"),
]

FLEET = [
    ("Geely", "Jiaji", 2023, 3500, "P101PP138"),
    ("Toyota", "Prius", 2018, 2500, "P202PP138"),
    ("Hyundai", "Solaris", 2020, 2200, "P303PP138"),
    ("Kia", "Rio", 2021, 2300, "P404PP138"),
    ("Toyota", "Land Cruiser Prado", 2019, 7000, "P505PP138"),
]

KINDS = ["china", "japan", "korea", "selection", "sale", "purchase", "commission", "rent"]
STAGES = ["new", "new", "consult", "calc", "contract", "work", "deal", "won", "lost"]


def vin():
    return "".join(random.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(17))


def load_demo(user_id):
    if scalar("SELECT COUNT(*) FROM clients") > 0:
        return
    random.seed(38)
    t = date.today()
    cids = []
    for i, (name, phone, src, temp) in enumerate(CLIENTS):
        cid = insert("clients", {"full_name": name, "phone": phone, "source": src, "temp": temp, "city": "Иркутск",
                                 "manager_id": user_id,
                                 "next_call": (t - timedelta(days=i % 3)).isoformat() if i in (0, 2, 9) else None})
        insert("activity", {"client_id": cid, "user_id": user_id, "text": "Клиент создан (демо)", "kind": "system"})
        cids.append(cid)

    car_ids = []
    for brand, model, year, origin, status, buy, costs, sale, rent, plate in STOCK:
        car_ids.append(insert("cars", {
            "brand": brand, "model": model, "year": year, "origin": origin, "status": status,
            "purchase_price": buy, "costs": costs, "sale_price": sale, "rent_day_price": rent, "plate": plate,
            "vin": vin(), "mileage": random.randint(15, 90) * 1000, "color": random.choice(["Белый", "Чёрный", "Серый", "Синий"]),
            "transmission": "АКПП", "fuel": "Бензин", "drive": random.choice(["Передний", "Полный"]),
            "arrival_date": (t + timedelta(days=random.randint(5, 40))).isoformat() if status == "В пути" else None,
            "owner_client_id": cids[7] if origin == "Комиссия" else None}))
    fleet_ids = []
    for brand, model, year, price, plate in FLEET:
        fleet_ids.append(insert("cars", {"brand": brand, "model": model, "year": year, "origin": "Прокат",
                                         "status": "В наличии", "rent_day_price": price, "plate": plate, "vin": vin(),
                                         "mileage": random.randint(30, 120) * 1000, "transmission": "АКПП",
                                         "color": "Белый", "purchase_price": 0}))

    wishes = ["Geely Monjaro до 3,5 млн", "Toyota Harrier 2020+", "Kia Sorento, дизель", "Mazda CX-5, полный привод",
              "Седан до 2 млн", "Honda Fit на каждый день", "Li Auto L7", "Hyundai Palisade", "Кроссовер для семьи", "Prius на прокат"]
    for i, cid in enumerate(cids):
        kind = KINDS[i % len(KINDS)]
        stage = STAGES[i % len(STAGES)]
        budget = random.choice([1_500_000, 2_000_000, 2_500_000, 3_000_000, 3_500_000, 4_500_000])
        insert("deals", {"client_id": cid, "kind": kind, "stage": stage, "title": {
            "china": "Заказ авто из Китая", "japan": "Заказ авто из Японии", "korea": "Заказ авто из Кореи",
            "selection": "Подбор автомобиля", "sale": "Продажа автомобиля", "purchase": "Покупка авто (выкуп)",
            "commission": "Комиссия авто", "rent": "Прокат"}[kind],
            "budget": budget if kind != "rent" else 30_000, "fee": random.choice([30_000, 50_000, 70_000, 100_000]),
            "car_wish": wishes[i], "manager_id": user_id,
            "closed_at": t.isoformat() if stage in ("won", "lost") else None,
            "deadline": (t + timedelta(days=random.randint(1, 25))).isoformat() if stage in ("contract", "work") else None})

    for n, (fid, cid) in enumerate(zip(fleet_ids[:4], cids[4:8])):
        s = t + timedelta(days=[-3, -1, 2, -20][n])
        e = s + timedelta(days=[5, 4, 3, 6][n])
        status = "Активна" if s <= t <= e else ("Бронь" if s > t else "Завершена")
        price = FLEET[n][3]
        insert("rentals", {"car_id": fid, "client_id": cid, "start_date": s.isoformat(), "end_date": e.isoformat(),
                           "price_day": price, "total": price * (e - s).days, "deposit": 10_000, "paid": price * (e - s).days,
                           "status": status, "manager_id": user_id})
    for m in range(1, 6):
        s = (t.replace(day=1) - timedelta(days=30 * m)).replace(day=10)
        for j in range(2 + m % 3):
            fid = fleet_ids[j % len(fleet_ids)]
            st = s + timedelta(days=j * 4)
            days = 3 + j
            price = FLEET[j % len(FLEET)][3]
            insert("rentals", {"car_id": fid, "client_id": cids[j], "start_date": st.isoformat(),
                               "end_date": (st + timedelta(days=days)).isoformat(), "price_day": price,
                               "total": price * days, "paid": price * days, "status": "Завершена", "manager_id": user_id})
    from db import execute
    execute("UPDATE cars SET status = 'В прокате' WHERE id IN (SELECT car_id FROM rentals WHERE status = 'Активна')")

    tasks = [("Отправить клиенту подборку по Monjaro", 0, "high", cids[0]),
             ("Заказать коврики для автомобиля", 0, "normal", None),
             ("Проверить статус контейнера из Китая", 1, "high", None),
             ("Оформить фальш-номера на авто из Китая", 1, "normal", None),
             ("Осмотр Toyota Harrier на площадке", 2, "normal", cids[1]),
             ("Подготовить договор комиссии", -1, "high", cids[7]),
             ("Сделать фото Lexus RX для объявления", 4, "low", None)]
    for title, dd, pr, cid in tasks:
        insert("tasks", {"title": title, "due_date": (t + timedelta(days=dd)).isoformat(), "priority": pr,
                         "status": "Новая", "assignee_id": user_id, "client_id": cid, "created_by": user_id})
    insert("events", {"title": "Встреча с клиентом в офисе", "kind": "Встреча", "date": (t + timedelta(days=1)).isoformat(),
                      "time": "11:00", "client_id": cids[2], "user_id": user_id})
    insert("events", {"title": "Приёмка авто с автовоза", "kind": "Приём авто", "date": (t + timedelta(days=3)).isoformat(),
                      "time": "15:30", "user_id": user_id})
