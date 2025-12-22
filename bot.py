import os
import json
import time
import random
from typing import Dict, Optional

import telebot
from telebot import types

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env var is not set")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ===== НАСТРОЙКИ ИГРЫ =====
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"

# Список участников ЗДЕСЬ:
PARTICIPANTS = [
    "Алёна",
    "Ирина",
    "Мария",
    "Марина",
    "Юлия",
]

DATA_FILE = "santa_state.json"


# ===== ХРАНЕНИЕ =====
def load_state() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {
            "chosen": {},   # user_id(str) -> name(str)
            "pairs": {},    # giver_name -> receiver_name
            "drawn_at": None
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def chosen_name_of(user_id: int, state: Dict) -> Optional[str]:
    return state["chosen"].get(str(user_id))


def name_taken(name: str, state: Dict) -> bool:
    return name in state["chosen"].values()


# ===== КНОПКИ =====
def kb_choose_name(state: Dict) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for name in PARTICIPANTS:
        suffix = " ✅" if name_taken(name, state) else ""
        kb.add(types.InlineKeyboardButton(f"{name}{suffix}", callback_data=f"pick:{name}"))
    kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="draw"))
    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))
    return kb


def kb_after_draw() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🎁 Моя пара", callback_data="my_pair"))
    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))
    return kb


# ===== ЖЕРЕБЬЁВКА =====
def build_pairs(names: list[str]) -> Dict[str, str]:
    """Перестановка без самодарения. Работает при len(names) >= 2."""
    if len(names) < 2:
        raise ValueError("Нужно минимум 2 участника")
    receivers = names[:]
    for _ in range(100):
        random.shuffle(receivers)
        if all(g != r for g, r in zip(names, receivers)):
            return {g: r for g, r in zip(names, receivers)}
    raise RuntimeError("Не удалось составить пары, попробуйте ещё раз")


def all_registered(state: Dict) -> bool:
    return len(set(state["chosen"].values())) == len(PARTICIPANTS)


# ===== ХЭНДЛЕРЫ =====
@bot.message_handler(commands=["start", "help"])
def start(message: types.Message):
    state = load_state()
    my = chosen_name_of(message.from_user.id, state)

    text = (
        "🎅 <b>Тайный Санта</b>\n\n"
        f"📅 Дата: <b>{EVENT_DATE}</b>\n"
        f"💰 Бюджет: <b>{BUDGET}</b>\n\n"
        "1) Выбери, кто ты, из списка\n"
        "2) Когда все выберут себя — нажмите <b>🎲 Жеребьёвка</b>\n\n"
        "⚠️ Пары никому не показываются, каждый видит только свою."
    )
    if my:
        text += f"\n\n✅ Ты выбран как: <b>{my}</b>"

    # если жеребьёвка уже была — показываем быстрые кнопки
    if state.get("pairs"):
        bot.send_message(message.chat.id, text, reply_markup=kb_after_draw())
    else:
        bot.send_message(message.chat.id, text, reply_markup=kb_choose_name(state))


@bot.message_handler(commands=["reset"])
def reset(message: types.Message):
    # ВНИМАНИЕ: сейчас reset может сделать любой, потому что это личка.
    # Если хочешь — добавим "секретный пароль" для reset.
    state = {"chosen": {}, "pairs": {}, "drawn_at": None}
    save_state(state)
    bot.send_message(message.chat.id, "♻️ Сбросил игру. Можно выбирать себя заново.")


@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    state = load_state()
    uid = call.from_user.id

    # Показ профиля
    if call.data == "me":
        my = chosen_name_of(uid, state)
        if my:
            msg = f"👤 Ты: <b>{my}</b>\n"
        else:
            msg = "👤 Ты пока не выбран.\n"

        msg += f"\nУчастников выбрано: <b>{len(set(state['chosen'].values()))}/{len(PARTICIPANTS)}</b>"
        if state.get("pairs"):
            msg += "\n\n🎲 Жеребьёвка уже проведена."
            bot.answer_callback_query(call.id, "Профиль")
            bot.send_message(call.message.chat.id, msg, reply_markup=kb_after_draw())
        else:
            bot.answer_callback_query(call.id, "Профиль")
            bot.send_message(call.message.chat.id, msg, reply_markup=kb_choose_name(state))
        return

    # Выбор имени
    if call.data.startswith("pick:"):
        name = call.data.split(":", 1)[1]

        # если жеребьёвка уже прошла — выбор запрещаем
        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвка уже была. /reset чтобы начать заново.", show_alert=True)
            return

        # если это имя уже занято другим
        current_owner = None
        for k, v in state["chosen"].items():
            if v == name:
                current_owner = int(k)
                break

        if current_owner is not None and current_owner != uid:
            bot.answer_callback_query(call.id, "Это имя уже выбрал другой участник.", show_alert=True)
            return

        # если пользователь ранее выбрал другое имя — просто перезапишем
        state["chosen"][str(uid)] = name
        save_state(state)

        bot.answer_callback_query(call.id, f"Ты выбрал: {name}")
        bot.send_message(call.message.chat.id, f"✅ Теперь ты: <b>{name}</b>", reply_markup=kb_choose_name(state))
        return

    # Жеребьёвка
    if call.data == "draw":
        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвка уже проведена.", show_alert=True)
            bot.send_message(call.message.chat.id, "🎲 Жеребьёвка уже была. Нажми «🎁 Моя пара».", reply_markup=kb_after_draw())
            return

        if not all_registered(state):
            bot.answer_callback_query(call.id, "Ещё не все выбрали себя.", show_alert=True)
            bot.send_message(
                call.message.chat.id,
                f"⏳ Ещё не все выбрали себя: <b>{len(set(state['chosen'].values()))}/{len(PARTICIPANTS)}</b>\n"
                "Пусть каждый нажмёт /start и выберет себя.",
                reply_markup=kb_choose_name(state)
            )
            return

        # Таймер 10 секунд (без редактирования сообщений, просто считаем)
        bot.answer_callback_query(call.id, "Запускаю…")
        msg = bot.send_message(call.message.chat.id, "🎲 Жеребьёвка начнётся через <b>10</b> секунд…")
        for s in range(9, 0, -1):
            time.sleep(1)
            try:
                bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=msg.message_id,
                    text=f"🎲 Жеребьёвка начнётся через <b>{s}</b> секунд…",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # строим пары по именам
        names = PARTICIPANTS[:]  # фиксированный список
        pairs = build_pairs(names)
        state["pairs"] = pairs
        state["drawn_at"] = int(time.time())
        save_state(state)

        # рассылаем каждому его пару (по user_id -> chosen name)
        sent = 0
        failed = 0
        for user_id_str, my_name in state["chosen"].items():
            user_id = int(user_id_str)
            receiver_name = pairs.get(my_name)

            try:
                bot.send_message(
                    user_id,
                    "🎅 <b>Тайный Санта — твоя пара</b>\n\n"
                    f"Ты даришь: <b>{receiver_name}</b>\n"
                    f"📅 Дата: <b>{EVENT_DATE}</b>\n"
                    f"💰 Бюджет: <b>{BUDGET}</b>\n\n"
                    "Пожалуйста, не раскрывай пару 🙂",
                    reply_markup=kb_after_draw()
                )
                sent += 1
            except Exception:
                failed += 1

        bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=msg.message_id,
            text=(
                "✅ <b>Жеребьёвка проведена!</b>\n\n"
                "Каждому участнику отправил пару в личку.\n"
                f"Отправлено: <b>{sent}</b>, не доставлено: <b>{failed}</b>\n\n"
                "Нажми «🎁 Моя пара»."
            ),
            parse_mode="HTML"
        )
        return

    # Показать свою пару
    if call.data == "my_pair":
        if not state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвки ещё не было.", show_alert=True)
            bot.send_message(call.message.chat.id, "🎲 Жеребьёвки ещё не было. Сначала выберите себя и нажмите «Жеребьёвка».")
            return

        my = chosen_name_of(uid, state)
        if not my:
            bot.answer_callback_query(call.id, "Сначала выбери себя.", show_alert=True)
            bot.send_message(call.message.chat.id, "Сначала нажми /start и выбери, кто ты.")
            return

        receiver = state["pairs"].get(my)
        bot.answer_callback_query(call.id, "Твоя пара")
        bot.send_message(
            call.message.chat.id,
            "🎁 <b>Твоя пара</b>\n\n"
            f"Ты даришь: <b>{receiver}</b>\n"
            f"📅 Дата: <b>{EVENT_DATE}</b>\n"
            f"💰 Бюджет: <b>{BUDGET}</b>",
            reply_markup=kb_after_draw()
        )
        return

    bot.answer_callback_query(call.id, "Неизвестная кнопка.")


if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
