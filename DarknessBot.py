import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import uuid
import os
import json
import shutil
import threading
import requests
import glob

from dotenv import load_dotenv

load_dotenv()

bot = telebot.TeleBot(os.environ["BOT_TOKEN"])
crypto_token = os.environ["CRYPTO_PAY_TOKEN"]
api_crypto = f"https://pay.crypt.bot/api"
RUB_TO_USDT_RATE = 82

adminss = [int(x) for x in os.environ["ADMIN_IDS"].split(",")]
user_states = {}
tickets = {}
message_to_delete = {}
admin_messages = {}
active_payments = {}
broadcast_messages = {}

def create_invoice(asset, amount, description):
    url = f"{api_crypto}/createInvoice"
    headers = {
        "Crypto-Pay-API-Token": crypto_token
    }
    payload = {
        "asset": asset,
        "amount": amount,
        "description": description
    }
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    if data.get("ok"):
        return data["result"]
    else:
        raise Exception(data.get("error", "Error creating invoice"))

def get_invoice(invoice_id):
    url = f"{api_crypto}/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": crypto_token
    }
    params = {
        "invoice_ids": invoice_id
    }
    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    if data.get("ok") and data["result"]["items"]:
        return data["result"]["items"][0]
    else:
        return None

def get_invoice_status(invoice_id):
    url = f"{api_crypto}/getInvoices"
    headers = {
        "Crypto-Pay-API-Token": crypto_token
    }
    params = {
        "invoice_ids": invoice_id
    }
    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    if data.get("ok") and data["result"]["items"]:
        return data["result"]["items"][0]["status"]
    else:
        return None

def update_user_balance(user_id, amount):
    user_folder = f"Users/{user_id}"
    file_path = f"{user_folder}/{user_id}.json"
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        user_data['Balance'] = user_data.get('Balance', 0) + amount
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)
        return user_data['Balance']
    return 0

def get_user_data(user_id, username):
    if not os.path.exists("Users"):
        os.makedirs("Users")
    user_folder = f"Users/{user_id}"
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
        os.makedirs(os.path.join(user_folder, "Purchase"), exist_ok=True)
        os.makedirs(os.path.join(user_folder, "Reservation"), exist_ok=True)
    file_path = f"{user_folder}/{user_id}.json"
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        user_data = {
            "Username": username,
            "Id": user_id,
            "Purchases": 0,
            "Balance": 0
        }
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)
        return user_data

def count_users():
    user_folders = glob.glob("Users/*")
    return len(user_folders)

def cleanup_empty_products_and_categories():
    base_dir = "Cookies"
    if not os.path.exists(base_dir):
        return
    for category in os.listdir(base_dir):
        category_path = os.path.join(base_dir, category)
        if not os.path.isdir(category_path):
            continue
        for product_file in os.listdir(category_path):
            if product_file.endswith('.txt'):
                product_path = os.path.join(category_path, product_file)
                try:
                    with open(product_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    if len(lines) == 0:
                        os.remove(product_path)
                except Exception as e:
                    print(f"Ошибка при удалении пустого товара: {e}")
        if not any(fname.endswith('.txt') for fname in os.listdir(category_path)):
            try:
                shutil.rmtree(category_path)
            except Exception as e:
                print(f"Ошибка при удалении пустой категории: {e}")

def check_payment_status(invoice_id, user_id, amount_rub, chat_id):
    start_time = time.time()
    while time.time() - start_time < 300:
        try:
            status = get_invoice_status(invoice_id)
            if status == 'paid':
                new_balance = update_user_balance(user_id, amount_rub)
                amount_usdt = amount_rub / RUB_TO_USDT_RATE
                success_text = (
                    f"🎉Ваш баланс успешно пополнен!\n"
                    f"💸Сумма пополнения: {amount_rub} руб. ({amount_usdt:.2f} USDT)\n"
                    f"💰Текущий баланс: {new_balance} руб.\n"
                    f"🍪Удачных покупок!"
                )
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
                bot.send_message(chat_id, success_text, reply_markup=markup)
                if invoice_id in active_payments:
                    try:
                        bot.delete_message(chat_id, active_payments[invoice_id]["invoice_message_id"])
                    except:
                        pass
                    del active_payments[invoice_id]
                return
            elif status == 'expired':
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
                bot.send_message(chat_id, "⏳ Время оплаты истекло!", reply_markup=markup)
                if invoice_id in active_payments:
                    del active_payments[invoice_id]
                return
        except Exception as e:
            print(f"Ошибка при проверке платежа: {e}")
        time.sleep(5)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
    bot.send_message(chat_id, "⏳ Время оплаты истекло!", reply_markup=markup)
    if invoice_id in active_payments:
        try:
            bot.delete_message(chat_id, active_payments[invoice_id]["invoice_message_id"])
        except:
            pass
        del active_payments[invoice_id]

def show_menu(chat_id, message_id=None, user_name="", user_id=None):
    welcome_text = (
    f"👋 Привет {user_name}, ты попал в Darkness Cookie. Ниже приведена вся основная информация. Приятных покупок!\n\n"
    "✅ Тутор как заходить на куки: <a href='https://jumpshare.com/share/SxUf2YDLs3wdsnOlvWmD'>нажми здесь</a>\n\n"
    "✅ Тутор как пополнять кб: <a href='https://pastein.ru/t/RE5'>инструкция тут</a>\n\n"
    "📰 Наш ТГК: <a href='https://t.me/DarknessCookieChannel'>открыть канал</a>"
    )
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = [
        InlineKeyboardButton("🍪 Купить", callback_data="buy"),
        InlineKeyboardButton("🗂 Товары", callback_data="products"),
        InlineKeyboardButton("💭 Беседа", url="https://t.me/DarknessCookieChat"),
        InlineKeyboardButton("💼 Профиль", callback_data="profile"),
        InlineKeyboardButton("📞 Помощь", callback_data="help"),
        InlineKeyboardButton("📜 Правила", callback_data="rules")
    ]
    if user_id and user_id in adminss:
        buttons.append(InlineKeyboardButton("⚙️ Панель", callback_data="admin_panel"))
    markup.add(*buttons[:3])
    markup.add(*buttons[3:5], buttons[5])
    if len(buttons) > 6:
        markup.add(buttons[6])
    if message_id:
        try:
            bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=welcome_text,reply_markup=markup,parse_mode="HTML",disable_web_page_preview=True)
            return
        except:
            pass
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    get_user_data(user_id, user_name)
    if user_id in user_states:
        del user_states[user_id]
    show_menu(message.chat.id, user_name=user_name, user_id=user_id)

@bot.callback_query_handler(func=lambda call: call.data == "add_balance")
def handle_add_balance(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id 
    try:
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text="Отправьте сумму пополнения в рублях:",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile")
            )
        )
        user_states[user_id] = {
            "state": "waiting_for_amount",
            "request_message_id": message_id
        }
    except Exception as e:
        print(f"Ошибка при редактировании: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def handle_admin_panel(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    admin_text = f"Здравствуйте, админ: @{call.from_user.username}. Выберите функцию для использования:"
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = [
        InlineKeyboardButton("📩 Рассылка", callback_data="broadcast"),
        InlineKeyboardButton("⏰ Автозавоз", callback_data="auto_import"),
        InlineKeyboardButton("🍪 Завоз", callback_data="manual_import"),
        InlineKeyboardButton("➕ Пополнить баланс", callback_data="admin_add_balance"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")
    ]
    markup.add(buttons[0], buttons[1])
    markup.add(buttons[2], buttons[3])
    markup.add(buttons[4])
    try:
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=admin_text,reply_markup=markup)
        broadcast_messages[user_id] = {"admin_panel_id": message_id}
    except Exception as e:
        print(f"Ошибка админ-панели: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "auto_import")
def handle_auto_import_start(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    text = "Введите время для автозавоза товара. (Например, 0:20):"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    msg = bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    user_states[user_id] = {
        "state": "auto_import_time",
        "auto_import_msg_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "auto_import_time"
))
def handle_auto_import_time(message):
    import re, datetime
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["auto_import_msg_id"])
    except: pass
    time_str = message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", time_str):
        msg = bot.send_message(chat_id, "❌ Некорректный формат времени. Введите в формате 0:20:")
        user_states[user_id]["auto_import_msg_id"] = msg.message_id
        return
    try:
        dt = datetime.datetime.strptime(time_str, "%H:%M")
    except:
        msg = bot.send_message(chat_id, "❌ Некорректное время. Введите в формате 0:20:")
        user_states[user_id]["auto_import_msg_id"] = msg.message_id
        return
    msg = bot.send_message(chat_id, "📁 Пожалуйста, отправьте файл с товаром в формате .txt:")
    user_states[user_id] = {
        "state": "auto_import_file",
        "auto_time_str": time_str,
        "auto_time_dt": dt,
        "auto_import_file_msg_id": msg.message_id
    }

@bot.message_handler(content_types=['document'], func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "auto_import_file"
))
def handle_auto_import_file(message):
    import uuid
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["auto_import_file_msg_id"])
    except: pass
    if not message.document.file_name.endswith('.txt'):
        msg = bot.send_message(chat_id, "❌ Файл должен быть в формате .txt!")
        user_states[user_id]["auto_import_file_msg_id"] = msg.message_id
        return
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    temp_path = f"auto_temp_{user_id}_{uuid.uuid4().hex}.txt"
    with open(temp_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    msg = bot.send_message(chat_id, "Введите название категории товара:")
    user_states[user_id] = {
        "state": "auto_import_category",
        "auto_time_str": state["auto_time_str"],
        "auto_time_dt": state["auto_time_dt"],
        "auto_temp_file": temp_path,
        "auto_import_category_msg_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "auto_import_category"
))
def handle_auto_import_category(message):
    import os
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["auto_import_category_msg_id"])
    except: pass
    category_name = message.text.strip()
    auto_folder = os.path.join("AutoCookies", category_name)
    os.makedirs(auto_folder, exist_ok=True)
    msg = bot.send_message(chat_id, 'Введите название товара и цену (Например, "DarkCookies[Donate] - 2.5"):')
    user_states[user_id] = {
        "state": "auto_import_product_name",
        "auto_time_str": state["auto_time_str"],
        "auto_time_dt": state["auto_time_dt"],
        "auto_temp_file": state["auto_temp_file"],
        "auto_folder": auto_folder,
        "auto_category": category_name,
        "auto_import_product_msg_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "auto_import_product_name"
))
def handle_auto_import_product_name(message):
    import os, shutil
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["auto_import_product_msg_id"])
    except: pass
    product_name = message.text.strip()
    safe_name = "".join([c for c in product_name if c.isalnum() or c in " -_.[]"]).rstrip()
    final_path = os.path.join(state["auto_folder"], f"{safe_name}.txt")
    shutil.move(state["auto_temp_file"], final_path)
    msg = bot.send_message(chat_id, "✍️ Введите комментарий к завозу:")
    user_states[user_id] = {
        "state": "auto_import_comment",
        "auto_time_str": state["auto_time_str"],
        "auto_time_dt": state["auto_time_dt"],
        "auto_folder": state["auto_folder"],
        "auto_category": state["auto_category"],
        "auto_comment_msg_id": msg.message_id
    }

@bot.message_handler(content_types=['text', 'photo'], func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "auto_import_comment"
))
def handle_auto_import_comment(message):
    import datetime
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["auto_comment_msg_id"])
    except: pass
    comment_text = message.caption if message.caption else message.text if message.content_type == 'text' else ""
    comment_photo = message.photo[-1].file_id if message.photo else None
    user_states[user_id] = {
        "state": "auto_import_wait",
        "auto_time_str": state["auto_time_str"],
        "auto_time_dt": state["auto_time_dt"],
        "auto_folder": state["auto_folder"],
        "auto_category": state["auto_category"],
        "auto_comment_text": comment_text,
        "auto_comment_photo": comment_photo
    }
    text = f"⏰ Товар будет опубликован в магазин в {state['auto_time_str']} по МСК!"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    bot.send_message(chat_id, text, reply_markup=markup)
    import threading
    now = datetime.datetime.now()
    run_time = now.replace(hour=state["auto_time_dt"].hour, minute=state["auto_time_dt"].minute, second=0, microsecond=0)
    if run_time <= now:
        run_time += datetime.timedelta(days=1)
    delay = (run_time - now).total_seconds()
    threading.Thread(target=auto_publish, args=(user_id,), kwargs={'delay': delay}, daemon=True).start()

def auto_publish(user_id, delay=0):
    import shutil, os, time
    state = user_states.get(user_id)
    if not state: return
    time.sleep(delay)
    auto_folder = state["auto_folder"]
    category = state["auto_category"]
    cookies_path = os.path.join("Cookies", category)
    shutil.move(auto_folder, cookies_path)
    comment_text = state.get("auto_comment_text", "")
    comment_photo = state.get("auto_comment_photo")
    for user_folder in os.listdir("Users"):
        try:
            user_id_to_send = int(user_folder)
            if comment_photo:
                bot.send_photo(user_id_to_send, comment_photo, caption=comment_text or "")
            else:
                bot.send_message(user_id_to_send, comment_text or "")
        except Exception as e:
            print(f"Ошибка при рассылке комментария: {e}")
    user_states.pop(user_id, None)

@bot.callback_query_handler(func=lambda call: call.data == "admin_add_balance")
def handle_admin_add_balance_start(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    text = "Введите ID или Username для пополнения баланса:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    msg = bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    user_states[user_id] = {
        "state": "waiting_balance_target",
        "admin_add_balance_msg_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_balance_target"
))
def handle_admin_balance_target(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["admin_add_balance_msg_id"])
    except:
        pass
    input_text = message.text.strip()
    target_user_id = None
    username = None
    if input_text.isdigit():
        target_user_id = int(input_text)
    else:
        username = input_text.lstrip('@')
        found = False
        for user_folder in os.listdir("Users"):
            user_file = os.path.join("Users", user_folder, f"{user_folder}.json")
            if os.path.exists(user_file):
                with open(user_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get("Username", "").lower() == username.lower():
                    target_user_id = int(user_folder)
                    found = True
                    break
        if not found:
            bot.send_message(chat_id, "❌ Пользователь не найден.")
            del user_states[user_id]
            return
    text = "Введите сумму для пополнения баланса:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    msg = bot.send_message(chat_id, text, reply_markup=markup)
    user_states[user_id] = {
        "state": "waiting_balance_sum",
        "target_user_id": target_user_id,
        "balance_sum_msg_id": msg.message_id
    }

@bot.message_handler(
    func=lambda message: (
        message.from_user.id in user_states
        and isinstance(user_states[message.from_user.id], dict)
        and user_states[message.from_user.id].get("state") == "waiting_balance_sum"
    )
)
def handle_admin_balance_sum(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    if "balance_sum_msg_id" in state:
        try:
            bot.delete_message(chat_id, state["balance_sum_msg_id"])
        except:
            pass
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        error_msg = bot.send_message(chat_id, "❌ Вы ввели неправильную сумму. Пожалуйста, попробуйте снова:")
        user_states[user_id]["balance_sum_msg_id"] = error_msg.message_id
        return
    target_user_id = state["target_user_id"]
    update_user_balance(target_user_id, amount)
    user_file = os.path.join("Users", str(target_user_id), f"{target_user_id}.json")
    if os.path.exists(user_file):
        with open(user_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        uname = data.get("Username", f"ID {target_user_id}")
    else:
        uname = f"ID {target_user_id}"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    bot.send_message(chat_id, f"✅ Баланс пользователя @{uname} (ID: {target_user_id}) пополнен на {amount} руб.", reply_markup=markup)
    try:
        bot.send_message(target_user_id, f"✅ Ваш баланс был пополнен администратором на {amount} руб.")
    except:
        pass
    del user_states[user_id]

@bot.message_handler(
    func=lambda message: (
        message.from_user.id in user_states
        and isinstance(user_states[message.from_user.id], dict)
        and user_states[message.from_user.id].get("state") == "waiting_balance_sum"
    )
)
def handle_admin_balance_sum(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    if "balance_sum_msg_id" in state:
        try:
            bot.delete_message(chat_id, state["balance_sum_msg_id"])
        except:
            pass
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        error_msg = bot.send_message(chat_id, "❌ Вы ввели неправильную сумму. Пожалуйста, попробуйте снова:")
        user_states[user_id]["balance_sum_msg_id"] = error_msg.message_id
        return

def format_price(price):
    if price.is_integer():
        return int(price)
    return price

@bot.callback_query_handler(func=lambda call: call.data == "broadcast")
def handle_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    broadcast_text = "Введите сообщение для рассылки:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_admin_panel"))
    try:
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=broadcast_text,reply_markup=markup)
        broadcast_messages[user_id]["broadcast_request_id"] = message_id
        user_states[user_id] = {"state": "waiting_broadcast"}
    except Exception as e:
        print(f"Ошибка запроса рассылки: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_admin_panel")
def handle_back_to_admin_panel(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    handle_admin_panel(call)
    if user_id in user_states and user_states[user_id].get("state") == "waiting_broadcast":
        del user_states[user_id]

@bot.message_handler(content_types=['text', 'photo'], func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_broadcast"
))
def handle_broadcast_message(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id in broadcast_messages and "broadcast_request_id" in broadcast_messages[user_id]:
        try:
            bot.delete_message(chat_id, broadcast_messages[user_id]["broadcast_request_id"])
        except:
            pass
    total_users = count_users()
    success = 0
    failed = 0
    user_folders = glob.glob("Users/*")
    for user_folder in user_folders:
        try:
            user_id_to_send = int(os.path.basename(user_folder))
            if message.photo:
                bot.send_photo(
                    user_id_to_send,
                    message.photo[-1].file_id,
                    caption=message.caption if message.caption else ""
                )
            else:
                bot.send_message(user_id_to_send, message.text)
            success += 1
        except Exception as e:
            print(f"Ошибка при рассылке: {e}")
            failed += 1
    report = (
        f"👥 Пользователей: {total_users}\n"
        f"✅ Удалось отправить: {success}\n"
        f"❌ Не удалось отправить: {failed}"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
    bot.send_message(chat_id, report, reply_markup=markup)
    del user_states[user_id]
    if user_id in broadcast_messages:
        del broadcast_messages[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "manual_import")
def handle_manual_import(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    text = "📁 Для пополнения магазина, пожалуйста, отправьте файл с товаром в формате .txt:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="back_to_admin_panel"))
    try:
        msg = bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        user_states[user_id] = {
            "state": "waiting_import_file",
            "import_message_id": msg.message_id
        }
    except Exception as e:
        print(f"Ошибка при запросе файла: {e}")

@bot.message_handler(content_types=['document'], func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_import_file"
))
def handle_import_file(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["import_message_id"])
    except:
        pass
    if not message.document.file_name.endswith('.txt'):
        bot.send_message(chat_id, "❌ Файл должен быть в формате .txt!")
        del user_states[user_id]
        return
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    temp_path = f"temp_{user_id}_{message.message_id}.txt"
    with open(temp_path, 'wb') as new_file:
        new_file.write(downloaded_file)
    text = "Введите название категории товара:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="back_to_admin_panel"))
    msg = bot.send_message(chat_id, text, reply_markup=markup)
    user_states[user_id] = {
        "state": "waiting_category_name",
        "temp_file": temp_path,
        "category_message_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_category_name"
))
def handle_category_name(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["category_message_id"])
    except:
        pass
    category_name = message.text
    category_dir = f"Cookies/{category_name}"
    if not os.path.exists(category_dir):
        os.makedirs(category_dir)
    text = 'Введите название товара и цену, например: "DarkCookies - 2,5"'
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="back_to_admin_panel"))
    msg = bot.send_message(chat_id, text, reply_markup=markup)
    user_states[user_id] = {
        "state": "waiting_product_name",
        "temp_file": state["temp_file"],
        "category_dir": category_dir,
        "product_message_id": msg.message_id
    }

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_product_name"
))
def handle_product_name(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        bot.delete_message(chat_id, state["product_message_id"])
    except:
        pass
    product_name = message.text
    file_name = f"{product_name}.txt"
    safe_name = "".join([c for c in file_name if c.isalpha() or c.isdigit() or c in " -_."]).rstrip()
    final_path = os.path.join(state["category_dir"], safe_name)
    shutil.move(state["temp_file"], final_path)
    text = "✅ Товар был успешно пополнен в магазин!"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
    bot.send_message(chat_id, text, reply_markup=markup)
    del user_states[user_id]

def get_products_list():
    base_dir = "Cookies"
    if not os.path.exists(base_dir) or not os.listdir(base_dir):
        return None
    text = ""
    for category in os.listdir(base_dir):
        category_path = os.path.join(base_dir, category)
        if os.path.isdir(category_path):
            category_text = f"<b>➖➖{category}➖➖</b>\n"
            product_found = False
            for product in os.listdir(category_path):
                if product.endswith('.txt'):
                    product_path = os.path.join(category_path, product)
                    with open(product_path, 'r', encoding='utf-8') as f:
                        count = len(f.readlines())
                    if count == 0:
                        continue
                    product_found = True
                    product_name = os.path.splitext(product)[0]
                    if ' - ' in product_name:
                        name_part, price_part = product_name.rsplit(' - ', 1)
                        try:
                            price_val = float(price_part.replace(',', '.'))
                            formatted_price = format_price(price_val)
                            category_text += f"<b>{name_part} - {formatted_price} р. | {count} шт.</b>\n"
                        except ValueError:
                            category_text += f"<b>{product_name} | {count} шт.</b>\n"
                    else:
                        category_text += f"<b>{product_name} | {count} шт.</b>\n"
            if product_found:
                text += category_text + "\n"
    return text if text else None

@bot.callback_query_handler(func=lambda call: call.data == "products")
def handle_products(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    products_text = get_products_list()
    if not products_text:
        products_text = "Сейчас нет товаров в наличии."
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    try:
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=products_text,reply_markup=markup,parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отображения товаров: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "buy")
def handle_buy(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    base_dir = "Cookies"
    if not os.path.exists(base_dir) or not os.listdir(base_dir):
        text = "Сейчас нет товаров в наличии."
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        return
    markup = InlineKeyboardMarkup(row_width=2)
    categories = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    buttons = [InlineKeyboardButton(cat, callback_data=f"buy_category:{cat}") for cat in categories]
    markup.add(*buttons)
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    bot.edit_message_text(chat_id=chat_id,message_id=message_id,text="Выберите категорию для покупки:",reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_category:"))
def handle_buy_category(call):
    category = call.data.split(":", 1)[1]
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    category_path = os.path.join("Cookies", category)
    products = [f for f in os.listdir(category_path) if f.endswith('.txt')]
    markup = InlineKeyboardMarkup(row_width=1)
    product_exists = False
    for product_file in products:
        product_path = os.path.join(category_path, product_file)
        with open(product_path, 'r', encoding='utf-8') as f:
            count = len(f.readlines())
        if count == 0:
            continue
        product_exists = True
        product_name = os.path.splitext(product_file)[0]
        display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
        button_text = f"{display_name} | {count} шт."
        callback_data = f"select_product:{category}:{product_file}"
        markup.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="buy"))
    if product_exists:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="Выберите товар для покупки:", reply_markup=markup)
    else:
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text="В этой категории нет товаров!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("select_product:"))
def handle_select_product(call):
    data = call.data.split(":", 2)
    category = data[1]
    product_file = data[2]
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_id = call.from_user.id
    file_path = os.path.join("Cookies", category, product_file)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        count = len(lines)
    except Exception as e:
        print(f"Ошибка чтения файла товара: {e}")
        count = 0
    product_name = os.path.splitext(product_file)[0]
    display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
    price_str = product_name.split("-")[-1].strip()
    try:
        price = float(price_str.replace(',', '.'))
    except ValueError:
        price = 0.0
    user_states[user_id] = {
        "state": "buying_product",
        "category": category,
        "product_file": product_file,
        "file_path": file_path,
        "price": price,
        "max_quantity": count,
        "buy_message_id": message_id
    }
    formatted_price = format_price(price)
    markup = InlineKeyboardMarkup(row_width=5)
    quantities = [5, 10, 20, 30, 50]
    buttons = [InlineKeyboardButton(str(q), callback_data=f"set_quantity:{q}") for q in quantities if q <= count]
    markup.add(*buttons)
    markup.add(InlineKeyboardButton("✍️ Ввод своего кол-ва", callback_data="input_quantity"))
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"buy_category:{category}"))
    text = (
        f"🍪 Товар: {display_name}\n"
        f"💸 Цена: {formatted_price} ₽\n"
        f"📦 Доступное количество: {count} шт.\n\n"
        f"🔢 Выберите количество товара, которое хотите купить:"
    )
    bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "input_quantity")
def handle_input_quantity(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id not in user_states:
        return
    state = user_states[user_id]
    state["state"] = "waiting_quantity"
    text = "Введите количество товара, которое хотите купить:"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"select_product:{state['category']}:{state['product_file']}"))
    try:
        msg = bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        state["quantity_message_id"] = msg.message_id
    except:
        pass

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_quantity"
))
def handle_quantity_input(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state = user_states[user_id]
    try:
        quantity = int(message.text)
        if quantity <= 0 or quantity > state["max_quantity"]:
            raise ValueError
    except:
        if "error_message_id" in state:
            try:
                bot.delete_message(chat_id, state["error_message_id"])
            except:
                pass
        error_text = "❌ Вы ввели неправильное количество товара. Пожалуйста, попробуйте снова:"
        error_msg = bot.send_message(chat_id, error_text)
        state["error_message_id"] = error_msg.message_id
        return
    state["quantity"] = quantity
    state["state"] = "choosing_payment"
    try:
        bot.delete_message(chat_id, state["quantity_message_id"])
    except:
        pass
    if "error_message_id" in state:
        try:
            bot.delete_message(chat_id, state["error_message_id"])
        except:
            pass
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    total_price = quantity * state["price"]
    text = f"Выберите способ оплаты для {quantity} шт. товара (Итого: {total_price} ₽):"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🤖 CryptoBot", callback_data="payment_crypto"),
        InlineKeyboardButton("💰 Баланс", callback_data="payment_balance")
    )
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"select_product:{state['category']}:{state['product_file']}"))
    bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "payment_crypto")
def handle_payment_crypto(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id not in user_states:
        return
    state = user_states[user_id]
    total_price = state["quantity"] * state["price"]
    amount_usdt = total_price / RUB_TO_USDT_RATE
    order_id = str(uuid.uuid4().int)[:8]
    order_time = time.strftime("%Y-%m-%d %H:%M")
    expire_time = int(time.time()) + 300
    expire_time_str = time.strftime("%H:%M", time.localtime(expire_time))
    formatted_price = format_price(state["price"])
    formatted_total = format_price(total_price)
    product_name = os.path.splitext(state['product_file'])[0]
    display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
    try:
        invoice = create_invoice(
            asset='USDT',
            amount=amount_usdt,
            description=f'Покупка товара: {display_name}'
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка при создании счета: {str(e)}")
        return
    reservation_id = reserve_product(user_id, state["file_path"], state["quantity"])
    active_payments[invoice['invoice_id']] = {
        "user_id": user_id,
        "quantity": state["quantity"],
        "product_path": state["file_path"],
        "reservation_id": reservation_id,
        "order_id": order_id,
        "expire_time": expire_time,
        "chat_id": chat_id,
        "message_id": message_id
    }
    text = (
        f"➖➖➖➖➖➖➖➖➖➖➖➖\n"
        f"🍪 Товар: {display_name}\n"
        f"💸 Цена за шт.: {formatted_price} ₽\n"
        f"📦 Кол-во: {state['quantity']} шт.\n"
        f"🆔 Заказ: #{order_id}\n"
        f"🕐 Время заказа: {order_time}\n"
        f"💰 Итоговая сумма: {formatted_total} ₽\n"
        f"💳 Способ оплаты: CryptoBot\n"
        f"➖➖➖➖➖➖➖➖➖➖➖➖\n"
        f"Для оплаты перейдите по ссылке!\n"
        f"⏰ Время на оплату: 5 минут\n"
        f"🕜 Необходимо оплатить до {expire_time_str}\n"
        f"➖➖➖➖➖➖➖➖➖➖➖➖"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Перейти к оплате", url=invoice['pay_url']))
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_payment:{invoice['invoice_id']}"))
    bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
    threading.Thread(
        target=check_crypto_payment,
        args=(invoice['invoice_id'],),
        daemon=True
    ).start()
    del user_states[user_id]

def reserve_product(user_id, product_path, quantity):
    user_dir = f"Users/{user_id}"
    reservation_dir = os.path.join(user_dir, "Reservation")
    os.makedirs(reservation_dir, exist_ok=True)
    with open(product_path, 'r') as f:
        lines = f.readlines()
    reserved_lines = lines[:quantity]
    remaining_lines = lines[quantity:]
    reservation_id = str(uuid.uuid4().int)[:8]
    reservation_path = os.path.join(reservation_dir, f"{reservation_id}.txt")
    with open(reservation_path, 'w') as f:
        f.writelines(reserved_lines)
    with open(product_path, 'w') as f:
        f.writelines(remaining_lines)
    return reservation_id

def check_crypto_payment(invoice_id):
    if invoice_id not in active_payments:
        return
    payment = active_payments[invoice_id]
    start_time = time.time()
    while time.time() < payment["expire_time"]:
        try:
            status = get_invoice_status(invoice_id)
            if status == 'paid':
                total_price = payment["quantity"] * get_product_price(payment["product_path"])
                finalize_purchase(payment["user_id"], payment["reservation_id"], payment["order_id"], total_price)
                product_name = os.path.splitext(os.path.basename(payment["product_path"]))[0]
                display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
                formatted_total = format_price(total_price)
                try:
                    bot.delete_message(payment["chat_id"], payment["message_id"])
                except:
                    pass
                text = (
                    f"😁 Спасибо за покупку @{bot.get_chat(payment['user_id']).username} (ID: {payment['user_id']})!\n"
                    f"📦 Товар: {display_name}\n"
                    f"📋 Количество: {payment['quantity']} шт.\n"
                    f"💰 Цена: {formatted_total} ₽\n"
                    f"⏳ Время покупки: {time.strftime('%H:%M')}"
                )
                purchase_path = os.path.join(
                    f"Users/{payment['user_id']}/Purchase", 
                    f"Покупка #{payment['order_id']}.txt"
                ) 
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu_from_purchase"))
                with open(purchase_path, 'rb') as file:
                    bot.send_document(payment["chat_id"], file, caption=text,reply_markup=markup)
                del active_payments[invoice_id]
                return
            elif status == 'expired':
                return_product(payment["user_id"], payment["reservation_id"], payment["product_path"])
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
                bot.edit_message_text(
                    chat_id=payment["chat_id"],
                    message_id=payment["message_id"],
                    text="⏳ Время оплаты истекло!",
                    reply_markup=markup
                )
                del active_payments[invoice_id]
                return
        except Exception as e:
            print(f"Ошибка проверки платежа: {e}")
        time.sleep(5)
    return_product(payment["user_id"], payment["reservation_id"], payment["product_path"])
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
    bot.edit_message_text(chat_id=payment["chat_id"],message_id=payment["message_id"],text="⏳ Время оплаты истекло!",reply_markup=markup)
    del active_payments[invoice_id]

def finalize_purchase(user_id, reservation_id, order_id, purchase_amount):
    reservation_path = os.path.join(f"Users/{user_id}/Reservation", f"{reservation_id}.txt")
    purchase_dir = os.path.join(f"Users/{user_id}/Purchase")
    os.makedirs(purchase_dir, exist_ok=True)
    new_file_name = f"Покупка #{order_id}.txt"
    shutil.move(reservation_path, os.path.join(purchase_dir, new_file_name))
    user_file = f"Users/{user_id}/{user_id}.json"
    if os.path.exists(user_file):
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        user_data['Purchases'] = user_data.get('Purchases', 0) + purchase_amount
        with open(user_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)

def return_product(user_id, reservation_id, product_path):
    reservation_path = os.path.join(f"Users/{user_id}/Reservation", f"{reservation_id}.txt")
    with open(reservation_path, 'r') as f:
        lines = f.readlines()
    with open(product_path, 'a') as f:
        f.writelines(lines)
    os.remove(reservation_path)

@bot.callback_query_handler(func=lambda call: call.data == "payment_balance")
def handle_payment_balance(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id not in user_states:
        return
    state = user_states[user_id]
    total_price = state["quantity"] * state["price"]
    formatted_total = format_price(total_price)
    product_name = os.path.splitext(state['product_file'])[0]
    display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
    user_data = get_user_data(user_id, call.from_user.username)
    if user_data["Balance"] < total_price:
        text = "❌ Недостаточно средств для оплаты товара!"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        del user_states[user_id]
        return
    update_user_balance(user_id, -total_price)
    order_id = str(uuid.uuid4().int)[:8]
    issue_product(user_id, state["file_path"], state["quantity"], order_id)
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass
    purchase_path = os.path.join(f"Users/{user_id}/Purchase", f"Покупка #{order_id}.txt")
    caption = (
        f"😁 Спасибо за покупку @{call.from_user.username} (ID: {user_id})!\n"
        f"📦 Товар: {display_name}\n"
        f"📋 Количество: {state['quantity']} шт.\n"
        f"💰 Цена: {formatted_total} ₽\n"
        f"⏳ Время покупки: {time.strftime('%H:%M')}\n\n"
        f"📒 Ваш товар:"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Домой", callback_data="back_to_menu_from_purchase"))
    with open(purchase_path, 'rb') as file:
        bot.send_document(chat_id, file, caption=caption, reply_markup=markup)
    del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu_from_purchase")
def handle_back_to_menu_from_purchase(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name
    user_id = call.from_user.id
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass
    show_menu(chat_id, user_name=user_name, user_id=user_id)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_menu")
def handle_back_to_menu(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    show_menu(chat_id, message_id, user_name=call.from_user.first_name, user_id=user_id)

def issue_product(user_id, product_path, quantity, order_id):
    with open(product_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    purchased_lines = lines[:quantity]
    remaining_lines = lines[quantity:]
    purchase_dir = os.path.join(f"Users/{user_id}/Purchase")
    os.makedirs(purchase_dir, exist_ok=True)
    purchase_path = os.path.join(purchase_dir, f"Покупка #{order_id}.txt")
    with open(purchase_path, 'w', encoding='utf-8') as f:
        f.writelines(purchased_lines)
    with open(product_path, 'w', encoding='utf-8') as f:
        f.writelines(remaining_lines)
    total_price = quantity * get_product_price(product_path)
    user_file = f"Users/{user_id}/{user_id}.json"
    if os.path.exists(user_file):
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        user_data['Purchases'] = user_data.get('Purchases', 0) + total_price
        with open(user_file, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=4)
    cleanup_empty_products_and_categories()

@bot.callback_query_handler(func=lambda call: call.data == "order_history")
def handle_order_history(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    purchase_dir = f"Users/{user_id}/Purchase"
    if not os.path.exists(purchase_dir) or not os.listdir(purchase_dir):
        text = "У вас еще нет покупок."
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile"))
        bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        return
    orders = sorted(os.listdir(purchase_dir), key=lambda x: os.path.getmtime(os.path.join(purchase_dir, x)), reverse=True)
    user_states[user_id] = {
        "orders": orders,
        "current_page": 1
    }
    show_order_page(user_id, chat_id, message_id)

def show_order_page(user_id, chat_id, message_id):
    state = user_states[user_id]
    orders = state["orders"]
    page = state["current_page"]
    per_page = 5
    total_pages = (len(orders) + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, len(orders))
    text = f"[🗃] Ваши покупки [Страница {page}/{total_pages}]:\n\n"
    markup = InlineKeyboardMarkup()
    for i in range(start_idx, end_idx):
        order_file = orders[i]
        order_id = os.path.splitext(order_file)[0]
        order_time = time.strftime("%d.%m.%Y", time.localtime(os.path.getmtime(os.path.join(f"Users/{user_id}/Purchase", order_file))))
        button_text = f"📦{order_id} - {order_time}"
        markup.add(InlineKeyboardButton(button_text, callback_data=f"view_order:{order_file}"))
    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️", callback_data="order_prev_page"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("▶️", callback_data="order_next_page"))
        if nav_buttons:
            markup.row(*nav_buttons)
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile"))
    if message_id:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
        except:
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["order_prev_page", "order_next_page"])
def handle_order_navigation(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id not in user_states:
        return
    state = user_states[user_id]
    if call.data == "order_prev_page":
        state["current_page"] -= 1
    else:
        state["current_page"] += 1
    show_order_page(user_id, chat_id, message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_order:"))
def handle_view_order(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    order_file = call.data.split(":", 1)[1]
    order_path = os.path.join(f"Users/{user_id}/Purchase", order_file)
    if not os.path.exists(order_path):
        bot.answer_callback_query(call.id, text="Заказ не найден!")
        return
    order_id = os.path.splitext(order_file)[0]
    order_time = time.strftime("%d.%m.%Y в %H:%M", time.localtime(os.path.getmtime(order_path)))
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass
    caption = (
        f"Информация о вашей покупке:\n"
        f"🆔 ID: {user_id}\n"
        f"🛒 ID покупки: #{order_id}\n"
        f"⏳ Время покупки: {order_time}\n\n"
        f"📒 Ваш товар:"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_order_list"))
    with open(order_path, 'rb') as file:
        bot.send_document(chat_id, file, caption=caption, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "back_to_order_list")
def handle_back_to_order_list(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass
    show_order_page(user_id, chat_id, None)

def get_product_price(product_path):
    file_name = os.path.basename(product_path)
    price_str = os.path.splitext(file_name)[0].split("-")[-1].strip()
    try:
        return float(price_str.replace(',', '.'))
    except:
        return 0.0

@bot.message_handler(content_types=['document'], func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_import_file"
))
@bot.callback_query_handler(func=lambda call: call.data == "back_to_profile")
def handle_back_to_profile(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    username = call.from_user.username or "None"
    user_data = get_user_data(user_id, username)
    profile_text = (
        "➖➖➖➖➖➖➖➖➖➖\n"
        "ℹ️Личный кабинет:\n\n"
        f"👤 Имя: @{user_data['Username']}\n"
        f"🆔 ID: {user_data['Id']}\n"
        f"🎁 Покупок на сумму: {user_data['Purchases']} руб.\n\n"
        f"💸 Баланс: {user_data['Balance']} руб.\n"
        "📧 Для пополнения баланса нажмите на кнопку ниже!\n"
        "➖➖➖➖➖➖➖➖➖➖"
    )
    bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=profile_text,reply_markup=InlineKeyboardMarkup().row(
            InlineKeyboardButton("💸Пополнить баланс", callback_data="add_balance"),
            InlineKeyboardButton("📈История Заказов", callback_data="order_history")
        ).add(InlineKeyboardButton("◀️Назад", callback_data="back_to_menu")))
    if user_id in user_states:
        del user_states[user_id]

@bot.message_handler(func=lambda message: (
    message.from_user.id in user_states and
    isinstance(user_states[message.from_user.id], dict) and
    user_states[message.from_user.id].get("state") == "waiting_for_amount"
))
def handle_amount_input(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state_data = user_states[user_id]
    try:
        try:
            bot.delete_message(chat_id, state_data["request_message_id"])
        except Exception as e:
            print(f"Ошибка при удалении запроса: {e}")
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения пользователя: {e}")
        amount_rub = int(message.text)
        if amount_rub <= 0:
            raise ValueError("Сумма должна быть положительной")
        amount_usdt = amount_rub / RUB_TO_USDT_RATE
        if amount_usdt < 0.01:
            raise ValueError("Минимальная сумма пополнения 1 рубль")
        invoice = create_invoice(
            asset='USDT',
            amount=amount_usdt,
            description=f'Пополнение баланса на {amount_rub} руб.'
        )
        active_payments[invoice['invoice_id']] = {
            "user_id": user_id,
            "amount_rub": amount_rub,
            "chat_id": chat_id
        }
        payment_text = (
            f"Пополнение баланса на сумму {amount_rub} руб.\n"
            f"Оплатите {amount_usdt:.2f} USDT по <a href=\"{invoice['pay_url']}\">ссылке</a>."
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_payment:{invoice['invoice_id']}"))
        sent_msg = bot.send_message(chat_id, payment_text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        active_payments[invoice['invoice_id']]["invoice_message_id"] = sent_msg.message_id
        threading.Thread(
            target=check_payment_status,
            args=(invoice['invoice_id'], user_id, amount_rub, chat_id),
            daemon=True
        ).start()
        del user_states[user_id]
    except ValueError as e:
        error_msg = "❌ Вы ввели неправильную сумму. Пожалуйста, попробуйте снова:"
        if "положительной" in str(e):
            error_msg = "❌ Сумма должна быть больше 0. Пожалуйста, попробуйте снова:"
        elif "Минимальная" in str(e):
            error_msg = "❌ Минимальная сумма пополнения 1 рубль. Пожалуйста, попробуйте снова:"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_profile"))
        error_msg_obj = bot.send_message(chat_id, error_msg, reply_markup=markup)
        user_states[user_id] = {
            "state": "waiting_for_amount",
            "request_message_id": error_msg_obj.message_id
        }
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Ошибка при создании платежа: {str(e)}")
        if user_id in user_states:
            del user_states[user_id]

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_payment:"))
def handle_cancel_payment(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    invoice_id = call.data.split(":")[1]
    try:
        bot.delete_message(chat_id, message_id)
    except:
        pass
    if invoice_id in active_payments:
        del active_payments[invoice_id]
    username = call.from_user.username or "None"
    user_data = get_user_data(user_id, username)
    profile_text = (
        "➖➖➖➖➖➖➖➖➖➖\n"
        "ℹ️Личный кабинет:\n\n"
        f"👤 Имя: @{user_data['Username']}\n"
        f"🆔 ID: {user_data['Id']}\n"
        f"🎁 Покупок на сумму: {user_data['Purchases']} руб.\n\n"
        f"💸 Баланс: {user_data['Balance']} руб.\n"
        "📧 Для пополнения баланса нажмите на кнопку ниже!\n"
        "➖➖➖➖➖➖➖➖➖➖"
    )
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("💸Пополнить баланс", callback_data="add_balance"),
        InlineKeyboardButton("📈История Заказов", callback_data="order_history")
    )
    markup.add(InlineKeyboardButton("◀️Назад", callback_data="back_to_menu"))
    bot.send_message(chat_id, profile_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    user_name = call.from_user.first_name
    username = call.from_user.username or "None"
    if user_id in user_states and user_states[user_id] == "waiting_for_amount":
        del user_states[user_id]
    if call.data == "profile":
        user_data = get_user_data(user_id, username)
        profile_text = (
            "➖➖➖➖➖➖➖➖➖➖\n"
            "ℹ️Личный кабинет:\n\n"
            f"👤 Имя: @{user_data['Username']}\n"
            f"🆔 ID: {user_data['Id']}\n"
            f"🎁 Покупок на сумму: {user_data['Purchases']} руб.\n\n"
            f"💸 Баланс: {user_data['Balance']} руб.\n"
            "📧 Для пополнения баланса нажмите на кнопку ниже!\n"
            "➖➖➖➖➖➖➖➖➖➖"
        )
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("💸Пополнить баланс", callback_data="add_balance"),
            InlineKeyboardButton("📈История Заказов", callback_data="order_history")
        )
        markup.add(InlineKeyboardButton("◀️Назад", callback_data="back_to_menu"))
        try:
            bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=profile_text,reply_markup=markup)
        except Exception as e:
            print(f"Ошибка при редактировании: {e}")
        return
    if call.data == "rules":
        rules_text = (
            "Привет, в этом разделе находятся правила перед покупкой: <b>-- жирным текстом</b>\n\n"
            "<b>1) Покупка или пополнение</b>\n"
            "<b>1.1) Если вам выпало n-ое количество невалидных аккаунтов, пишите в нашу тех поддержку, выдадим вам замену кратную количеству невалидных аккаунтов.</b>\n"
            "<b>1.2) Куки - чистейший рандом, если вам ничего не выпало - ответственности не несём</b>\n"
            "<b>1.3) Если у вас случилась какая либо ошибка при пополнении, напишите нам - сделаем всё, что в наших силах.</b>\n\n"
            "<b>2) Тех.Поддержка</b>\n"
            "<b>2.1) Если что-то случилось касаемо нашего бота - пишите в техподдержку (ответим вплоть до 24 часов)</b>\n\n"
            "<b>Возврат средств невозможен, если только владелец не одобрил его вручную</b>\n\n"
            "<b>Ваш - Darkness Cookie &lt;3</b>"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=rules_text,reply_markup=markup,parse_mode="HTML")
        return
    if call.data == "help":
        message_to_delete[user_id] = message_id
        help_text = "🧑‍💻 | Пожалуйста, расскажите о вашей проблеме. Если у вас есть возможность, прикрепите скриншот - это поможет нам быстрее разобраться в проблеме:"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=help_text,reply_markup=markup)
        user_states[user_id] = "waiting_for_problem"
    if call.data.startswith("buy_category:"):
        handle_buy_category(call)
    elif call.data.startswith("select_product:"):
        handle_select_product(call)
    elif call.data == "input_quantity":
        handle_input_quantity(call)
    elif call.data.startswith("set_quantity:"):
        handle_set_quantity(call)
    elif call.data == "payment_crypto":
        handle_payment_crypto(call)
    elif call.data == "payment_balance":
        handle_payment_balance(call)
    elif call.data == "order_history":
        handle_order_history(call)
    elif call.data in ["order_prev_page", "order_next_page"]:
        handle_order_navigation(call)
    elif call.data.startswith("view_order:"):
        handle_view_order(call)
    elif call.data == "back_to_menu":
        if user_id in message_to_delete:
            try:
                bot.delete_message(chat_id, message_to_delete[user_id])
                del message_to_delete[user_id]
            except:
                pass
        show_menu(chat_id, message_id, user_name=user_name, user_id=user_id)
    elif call.data == "admin_panel":
        bot.answer_callback_query(call.id, text="Панель администратора активирована")
    elif call.data == "close_ticket":
        if message_id in tickets:
            ticket = tickets[message_id]
            ticket_id = ticket["ticket_id"]
            close_text = "Вы скрыли заявку пользователя. Если вы вернетесь в меню, заявка будет удалена. Если вы случайно скрыли заявку, нажмите на кнопку \"🔄 Восстановить\""
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🏠 Меню", callback_data="admin_menu"),
                InlineKeyboardButton("🔄 Восстановить", callback_data=f"restore_ticket:{ticket_id}")
            )
            if ticket.get("has_photo"):
                bot.edit_message_caption(chat_id=chat_id,message_id=message_id,caption=close_text,reply_markup=markup)
            else:
                bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=close_text,reply_markup=markup)
    elif call.data.startswith("restore_ticket:"):
        ticket_id = call.data.split(":")[1]
        original_ticket = None
        for msg_id, ticket in tickets.items():
            if ticket["ticket_id"] == ticket_id:
                original_ticket = ticket
                break
        if original_ticket:
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket:{original_ticket['user_id']}"),
                InlineKeyboardButton("❌ Скрыть", callback_data="close_ticket")
            )
            if original_ticket.get("has_photo"):
                bot.edit_message_caption(chat_id=chat_id,message_id=message_id,caption=original_ticket["text"],parse_mode="HTML",reply_markup=markup)
            else:
                bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=original_ticket["text"],parse_mode="HTML",reply_markup=markup)
    elif call.data == "admin_menu":
        if message_id in tickets:
            del tickets[message_id]
        bot.delete_message(chat_id, message_id)
        time.sleep(0.3)
        show_menu(chat_id, user_name=user_name, user_id=user_id)
    elif call.data.startswith("reply_ticket:"):
        target_user_id = int(call.data.split(":")[1])
        if message_id in tickets:
            tickets[message_id]["admin_message_id"] = message_id
        reply_text = "🧑‍💻 Введите ваш ответ для пользователя:"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_ticket"))
        if tickets[message_id].get("has_photo"):
            bot.edit_message_caption(chat_id=chat_id,message_id=message_id,caption=reply_text,reply_markup=markup)
        else:
            bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=reply_text,reply_markup=markup)
        user_states[user_id] = {
            "state": "admin_reply",
            "target_user_id": target_user_id,
            "ticket_message_id": message_id
        }
        admin_messages[user_id] = message_id
    elif call.data == "back_to_ticket":
        if message_id in tickets:
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket:{tickets[message_id]['user_id']}"),
                InlineKeyboardButton("❌ Скрыть", callback_data="close_ticket")
            )
            if tickets[message_id].get("has_photo"):
                bot.edit_message_caption(chat_id=chat_id,message_id=message_id,caption=tickets[message_id]["text"],parse_mode="HTML",reply_markup=markup)
            else:
                bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=tickets[message_id]["text"],parse_mode="HTML",reply_markup=markup)
    elif call.data == "helpful":
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text="🧑‍💻 Спасибо за обратную связь! Если у вас возникнут еще вопросы, обращайтесь снова.",)
        time.sleep(1)
        bot.delete_message(chat_id, message_id)
        time.sleep(0.3)
        show_menu(chat_id, user_name=user_name, user_id=user_id)
        for admin_id in adminss:
            try:
                bot.send_message(admin_id,f"Пользователю @{call.from_user.username}, помог ваш ответ! 👍")
            except:
                pass
    elif call.data == "user_reply":
        user_states[user_id] = {
            "state": "user_reply",
            "request_message_id": message_id
        }
        reply_text = "Введите ваш ответ для сотрудника поддержки:"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_reply"))
        bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=reply_text,reply_markup=markup
        )
    elif call.data == "cancel_reply":
        if user_id in user_states:
            del user_states[user_id]
        try:
            bot.delete_message(chat_id, message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
        time.sleep(0.3)
        show_menu(chat_id, user_name=user_name, user_id=user_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_quantity:"))
def handle_set_quantity(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    if user_id not in user_states:
        return
    quantity = int(call.data.split(":")[1])
    state = user_states[user_id]
    state["quantity"] = quantity
    state["state"] = "choosing_payment"
    total_price = quantity * state["price"]
    formatted_total = format_price(total_price)
    formatted_price = format_price(state["price"])
    product_name = os.path.splitext(state['product_file'])[0]
    display_name = product_name.rsplit(' - ', 1)[0] if ' - ' in product_name else product_name
    text = (
        f"🍪 Товар: {display_name}\n"
        f"💸 Цена за шт.: {formatted_price} ₽\n"
        f"📦 Количество: {quantity} шт.\n"
        f"💰 Итого: {formatted_total} ₽\n\n"
        f"Выберите способ оплаты:"
    )
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🤖 CryptoBot", callback_data="payment_crypto"),
        InlineKeyboardButton("💰 Баланс", callback_data="payment_balance")
    )
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"select_product:{state['category']}:{state['product_file']}"))
    bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=text,reply_markup=markup)

@bot.message_handler(content_types=['text', 'photo'])
def handle_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    if user_id in user_states and user_states[user_id] == "waiting_for_problem":
        if user_id in message_to_delete:
            try:
                bot.delete_message(chat_id, message_to_delete[user_id])
                del message_to_delete[user_id]
            except:
                pass
        problem_text = message.caption if message.caption else message.text
        has_photo = False
        photo_id = None
        if message.photo:
            has_photo = True
            photo_id = message.photo[-1].file_id
        confirm_text = "<b>✉️ Ваша заявка успешно создана.</b>\nПожалуйста, ожидайте ответа от администрации. Обычно время ответа составляет до 1 часа, но в случае высокой загруженности оно может увеличиться до 24 часов!"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        confirm_msg = bot.send_message(chat_id, confirm_text, parse_mode="HTML", reply_markup=markup)
        message_to_delete[user_id] = confirm_msg.message_id
        if not problem_text:
            problem_text = "Проблема не указана"
        for admin_id in adminss:
            ticket_text = (
                f"<b>📨 Запрос в поддержку!</b>\n\n"
                f"👤 Пользователь: @{message.from_user.username}\n"
                f"🆔 ID: {user_id}\n"
                f"📝 Проблема пользователя: {problem_text}"
            )
            try:
                bot.get_chat(admin_id)
            except Exception as e:
                print(f"Не удалось получить чат с админом {admin_id}: {e}")
                continue
            try:
                if has_photo:
                    msg = bot.send_photo(admin_id, photo_id, caption=ticket_text, parse_mode="HTML")
                else:
                    msg = bot.send_message(admin_id, ticket_text, parse_mode="HTML")
            except Exception as e:
                print(f"Не удалось отправить запрос админу {admin_id}: {e}")
                continue
            ticket_id = f"ticket_{user_id}_{msg.message_id}"
            tickets[msg.message_id] = {
                "ticket_id": ticket_id,
                "user_id": user_id,
                "text": ticket_text,
                "has_photo": has_photo,
                "photo_id": photo_id if has_photo else None
            }
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket:{user_id}"),
                InlineKeyboardButton("❌ Скрыть", callback_data="close_ticket")
            )
            try:
                if has_photo:
                    bot.edit_message_caption(chat_id=admin_id, message_id=msg.message_id, caption=ticket_text, parse_mode="HTML", reply_markup=markup)
                else:
                    bot.edit_message_text(chat_id=admin_id, message_id=msg.message_id, text=ticket_text, parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                print(f"Не удалось отредактировать сообщение админа {admin_id}: {e}")
        del user_states[user_id]
    elif user_id in user_states and isinstance(user_states[user_id], dict) and user_states[user_id].get("state") == "admin_reply":
        admin_state = user_states[user_id]
        target_user_id = admin_state["target_user_id"]
        ticket_msg_id = admin_state["ticket_message_id"]
        if user_id in admin_messages:
            try:
                bot.delete_message(chat_id, admin_messages[user_id])
                del admin_messages[user_id]
            except:
                pass
        reply_text = message.caption if message.caption else message.text
        has_photo = False
        photo_id = None
        if message.photo:
            has_photo = True
            photo_id = message.photo[-1].file_id
        response_text = f"🧑‍💻 Ответ от поддержки: {reply_text}"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("💬 Ответить", callback_data="user_reply"),
            InlineKeyboardButton("Ответ помог👍", callback_data="helpful")
        )
        try:
            if has_photo:
                bot.send_photo(target_user_id,photo_id,caption=response_text,reply_markup=markup)
            else:
                bot.send_message(target_user_id,response_text,reply_markup=markup)
        except Exception as e:
            print(f"Ошибка отправки пользователю: {e}")
        bot.send_message(user_id, "✅ Ваш ответ был успешно доставлен пользователю!")
        show_menu(user_id, user_name=user_name, user_id=user_id)
        if ticket_msg_id in tickets:
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket:{target_user_id}"),
                InlineKeyboardButton("❌ Скрыть", callback_data="close_ticket")
            )
            try:
                if tickets[ticket_msg_id].get("has_photo"):
                    bot.edit_message_caption(chat_id=user_id,message_id=ticket_msg_id,caption=tickets[ticket_msg_id]["text"],parse_mode="HTML",reply_markup=markup)
                else:
                    bot.edit_message_text(chat_id=user_id,message_id=ticket_msg_id,text=tickets[ticket_msg_id]["text"],parse_mode="HTML",reply_markup=markup)
            except:
                pass
        del user_states[user_id]
    elif user_id in user_states and isinstance(user_states[user_id], dict) and user_states[user_id].get("state") == "user_reply":
        state_data = user_states[user_id]
        request_msg_id = state_data.get("request_message_id")
        if request_msg_id:
            try:
                bot.delete_message(chat_id, request_msg_id)
            except:
                pass
        reply_text = message.caption if message.caption else message.text
        has_photo = False
        photo_id = None
        if message.photo:
            has_photo = True
            photo_id = message.photo[-1].file_id
        confirm_text = "<b>✉️ Ваша заявка успешно создана.</b>\nПожалуйста, ожидайте ответа от администрации. Обычно время ответа составляет до 1 часа, но в случае высокой загруженности оно может увеличиться до 24 часов!"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        confirm_msg = bot.send_message(chat_id,confirm_text,parse_mode="HTML",reply_markup=markup)
        message_to_delete[user_id] = confirm_msg.message_id
        if not reply_text:
            reply_text = "Ответ не указан"
        for admin_id in adminss:
            ticket_text = (
                f"<b>❓ Ответ в поддержку!</b>\n\n"
                f"👤 Пользователь: @{message.from_user.username}\n"
                f"🆔 ID: {user_id}\n"
                f"📝 Ответ пользователя: {reply_text}"
            )
            if has_photo:
                msg = bot.send_photo(admin_id,photo_id,caption=ticket_text,parse_mode="HTML")
            else:
                msg = bot.send_message(admin_id,ticket_text,parse_mode="HTML")
            ticket_id = f"ticket_{user_id}_{msg.message_id}"
            tickets[msg.message_id] = {
                "ticket_id": ticket_id,
                "user_id": user_id,
                "text": ticket_text,
                "has_photo": has_photo,
                "photo_id": photo_id if has_photo else None
            }
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("💬 Ответить", callback_data=f"reply_ticket:{user_id}"),
                InlineKeyboardButton("❌ Скрыть", callback_data="close_ticket")
            )
            if has_photo:
                bot.edit_message_caption(chat_id=admin_id,message_id=msg.message_id,caption=ticket_text,parse_mode="HTML",reply_markup=markup)
            else:
                bot.edit_message_text(chat_id=admin_id,message_id=msg.message_id,text=ticket_text,parse_mode="HTML",reply_markup=markup)
        del user_states[user_id]

if __name__ == "__main__":
    os.makedirs("Cookies", exist_ok=True)
    os.makedirs("AutoCookies", exist_ok=True)
    print("Бот запущен...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)