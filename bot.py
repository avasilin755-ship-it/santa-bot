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

RESET_CODE = os.getenv("RESET_CODE")  # если задан — /reset КОД доступен

EVENT_TITLE = "🎄 Тайный Санта 2025"
EVENT_DATE = "25.12.2025"
BUDGET = "200 ₽"
COUNTDOWN_SECONDS = 10

PARTICIPANTS: List[str] = [
    "Алёна",
    "Ирина",
    "Мария",
    "Марина",
    "Юлия",
]

DATA_FILE = "santa_state.json"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


# ================== ХРАНЕНИЕ ==================
def load_state() -> Dict:
    if not os.path.exists(DATA_FILE):
        return {
            "chosen": {},          # user_id(str) -> name(str)
            "pairs": {},           # giver_name -> receiver_name
            "drawn_at": None,      # timestamp
            "draw_in_progress": False,
            "ui": {}               # user_id(str) -> {"chat_id": int, "message_id": int}
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # на всякий случай докидываем ключи
    data.setdefault("chosen", {})
    data.setdefault("pairs", {})
    data.setdefault("drawn_at", None)
    data.setdefault("draw_in_progress", False)
    data.setdefault("ui", {})
    return data


def save_state(state: Dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def chosen_name_of(user_id: int, state: Dict) -> Optional[str]:
    return state.get("chosen", {}).get(str(user_id))


def name_taken(name: str, state: Dict) -> bool:
    return name in state.get("chosen", {}).values()


def all_registered(state: Dict) -> bool:
    chosen_names = set(state.get("chosen", {}).values())
    return len(chosen_names) == len(PARTICIPANTS)


# ================== UI / ТЕКСТЫ ==================
def header() -> str:
    return (
        f"❄️ <b>{EVENT_TITLE}</b> ❄️\n"
        f"📅 Дата: <b>{EVENT_DATE}</b>\n"
        f"💰 Лимит: <b>{BUDGET}</b>\n"
        "━━━━━━━━━━━━━━━━━━"
    )


def progress_line(state: Dict) -> str:
    got = len(set(state.get("chosen", {}).values()))
    total = len(PARTICIPANTS)
    left = total - got
    if left <= 0:
        return f"✅ Все готовы: <b>{got}/{total}</b>"
    return f"⏳ Готовность: <b>{got}/{total}</b> (осталось: <b>{left}</b>)"


def panel_text_for(user_id: int, state: Dict) -> str:
    my = chosen_name_of(user_id, state)
    if state.get("pairs"):
        t = (
            f"{header()}\n\n"
            "🎉 <b>Жеребьёвка уже проведена!</b>\n"
            "Нажми кнопку ниже, чтобы увидеть <b>только свою</b> пару.\n\n"
            "☃️ Не раскрывай свою пару другим 🙂\n"
        )
        if my:
            t += f"\n👤 Ты: <b>{my}</b>"
        else:
            t += "\n👤 Ты не выбрал себя до жеребьёвки. Напиши /start в самом начале следующей игры."
        return t

    t = (
        f"{header()}\n\n"
        "🎅 Правила:\n"
        "1) Выбери, <b>кто ты</b>, кнопкой ниже\n"
        "2) Когда все выберут себя — появится кнопка <b>🎲 Жеребьёвка</b>\n"
        "3) После выбора <b>нельзя поменять имя</b>\n"
        "4) После жеребьёвки каждый увидит <b>только свою</b> пару\n\n"
        f"{progress_line(state)}\n"
    )
    if my:
        t += f"\n👤 Ты уже выбран как: <b>{my}</b> ✅"
    else:
        t += "\n👤 Ты ещё не выбран."
    return t


def kb_choose_name(user_id: int, state: Dict) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)

    my = chosen_name_of(user_id, state)
    for name in PARTICIPANTS:
        taken = name_taken(name, state)
        mark = " ✅" if taken else ""
        # если имя занято НЕ этим пользователем — делаем кнопку "недоступной" через callback, но внешне показываем
        kb.add(types.InlineKeyboardButton(f"🎁 {name}{mark}", callback_data=f"pick:{name}"))

    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))

    # Кнопка жеребьёвки появляется только когда все выбрали себя и жеребьёвка ещё не проведена
    if all_registered(state) and not state.get("pairs") and not state.get("draw_in_progress"):
        kb.add(types.InlineKeyboardButton("🎲 Жеребьёвка", callback_data="draw"))

    # если пользователь уже выбрал себя — можно показать "ожидаем"
    if my and (not all_registered(state)) and (not state.get("pairs")):
        kb.add(types.InlineKeyboardButton("⏳ Ждём остальных", callback_data="noop"))

    return kb


def kb_after_draw() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("🎁 Моя пара", callback_data="my_pair"))
    kb.add(types.InlineKeyboardButton("👤 Мой профиль", callback_data="me"))
    return kb


def safe_edit(chat_id: int, message_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup]):
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return True
    except Exception:
        return False


def broadcast_refresh(state: Dict):
    """
    Обновляет панели всем пользователям, которые когда-либо нажимали /start.
    Для маленького списка (5 участников) — безопасно.
    """
    ui = state.get("ui", {})
    to_delete = []
    for uid_str, meta in ui.items():
        try:
            uid = int(uid_str)
            chat_id = int(meta["chat_id"])
            msg_id = int(meta["message_id"])
        except Exception:
            to_delete.append(uid_str)
            continue

        if state.get("pairs"):
            ok = safe_edit(chat_id, msg_id, panel_text_for(uid, state), kb_after_draw())
        else:
            ok = safe_edit(chat_id, msg_id, panel_text_for(uid, state), kb_choose_name(uid, state))

        # если не получилось — скорее всего сообщение удалили/чат недоступен
        if not ok:
            to_delete.append(uid_str)

        time.sleep(0.1)  # маленькая пауза против лимитов

    for k in to_delete:
        ui.pop(k, None)

    state["ui"] = ui
    save_state(state)


# ================== ЖЕРЕБЬЁВКА ==================
def build_pairs(names: List[str]) -> Dict[str, str]:
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

    # отправляем панель и сохраняем message_id, чтобы потом редактировать всем
    text = panel_text_for(message.from_user.id, state)
    if state.get("pairs"):
        sent = bot.send_message(message.chat.id, text, reply_markup=kb_after_draw())
    else:
        sent = bot.send_message(message.chat.id, text, reply_markup=kb_choose_name(message.from_user.id, state))

    state["ui"][str(message.from_user.id)] = {"chat_id": message.chat.id, "message_id": sent.message_id}
    save_state(state)

    # сразу обновим всем (например, чтобы у других появились ✅, если они открыли бота позже)
    broadcast_refresh(load_state())


# ================== /reset ==================
@bot.message_handler(commands=["reset"])
def reset(message: types.Message):
    if not RESET_CODE:
        bot.send_message(message.chat.id, "♻️ Сброс отключён (на сервере не задан RESET_CODE).")
        return

    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2 or parts[1] != RESET_CODE:
        bot.send_message(message.chat.id, "♻️ Нужен код. Формат: <code>/reset КОД</code>")
        return

    state = {"chosen": {}, "pairs": {}, "drawn_at": None, "draw_in_progress": False, "ui": load_state().get("ui", {})}
    save_state(state)
    bot.send_message(message.chat.id, "♻️ Игра сброшена! Можно начинать заново 🎄")
    broadcast_refresh(load_state())


# ================== CALLBACKS ==================
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call: types.CallbackQuery):
    state = load_state()
    uid = call.from_user.id

    if call.data == "noop":
        bot.answer_callback_query(call.id, "Ждём 🙂")
        return

    if call.data == "me":
        bot.answer_callback_query(call.id, "Профиль")
        # просто обновим панель этому пользователю
        if state.get("pairs"):
            bot.send_message(call.message.chat.id, panel_text_for(uid, state), reply_markup=kb_after_draw())
        else:
            bot.send_message(call.message.chat.id, panel_text_for(uid, state), reply_markup=kb_choose_name(uid, state))
        return

    # выбор имени
    if call.data.startswith("pick:"):
        name = call.data.split(":", 1)[1]

        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвка уже была. Смена недоступна.", show_alert=True)
            return

        if state.get("draw_in_progress"):
            bot.answer_callback_query(call.id, "Жеребьёвка запускается. Подожди.", show_alert=True)
            return

        already = chosen_name_of(uid, state)
        if already:
            # ВАЖНО: запрет смены
            bot.answer_callback_query(call.id, "Ты уже подтвердил себя. Менять нельзя ✅", show_alert=True)
            return

        # если имя занято другим
        for k, v in state.get("chosen", {}).items():
            if v == name and k != str(uid):
                bot.answer_callback_query(call.id, "Это имя уже заняли ✅", show_alert=True)
                return

        state.setdefault("chosen", {})[str(uid)] = name
        save_state(state)

        bot.answer_callback_query(call.id, f"Готово: {name} ✅")

        # обновляем панели всем
        broadcast_refresh(load_state())
        return

    # жеребьёвка
    if call.data == "draw":
        if state.get("pairs"):
            bot.answer_callback_query(call.id, "Уже проведено.", show_alert=True)
            return

        if state.get("draw_in_progress"):
            bot.answer_callback_query(call.id, "Уже запускается.", show_alert=True)
            return

        if not all_registered(state):
            bot.answer_callback_query(call.id, "Ещё не все готовы.", show_alert=True)
            return

        # блокируем и обновляем всем (чтобы кнопка draw исчезла, если надо)
        state["draw_in_progress"] = True
        save_state(state)
        broadcast_refresh(load_state())

        bot.answer_callback_query(call.id, "Запускаю 🎲")

        # обратный отсчёт в сообщении, которое нажали (может быть не панель)
        msg = bot.send_message(call.message.chat.id, f"🎄 Жеребьёвка через <b>{COUNTDOWN_SECONDS}</b>…")

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
            pairs = build_pairs(PARTICIPANTS[:])
            state = load_state()
            state["pairs"] = pairs
            state["drawn_at"] = int(time.time())
            save_state(state)

            sent = 0
            failed = 0

            # рассылаем только тем, кто выбрал себя
            for user_id_str, my_name in state.get("chosen", {}).items():
                user_id = int(user_id_str)
                receiver_name = pairs.get(my_name)

                try:
                    bot.send_message(
                        user_id,
                        f"{header()}\n\n"
                        "🎁 <b>Твоя пара готова!</b>\n\n"
                        f"Ты даришь: <b>{receiver_name}</b>\n\n"
                        "✨ С наступающим! Пусть подарок будет классным 🎄\n"
                        "🤫 Пару не раскрываем 🙂",
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
                    "Каждому отправил пару в личку.\n"
                    f"📬 Отправлено: <b>{sent}</b>\n"
                    f"⚠️ Не доставлено: <b>{failed}</b>\n\n"
                    "Нажми «🎁 Моя пара»."
                ),
                parse_mode="HTML"
            )

        finally:
            state = load_state()
            state["draw_in_progress"] = False
            save_state(state)
            broadcast_refresh(load_state())

        return

    # показать свою пару
    if call.data == "my_pair":
        state = load_state()
        if not state.get("pairs"):
            bot.answer_callback_query(call.id, "Жеребьёвки ещё не было.", show_alert=True)
            return

        my = chosen_name_of(uid, state)
        if not my:
            bot.answer_callback_query(call.id, "Ты не выбирал себя.", show_alert=True)
            return

        receiver = state["pairs"].get(my)
        bot.answer_callback_query(call.id, "Готово 🎁")
        bot.send_message(
            call.message.chat.id,
            f"{header()}\n\n"
            "🎁 <b>Твоя пара</b>\n\n"
            f"Ты даришь: <b>{receiver}</b>\n\n"
            "🎄 Удачи! И классного настроения 😊",
            reply_markup=kb_after_draw()
        )
        return

    bot.answer_callback_query(call.id, "Неизвестная кнопка.")


if __name__ == "__main__":
    print("Santa bot started...")
    bot.infinity_polling(skip_pending=True)
