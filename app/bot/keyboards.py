from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def get_deal_keyboard(ad_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Купил", callback_data=f"deal:bought:{ad_id}")
    builder.button(text="👀 Интересно", callback_data=f"deal:interesting:{ad_id}")
    builder.button(text="❌ Мусор", callback_data=f"deal:trash:{ad_id}")
    builder.button(text="💰 Продал", callback_data=f"deal:sold:{ad_id}")
    builder.button(text="🔄 Пересканировать", callback_data=f"deal:rescan:{ad_id}")
    builder.button(text="💬 Шаблон", callback_data=f"deal:reply:{ad_id}")
    builder.button(text="✉️ OLX", callback_data=f"deal:send_olx:{ad_id}")
    builder.adjust(2, 2, 1, 2)
    return builder.as_markup()


def get_rescan_keyboard(ad_id: int, old_msg_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Купил", callback_data=f"deal:bought:{ad_id}")
    builder.button(text="👀 Интересно", callback_data=f"deal:interesting:{ad_id}")
    builder.button(text="❌ Мусор", callback_data=f"deal:trash:{ad_id}")
    builder.button(text="💰 Продал", callback_data=f"deal:sold:{ad_id}")
    builder.button(text="🔄 Ещё раз", callback_data=f"deal:rescan:{ad_id}")
    builder.adjust(2, 2, 1)
    return builder.as_markup()
