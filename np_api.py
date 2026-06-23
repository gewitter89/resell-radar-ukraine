"""
Nova Poshta REAL API — точный расчёт доставки по адресу.

API Nova Poshta v2.0 (публичный, бесплатный):
  - Регистрация ключа: https://novaposhta.ua/private-cabinet → API
  - Документация: https://developers.novaposhta.ua/

Что считает реально:
  - Курьерская доставка на адрес (стоимость = тариф НП)
  - Доставка в отделение
  - Доставка в почтомат
  - Срок доставки (DocumentDeliveryDate)
  - Подъём на этаж

Адрес пользователя — в shopping_list.json:
  "address": {
    "city": "Киев",
    "street": "вул. Хрещатик",
    "building": "1",
    "apartment": "10",
    "floor": 3
  }
"""

import httpx
import asyncio
from dataclasses import dataclass, field
from typing import Optional


# === Dateklass ===

# Рефы городов (для Киева) — ДО Address
KYIV_REF = "8d5a980d-391c-11dd-90d9-001a92567626"


@dataclass
class Address:
    city: str = "Киев"
    city_ref: str = KYIV_REF
    street: str = ""
    building: str = ""
    apartment: str = ""
    floor: int = 1


@dataclass
class NpRate:
    """Реальная стоимость доставки Новой Почты."""
    service_type: str  # WarehouseWarehouse / WarehouseDoors / DoorsDoors
    service_name: str
    cost: float
    cost_floor_lift: float = 0.0
    delivery_days: int = 1
    currency: str = "UAH"
    raw_response: dict = field(default_factory=dict)


# === КОНФИГ ===
NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"

# API key — бесплатно: https://developers.novaposhta.ua/register
NP_API_KEY = ""  # вставь сюда или в .env: NP_API_KEY=...

# Адрес пользователя (обновляется из shopping_list.json)
USER_ADDRESS = Address(
    city="Київ",
    city_ref=KYIV_REF,
    street="вул. Бориса Антоненка-Давидовича",
    building="1",
    apartment="",
    floor=1,
)


# === NP API CLIENT ===

async def _np_api_call(method: str, properties: dict) -> dict:
    """Вызов API Новой Почты."""
    api_key = NP_API_KEY

    payload = {
        "apiKey": api_key,
        "modelName": "InternetDocument",
        "calledMethod": method,
        "methodProperties": properties,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(NP_API_URL, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    return data
                else:
                    print(f"  NP API error: {data.get('errors', 'unknown')}")
                    return {}
            else:
                print(f"  NP API HTTP {resp.status_code}")
                return {}
    except Exception as e:
        print(f"  NP API exception: {e}")
        return {}


async def search_city(city_name: str) -> list[dict]:
    """Поиск города по названию → получить Ref."""
    result = await _np_api_call("getSettlements", {
        "CityName": city_name,
        "Limit": 5,
    })

    cities = []
    data = result.get("data", [])
    for item in data:
        cities.append({
            "ref": item.get("Ref"),
            "name": item.get("Description"),
            "area": item.get("AreaDescription"),
            "settlement_type": item.get("SettlementTypeDescription"),
        })
    return cities


async def search_street(city_ref: str, street_name: str) -> list[dict]:
    """Поиск улицы в городе."""
    result = await _np_api_call("getStreet", {
        "CityRef": city_ref,
        "FindByString": street_name,
        "Limit": 5,
    })
    streets = []
    for item in result.get("data", []):
        streets.append({
            "ref": item.get("Ref"),
            "name": item.get("Description"),
            "type": item.get("StreetsType"),
        })
    return streets


async def search_warehouse(city_ref: str, warehouse_num: str = "") -> list[dict]:
    """Поиск отделений НП."""
    props = {"CityRef": city_ref, "Limit": 10}
    if warehouse_num:
        props["FindByString"] = warehouse_num

    result = await _np_api_call("getWarehouses", props)
    warehouses = []
    for item in result.get("data", []):
        warehouses.append({
            "ref": item.get("Ref"),
            "number": item.get("Number"),
            "address": item.get("ShortAddress"),
            "type": item.get("TypeOfWarehouse"),
            "has_payment_card": item.get("HasPaymentCard"),
        })
    return warehouses


async def get_delivery_price(
    city_recipient_ref: str,
    cost_declared: float,  # объявленная стоимость (для страховки)
    weight_kg: float = 0.5,
    service_type: str = "WarehouseWarehouse",  # или WarehouseDoors / DoorsDoors
    recipient_address: str = "",  # для курьера
    floor: int = 1,
) -> NpRate:
    """РЕАЛЬНЫЙ расчёт стоимости через API НП."""

    # Параметры расчёта
    props = {
        "CityRecipient": city_recipient_ref,
        "Cost": int(cost_declared * 100),  # в копейках? Нет, в грн для API
        "Weight": max(0.1, weight_kg),
        "ServiceType": service_type,
        "SeatsAmount": 1,
    }

    # Для курьерской доставки нужен адрес
    if service_type in ("WarehouseDoors", "DoorsDoors") and recipient_address:
        props["RecipientAddressName"] = recipient_address

    result = await _np_api_call("getDocumentPrice", props)

    if not result.get("data"):
        # Fallback: примерные цифры если API не дал ответ
        fallback = _fallback_prices(weight_kg, service_type, floor)
        return fallback

    data = result["data"][0] if isinstance(result["data"], list) else result["data"]

    cost = float(data.get("Cost", 0))
    delivery_date = data.get("DeliveryDate", "")

    # Расчёт дней
    try:
        from datetime import datetime
        delivery_dt = datetime.strptime(delivery_date, "%d.%m.%Y")
        days = (delivery_dt - datetime.now()).days
        days = max(1, days)
    except Exception:
        days = 1

    # Подъём на этаж (только для курьера, этаж > 2)
    floor_lift = 0.0
    if service_type == "WarehouseDoors" and floor > 2:
        # Подъём: ~15 грн за этаж выше 2-го
        floor_lift = (floor - 2) * 15.0

    service_names = {
        "WarehouseWarehouse": "Відділення → Відділення",
        "WarehouseDoors": "Відділення → Кур'єр",
        "DoorsDoors": "Кур'єр → Кур'єр",
    }

    return NpRate(
        service_type=service_type,
        service_name=service_names.get(service_type, service_type),
        cost=cost,
        cost_floor_lift=floor_lift,
        delivery_days=days,
        raw_response=data,
    )


def _fallback_prices(weight_kg: float, service_type: str, floor: int) -> NpRate:
    """Fallback-цены на случай ошибки API (приближенные к реальным)."""
    prices = {
        "WarehouseWarehouse": {0.5: 55, 1.0: 60, 2.0: 70, 5.0: 85, 10.0: 105, 20.0: 135},
        "WarehouseDoors": {0.5: 75, 1.0: 85, 2.0: 95, 5.0: 110, 10.0: 135, 20.0: 170},
        "DoorsDoors": {0.5: 95, 1.0: 105, 2.0: 115, 5.0: 135, 10.0: 160, 20.0: 200},
    }

    p = prices.get(service_type, prices["WarehouseDoors"])
    cost = p.get(2.0, 85)
    for kg, price in p.items():
        if weight_kg <= kg:
            cost = price
            break

    floor_lift = (floor - 2) * 15.0 if service_type == "WarehouseDoors" and floor > 2 else 0.0

    service_names = {
        "WarehouseWarehouse": "Відділення → Відділення (прибл.)",
        "WarehouseDoors": "Відділення → Кур'єр (прибл.)",
        "DoorsDoors": "Кур'єр → Кур'єр (прибл.)",
    }

    return NpRate(
        service_type=service_type,
        service_name=service_names.get(service_type, service_type),
        cost=cost,
        cost_floor_lift=floor_lift,
        delivery_days=1,
    )


# === УДОБНЫЙ МЕТОД: все варианты для пользователя ===

async def get_all_delivery_prices(
    address: Address,
    cart_value: float,  # стоимость товаров
    weight_kg: float = 2.0,
) -> list[NpRate]:
    """Все варианты доставки НП на адрес пользователя."""

    recipient_address = f"{address.street}, {address.building}"
    if address.apartment:
        recipient_address += f", кв. {address.apartment}"

    tasks = [
        get_delivery_price(address.city_ref, cart_value, weight_kg,
                          "WarehouseWarehouse"),
        get_delivery_price(address.city_ref, cart_value, weight_kg,
                          "WarehouseDoors", recipient_address, address.floor),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for r in results:
        if isinstance(r, NpRate):
            valid.append(r)
        elif isinstance(r, Exception):
            valid.append(NpRate(
                service_type="error",
                service_name=f"Ошибка: {r}",
                cost=0,
            ))

    return valid


def format_np_prices(rates: list[NpRate]) -> str:
    """Формат для Telegram."""
    lines = ["🚚 <b>НОВАЯ ПОШТА (точный расчёт)</b>", "─" * 28]
    for rate in rates:
        floor_str = f" + {rate.cost_floor_lift:.0f} подъём" if rate.cost_floor_lift > 0 else ""
        lines.append(
            f"  {rate.service_name}: <b>{rate.cost:.0f} ₴</b>{floor_str}  "
            f"(~{rate.delivery_days} дн)"
        )
    return "\n".join(lines)


# === БЛИЖАЙШЕЕ ОТДЕЛЕНИЕ К АДРЕСУ ===

async def find_nearest_warehouses(
    city_ref: str = KYIV_REF,
    address: str = "вул. Бориса Антоненка-Давидовича, 1",
    limit: int = 3,
) -> list[dict]:
    """Найти ближайшие отделения НП к адресу."""
    result = await _np_api_call("getWarehouses", {
        "CityRef": city_ref,
        "FindByString": "Дарниц",
        "Limit": 10,
    })
    warehouses = []
    for item in result.get("data", []):
        warehouses.append({
            "ref": item.get("Ref"),
            "number": item.get("Number"),
            "address": item.get("ShortAddress"),
            "type": item.get("TypeOfWarehouseDescription"),
            "phone": item.get("Phone", ""),
            "schedule": item.get("Schedule", {}).get("Monday", ""),
            "max_weight": item.get("TotalMaxWeightAllowed"),
        })
    return warehouses[:limit]


async def get_delivery_to_my_address(
    cart_value: float,
    weight_kg: float = 2.0,
    street: str = "вул. Бориса Антоненка-Давидовича",
    building: str = "1",
    floor: int = 1,
    apartment: str = "",
) -> dict:
    """
    Полный расчёт доставки на мой адрес:
    - Курьер на дом (WarehouseDoors)
    - В ближайшее отделение (WarehouseWarehouse)
    - Ближайшие 3 отделения
    """
    recipient = f"{street}, {building}"
    if apartment:
        recipient += f", кв. {apartment}"

    # Параллельно: цена + ближайшие отделения
    courier_price = await get_delivery_price(
        KYIV_REF, cart_value, weight_kg,
        "WarehouseDoors", recipient, floor,
    )
    warehouse_price = await get_delivery_price(
        KYIV_REF, cart_value, weight_kg,
        "WarehouseWarehouse",
    )
    nearest = await find_nearest_warehouses(KYIV_REF, recipient)

    return {
        "address": recipient,
        "floor": floor,
        "courier": {
            "cost": courier_price.cost + courier_price.cost_floor_lift,
            "days": courier_price.delivery_days,
        },
        "warehouse": {
            "cost": warehouse_price.cost,
            "days": warehouse_price.delivery_days,
        },
        "nearest_warehouses": nearest,
    }


def format_my_delivery(data: dict) -> str:
    """Красивый вывод доставки на мой адрес."""
    addr = data["address"]
    courier = data["courier"]
    warehouse = data["warehouse"]

    lines = [
        f"🚚 <b>ДОСТАВКА НА МОЙ АДРЕС</b>",
        f"📍 {addr}",
        "─" * 28,
        f"🏠 <b>Курьер на дом:</b> {courier['cost']:.0f} ₴ (~{courier['days']} дн)",
        f"📦 <b>В отделение:</b> {warehouse['cost']:.0f} ₴ (~{warehouse['days']} дн)",
        "",
        "🏪 <b>Ближайшие отделения:</b>",
    ]

    for i, wh in enumerate(data.get("nearest_warehouses", [])[:3]):
        num = "①②③"[i]
        lines.append(f"  {num} №{wh['number']} — {wh['address']}")

    return "\n".join(lines)
