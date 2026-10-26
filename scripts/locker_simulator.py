"""Эмулятор постамата РосПит: подписывает запросы так же, как прошивка ESP32.

С ним весь сценарий постамата показывается без железа.

    # весь сценарий: заказ → «Положен в ячейку» → QR → ячейка открылась → «Выдан»
    python scripts/locker_simulator.py demo

    # отдельные действия устройства
    python scripts/locker_simulator.py scan "ROSPIT:L:…"      # студент поднёс QR
    python scripts/locker_simulator.py pin 123456              # ввёл PIN
    python scripts/locker_simulator.py listen                  # ждать команд сервера
    python scripts/locker_simulator.py event door_closed 7     # событие двери
    python scripts/locker_simulator.py heartbeat

Секрет устройства: --secret, переменная LOCKER_SECRET или — для стенда разработчика —
вывод из SECRET_KEY (так же, как на сервере, см. app/lockers.py: device_secret).
Узнать секрет для прошивки: python scripts/locker_simulator.py secret
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import secrets
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx

DEFAULT_BASE = os.environ.get("ROSPIT_URL", "http://localhost:8000")
DEFAULT_DEVICE = "locker-b1"
DEV_SECRET_KEY = "dev-secret-change-me-in-production"


def derive_secret(device_id: str, version: int = 1) -> str:
    """Та же формула, что device_secret() на сервере."""
    secret_key = os.environ.get("SECRET_KEY", DEV_SECRET_KEY)
    raw = f"locker-device:{device_id}:{version}"
    return hmac.new(secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()


class Locker:
    """Программная копия контроллера: подпись, nonce, разбор ответов."""

    def __init__(self, base: str, device_id: str, secret: str):
        self.base = base.rstrip("/")
        self.device_id = device_id
        self.secret = secret
        self.http = httpx.Client(base_url=self.base, timeout=40)

    def _signed(self, payload: str) -> dict:
        ts = int(time.time())
        nonce = secrets.token_hex(8)
        message = f"{self.device_id}|{ts}|{nonce}|{payload}"
        sig = hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return {"ts": ts, "nonce": nonce, "sig": sig}

    def _url(self, action: str) -> str:
        return f"/api/device/lockers/{self.device_id}/{action}"

    def scan(self, code: str) -> dict:
        r = self.http.post(self._url("scan"), json={"code": code, **self._signed(code)})
        r.raise_for_status()
        result = r.json()
        if result["action"] == "open":
            print(f"🔓 Ячейка №{result['cell']} открыта (заказ {result.get('order', '')})")
        else:
            print(f"⛔ Отказ: {result.get('message', result.get('reason'))}")
        return result

    def event(self, kind: str, cell: int | None, empty: bool | None = None) -> dict:
        body = {"type": kind, "cell": cell, **self._signed(f"{kind}:{cell if cell is not None else ''}")}
        if empty is not None:
            body["empty"] = empty
        r = self.http.post(self._url("events"), json=body)
        r.raise_for_status()
        result = r.json()
        label = {"door_opened": "дверь открыта", "door_closed": "дверь закрыта",
                 "cell_empty": "датчик: ячейка пуста", "door_jammed": "дверь заклинило"}.get(kind, kind)
        print(f"   ячейка №{cell}: {label}" + (f" → заказ {result['issued']} выдан" if result.get("issued") else ""))
        return result

    def heartbeat(self, firmware: str = "sim-1.0") -> None:
        r = self.http.post(self._url("heartbeat"), json={"firmware": firmware, **self._signed("heartbeat")})
        r.raise_for_status()
        print("💓 heartbeat принят — постамат «онлайн» в кабинете столовой")

    def commands(self, wait: int = 25) -> list[dict]:
        r = self.http.get(self._url("commands"), params={**self._signed("commands"), "wait": wait})
        r.raise_for_status()
        return r.json()["commands"]

    def listen(self) -> None:
        print("Жду команды сервера (long-polling, Ctrl+C — выход)…")
        while True:
            for cmd in self.commands():
                reason = {"load": "загрузить заказ", "unload": "забрать заказ",
                          "service": "обслуживание"}.get(cmd["reason"], cmd["reason"])
                print(f"🔓 Команда: открыть ячейку №{cmd['cell']} ({reason})")
                time.sleep(1)
                self.event("door_closed", cmd["cell"])


# --------------------------------------------------------------------------- #
#  Сквозной сценарий для показа
# --------------------------------------------------------------------------- #
def demo(locker: Locker) -> None:
    api = httpx.Client(base_url=locker.base, timeout=20)

    def login(email: str, password: str) -> dict:
        r = api.post("/api/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['token']}"}

    student = login("student@rosbiotech.ru", "student")
    kitchen = login("operator@rosbiotech.ru", "operator")
    locker.heartbeat()

    # ближайший день, на который ещё открыт приём в перемену с постаматом
    slot, on = None, None
    for offset in range(0, 7):
        campus = datetime.now(UTC) + timedelta(hours=int(os.environ.get("TZ_OFFSET_HOURS", 3)))
        day = (campus.date() + timedelta(days=offset)).isoformat()
        for s in api.get(f"/api/slots?date={day}").json():
            if s["is_available"] and "остамат" in s["point"]:
                slot, on = s, day
                break
        if slot:
            break
    if slot is None:
        sys.exit("Нет открытых перемен с выдачей в постамате")

    dish = next(d for d in api.get("/api/dishes").json() if d["stock_qty"] > 0)
    api.delete("/api/cart", headers=student)
    api.post("/api/cart/items", json={"dish_id": dish["id"], "qty": 1}, headers=student).raise_for_status()
    order = api.post("/api/orders", json={"slot_id": slot["id"], "pickup_date": on}, headers=student).json()
    api.post(f"/api/orders/{order['id']}/pay", json={"method": "sbp"}, headers=student).raise_for_status()
    print(f"1. Студент оформил и оплатил {order['number']}: {dish['name']}, {slot['label']} ({on})")

    api.patch(f"/api/operator/orders/{order['id']}/status", json={"status": "ready"}, headers=kitchen)
    placed = api.post(f"/api/operator/orders/{order['id']}/place", json={}, headers=kitchen)
    placed.raise_for_status()
    cell = placed.json()["cell_number"]
    print(f"2. Кухня: «Собран» → «Положен в ячейку» — сервер выдал ячейку №{cell}")

    for cmd in locker.commands(wait=2):
        print(f"3. Постамат получил команду: открыть ячейку №{cmd['cell']} ({cmd['reason']})")
    locker.event("door_closed", cell)

    token = api.post(f"/api/orders/{order['id']}/pickup-token", headers=student).json()
    print(f"4. У студента на экране одноразовый QR {token['code'][:18]}… и PIN {token['pin']} "
          f"(действует {token['ttl_seconds']} с)")

    print("5. Студент подносит QR к сканеру:")
    locker.scan(token["code"])
    print("   Повторный скан того же кода (скриншот у друга):")
    locker.scan(token["code"])

    locker.event("door_opened", cell)
    locker.event("door_closed", cell)
    status = api.get(f"/api/orders/{order['id']}", headers=student).json()["status_label"]
    print(f"6. В приложении студента: «{status}»")


def main() -> None:
    parser = argparse.ArgumentParser(description="Эмулятор постамата РосПит")
    parser.add_argument("--base", default=DEFAULT_BASE, help="адрес сервера")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="device_id постамата")
    parser.add_argument("--secret", default=os.environ.get("LOCKER_SECRET"), help="секрет устройства")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo")
    sub.add_parser("listen")
    sub.add_parser("heartbeat")
    sub.add_parser("secret")
    p = sub.add_parser("scan")
    p.add_argument("code")
    p = sub.add_parser("pin")
    p.add_argument("pin")
    p = sub.add_parser("event")
    p.add_argument("type", choices=["door_opened", "door_closed", "cell_empty", "door_jammed"])
    p.add_argument("cell", type=int)
    args = parser.parse_args()

    secret = args.secret or derive_secret(args.device)
    if args.cmd == "secret":
        print(secret)
        return
    locker = Locker(args.base, args.device, secret)
    if args.cmd == "demo":
        demo(locker)
    elif args.cmd == "listen":
        try:
            locker.listen()
        except KeyboardInterrupt:
            pass
    elif args.cmd == "heartbeat":
        locker.heartbeat()
    elif args.cmd in ("scan", "pin"):
        locker.scan(args.code if args.cmd == "scan" else args.pin)
    elif args.cmd == "event":
        locker.event(args.type, args.cell)


if __name__ == "__main__":
    main()
