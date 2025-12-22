import os
import json
import time
import random
from typing import Dict, Optional, List

import telebot
from telebot import types

# ================== НАСТРОЙКИ ==================
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise RuntimeError("TOKEN env var is not set")

# Защита сброса: задай RESET_CODE в окружении (любой пароль).
# Если RESET_CODE не задан — /reset будет недоступен.
RESET_CODE = os.getenv("RESET_CODE")  # например: "santa2025"

EVENT_TITLE = "🎄 Тайный Санта 2025"
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"
COUNTDOWN_SECONDS = 10

# Участники (вшито в код)
PARTICIPANTS: List[str] = [
    "Алёна",
    "Ирина",
    "Мария",
    "Марина",
    "Юлия",
]

DATA_FILE = "santa_state.json"

# =================================================

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


# ================== ХРАНЕНИЕ ==================
def load_state() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {
            "chosen": {},          # user_id(str) -> name(str)
            "pairs": {},           # giver_name -> receiver_name
            "drawn_at": None,      # timestamp
            "draw_in_progress": False
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def chosen_name_of(user_id: int, state: Dict) -> Optional[str]:
    return state.get("chosen", {}).get(str(user_id))


def name_taken(name: str, state: Dict) -> bool:
    return name in state.get("chosen", {}).values()


def all_registered(state: Dict) -> bool:
    # все имена должны быть заняты (каждое ровно одним человеком)
    chosen_names = set(state.get("chosen", {}).values())
    return len(chosen_names) == len(PARTICIPANTS)


# ================== ДИЗАЙН / ТЕКСТЫ ==================
def header() -> str:
    return (
        f"❄️ <b>{EVENT_TITLE}</b> ❄️\n"
        f"📅 Дата: <b>{EVENT_DATE}</b>\n"
        f"💰 Лимит: <b>{BUDGET}</b>\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def pretty_progress(state: Dict) -> str:
    got = len(set(state.get("chosen", {}).values()))
    total = len(PARTICIPANTS)
    left = total - got
    if left <= 0:
        return f"✅ Все готовы: <b>{got}/{total}</b>"
    return f"⏳ Готовность: <b>{got}/{total}</b> (осталось: <b>{left}</b>)"


# ================== КНОПКИ ==================
def kb_choose_name(state: Dict) -> types.InlineKeyboardMarkup:
    """
    Пока не все выбрались — показываем только список имён + профиль.
    Когда все выбрались — добавляем кнопку жеребьёвки.
    """
    kb = types.InlineKeyboardMarkup(row_width=1)

    for name in PARTICIPANTS:
        mark = " ✅" if name_taken(name, state) else ""
        kb.add(types.InlineKeyboardButton(f"🎁 {name}{mark}", callback_data=f"pick:{name}"))

    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))

    if all_registered(state) and not state.get("pairs") and not state.get("draw_in_progress"):
        kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="draw"))

    return kb


def kb_after_draw() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🎁 Моя пара", callback_data="my_pair"))
    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))
    return kb


# ================== ЖЕРЕБЬЁВКА ==================
def build_pairs(names: List[str]) -> Dict[str, str]:
    """
    Делает перестановку без совпадений (никто не дарит сам себе).
    """
    if len(names) < 2:
        raise ValueError("Нужно минимум 2 участника")

    receivers = names[:]
    for _ in range(200):
        random.shuffle(receivers)
        if all(g != r for g, r in zip(names, receivers)):
            return {g: r for g, r in zip(names, receivers)}
    raise RuntimeError("Не удалось составить пары. Попробуйте ещё раз.")


# ================== /start ==================
@bot.message_handler(commands=["start", "help"])
def start(message: types.Message):
    state = load_state()
    my = chosen_name_of(message.from_user.id, state)

    if state.get("pairs"):
        text = (
            f"{header()}\n\n"
            "🎉 <b>Жеребьёвка уже проведена!</b>\n"
            "Нажми кнопку ниже, чтобы увидеть только свою пару.\n\n"
            "☃️ Не раскрывай свою пару другим — так интереснее!\n"
        )
        if my:
            text += f"\n👤 Ты: <b>{my}</b>"
        bot.send_message(message.chat.id, text, reply_markup=kb_after_draw())
        return

    text = (
        f"{header()}\n\n"
        "🎅 Правила простые:\n"
        "1) Выбери, <b>кто ты</b>, кнопкой ниже\n"
        "2) Когда все выберут себя — появится кнопка <b>🎲 Жеребьёвка</b>\n"
        "3) После жеребьёвки каждый увидит <b>только свою</b> пару\n\n"
        f"{pretty_progress(state)}\n"
    )
    if my:
        text += f"\n👤 Ты уже выбран как: <b>{my}</b> ✅"

    bot.send_message(message.chat.id, text, reply_markup=kb_choose_name(state))


# ================== /reset ==================
@bot.message_handler(commands=["reset"])
def reset(message: types.Message):
    if not RESET_CODE:
        bot.send_message(message.chat.id, "♻️ Сброс отключён (нет RESET_CODE на сервере).")
        return

    # ожидаем: /reset код
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2 or parts[1] != RESET_CODE:
        bot.send_message(
            message.chat.id,
            "♻️ Нужен код сброса.\n"
            "Формат: <code>/reset КОД</code>"
        )
        return

    state = {"chosen": {}, "pairs": {}, "drawn_at": None, "draw_in_progress": False}
    save_state(state)
    bot.send_message(message.chat.id, "♻️ Игра сброшена! Можно выбирать себя заново 🎄", reply_markup=kb_choose_name(state))


# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    state = load_state()
    uid = call.from_user.id

    # профиль
    if call.data == "me":
        my = chosen_name_of(uid, state)
        text = (
            f"{header()}\n\n"
            f"{pretty_progress(state)}\n\n"
        )
        if my:
            text += f"👤 Ты: <b>{my}</b>\n"
        else:
            text += "👤 Ты пока не выбран.\n"

        if state.get("pairs"):
            text += "\n🎁 Жеребьёвка уже была. Нажми «Моя пара»."
            bot.answer_callback_query(call.id, "Профиль")
            bot.send_message(call.message.chat.id, text, reply_markup=kb_after_draw())
        else:
            text += "\nВыбери себя из списка ниже:"
            bot.answer_callback_query(call.id, "Профиль")
            bot.send_message(call.message.chat.id, text, reply_markup=kb_choose_name(state))
        return

    # выбор имени
    if call.data.startswith("pick:"):
        name = call.data.split(":", 1)[1]

        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвка уже прошла. Смена недоступна.", show_alert=True)
            return
        if state.get("draw_in_progress"):
            bot.answer_callback_query(call.id, "Жеребьёвка запускается. Подожди.", show_alert=True)
            return

        # проверка занятости
        owner = None
        for k, v in state.get("chosen", {}).items():
            if v == name:
                owner = int(k)
                break
        if owner is not None and owner != uid:
            bot.answer_callback_query(call.id, "Это имя уже заняли.", show_alert=True)
            return

        # записываем выбор
        state.setdefault("chosen", {})[str(uid)] = name
        save_state(state)

        bot.answer_callback_query(call.id, f"Ты выбрал: {name}")
        msg = (
            f"{header()}\n\n"
            f"✅ Готово! Ты: <b>{name}</b>\n\n"
            f"{pretty_progress(state)}\n"
        )
        if all_registered(state):
            msg += "\n🎲 Теперь можно запускать жеребьёвку!"
        else:
            msg += "\n❄️ Ждём остальных…"

        bot.send_message(call.message.chat.id, msg, reply_markup=kb_choose_name(state))
        return

    # жеребьёвка
    if call.data == "draw":
        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Уже проведено.", show_alert=True)
            bot.send_message(call.message.chat.id, "🎲 Жеребьёвка уже была.", reply_markup=kb_after_draw())
            return

        if state.get("draw_in_progress"):
            bot.answer_callback_query(call.id, "Уже запускается.", show_alert=True)
            return

        if not all_registered(state):
            bot.answer_callback_query(call.id, "Ещё не все готовы.", show_alert=True)
            bot.send_message(
                call.message.chat.id,
                f"{header()}\n\n"
                "⏳ Пока не все выбрали себя.\n"
                f"{pretty_progress(state)}",
                reply_markup=kb_choose_name(state)
            )
            return

        # блокируем
        state["draw_in_progress"] = True
        save_state(state)

        bot.answer_callback_query(call.id, "Запускаю 🎲")
        msg = bot.send_message(call.message.chat.id, f"🎄 Начинаем через <b>{COUNTDOWN_SECONDS}</b>…", parse_mode="HTML")

        # обратный отсчёт
        for s in range(COUNTDOWN_SECONDS, 0, -1):
            try:
                bot.edit_message_text(
                    chat_id=msg.chat.id,
                    message_id=msg.message_id,
                    text=f"🎄 <b>Жеребьёвка</b> через <b>{s}</b>… ❄️",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            time.sleep(1)

        try:
            # строим пары по именам
            pairs = build_pairs(PARTICIPANTS[:])
            state["pairs"] = pairs
            state["drawn_at"] = int(time.time())
            save_state(state)

            # каждому — в личку
            sent = 0
            failed = 0
            for user_id_str, my_name in state.get("chosen", {}).items():
                user_id = int(user_id_str)
                receiver_name = pairs.get(my_name)

                try:
                    bot.send_message(
                        user_id,
                        f"{header()}\n\n"
                        "🎁 <b>Твоя пара готова!</b>\n\n"
                        f"Ты даришь: <b>{receiver_name}</b>\n\n"
                        "✨ Пусть подарок будет тёплым и добрым!\n"
                        "🤫 Пару не раскрываем 🙂",
                        reply_markup=kb_after_draw()
                    )
                    sent += 1
                except Exception:
                    failed += 1

            # итоговое сообщение
            bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                text=(
                    "✅ <b>Жеребьёвка проведена!</b>\n\n"
                    "Каждому отправил пару в личку.\n"
                    f"📬 Отправлено: <b>{sent}</b>\n"
                    f"⚠️ Не доставлено: <b>{failed}</b>\n\n"
                    "Нажми «🎁 Моя пара»."
                ),
                parse_mode="HTML"
            )

        finally:
            # снимаем блокировку
            state = load_state()
            state["draw_in_progress"] = False
            save_state(state)

        return

    # показать свою пару
    if call.data == "my_pair":
        state = load_state()
        if not state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвки ещё не было.", show_alert=True)
            bot.send_message(call.message.chat.id, "🎲 Сначала нужно провести жеребьёвку.", reply_markup=kb_choose_name(state))
            return

        my = chosen_name_of(uid, state)
        if not my:
            bot.answer_callback_query(call.id, "Сначала выбери себя.", show_alert=True)
            bot.send_message(call.message.chat.id, "Нажми /start и выбери, кто ты.", reply_markup=kb_choose_name(state))
            return

        receiver = state["pairs"].get(my)
        bot.answer_callback_query(call.id, "Готово 🎁")
        bot.send_message(
            call.message.chat.id,
            f"{header()}\n\n"
            "🎁 <b>Твоя пара</b>\n\n"
            f"Ты даришь: <b>{receiver}</b>\n\n"
            "🎄 Удачи! И хорошего настроения 😊",
            reply_markup=kb_after_draw()
        )
        return

    bot.answer_callback_query(call.id, "Неизвестная кнопка.")


# ================== RUN ==================
if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
