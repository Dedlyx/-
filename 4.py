import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import random
import json
import os
import time

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = "7687096568:AAEIToYE75cf0eCkFk_XcfVlM3nXFAr-NVI"
CHANNEL_ID = -1003207415613
ADMIN_IDS = [7955714952]  # Ваш ID

# Инициализация
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_admin_message = State()

# Хранилище данных
active_captchas: Dict[int, Dict] = {}
approved_users = set()
user_data = {}

# Загрузка данных
def load_data():
    global approved_users, user_data
    try:
        if os.path.exists('data.json'):
            with open('data.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                approved_users = set(data.get('approved_users', []))
                user_data = data.get('user_data', {})
                logger.info(f"Загружено {len(approved_users)} пользователей")
    except Exception as e:
        logger.error(f"Ошибка загрузки: {e}")

def save_data():
    try:
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump({
                'approved_users': list(approved_users),
                'user_data': user_data,
                'last_save': datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

# Сохраняем информацию о пользователе
def save_user_info(user: types.User):
    user_id = user.id
    if user_id not in user_data:
        user_data[user_id] = {
            'username': user.username,
            'full_name': user.full_name,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'language_code': user.language_code,
            'is_premium': user.is_premium or False,
            'first_seen': datetime.now().isoformat(),
            'last_seen': datetime.now().isoformat(),
            'approved': user_id in approved_users
        }
    else:
        user_data[user_id]['last_seen'] = datetime.now().isoformat()
        user_data[user_id]['approved'] = user_id in approved_users
    save_data()

# Генерация капчи
def generate_simple_captcha() -> tuple:
    types = [
        ("math", f"{random.randint(1, 9)} + {random.randint(1, 9)}"),
        ("math", f"{random.randint(2, 9)} × {random.randint(2, 4)}"),
        ("math", f"{random.randint(6, 15)} - {random.randint(1, 5)}"),
        ("number", f"{random.randint(100, 999)}"),
        ("number", f"{random.randint(10, 99)}"),
        ("color", random.choice(["красный", "синий", "зеленый", "желтый", "белый", "черный"])),
        ("animal", random.choice(["кошка", "собака", "мышь", "заяц", "медведь"])),
    ]
    
    captcha_type, captcha_text = random.choice(types)
    
    if captcha_type == "math":
        if "+" in captcha_text:
            parts = captcha_text.split("+")
            answer = str(int(parts[0].strip()) + int(parts[1].strip()))
        elif "×" in captcha_text:
            parts = captcha_text.split("×")
            answer = str(int(parts[0].strip()) * int(parts[1].strip()))
        elif "-" in captcha_text:
            parts = captcha_text.split("-")
            answer = str(int(parts[0].strip()) - int(parts[1].strip()))
        else:
            answer = captcha_text
    else:
        answer = captcha_text.lower()
    
    return captcha_text, answer

# Сообщения
MESSAGES = {
    "welcome": "🎉 *Добро пожаловать!*\n\nДля доступа к каналу пройди проверку.",
    "captcha_start": "🔐 *Проверка безопасности*\n\n📝 *Вопрос:* {question}\n\n✏️ *Введи ответ:*",
    "captcha_progress": "🔐 *Проверка безопасности*\n\n📝 *Вопрос:* {question}\n\n✏️ *Твой ответ:* `{user_input}`",
    "success": "✅ *Поздравляем!*\n\nТы успешно прошел проверку!",
    "wrong_answer": "❌ *Неверный ответ!*\n\n🔄 Попробуй еще раз!",
    "no_attempts": "😔 *Попытки закончились*\n\nИспользованы все 3 попытки.\n\n📞 Свяжись: @DedlyxBr",
    "timeout": "⏰ *Время вышло!*\n\nСессия проверки истекла.",
    "already_approved": "🌟 *Ты уже в канале!*\n\nПиши @DedlyxBr если нужна помощь.",
}

# Клавиатуры
def create_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="🚀 Начать проверку", callback_data="start_captcha")],
        [InlineKeyboardButton(text="📞 Связаться с админом", url="https://t.me/DedlyxBr")],
        [InlineKeyboardButton(text="ℹ️ Правила", callback_data="rules")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def create_captcha_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    # Цифры 1-9
    for i in range(1, 10):
        builder.button(text=str(i), callback_data=f"num_{i}")
    
    # Дополнительные кнопки
    builder.button(text="0", callback_data="num_0")
    builder.button(text="⌫ Удалить", callback_data="delete")
    builder.button(text="✅ Готово", callback_data="submit")
    builder.button(text="🔄 Новый вопрос", callback_data="refresh")
    builder.button(text="📝 Ввести текст", callback_data="text_input")
    builder.button(text="📞 Админ", url="https://t.me/DedlyxBr")
    
    builder.adjust(3, 3, 3, 2, 1, 1)
    return builder.as_markup()

def create_admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔍 Поиск пользователя", callback_data="admin_search")],
        [InlineKeyboardButton(text="📤 Экспорт данных", callback_data="admin_export")],
        [InlineKeyboardButton(text="🚪 Выйти из админки", callback_data="admin_exit")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== ОСНОВНАЯ ФУНКЦИОНАЛЬНОСТЬ КАПЧИ ====================

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    save_user_info(message.from_user)
    
    welcome_msg = (
        f"👋 *Привет, {message.from_user.first_name}!*\n\n"
        "🎉 *Добро пожаловать!*\n\n"
        "Чтобы получить доступ к закрытому каналу, необходимо пройти простую проверку.\n\n"
        "📋 *Что нужно сделать:*\n"
        "1️⃣ Нажми кнопку *«Начать проверку»*\n"
        "2️⃣ Ответь на простой вопрос\n"
        "3️⃣ Получи приглашение в канал\n\n"
        "⏱ *У тебя есть 5 минут и 3 попытки*"
    )
    
    await message.answer(
        welcome_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=create_main_keyboard()
    )

# Начало проверки капчи
@dp.callback_query(lambda c: c.data == "start_captcha")
async def start_captcha(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_name = callback.from_user.first_name
    
    logger.info(f"Начало проверки для {user_id} ({user_name})")
    
    # Проверяем, не прошел ли уже пользователь
    if user_id in approved_users:
        try:
            invite_link = await bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=datetime.now() + timedelta(hours=24)
            )
            
            await callback.message.answer(
                "✅ *Ты уже прошел проверку!*\n\nВот новая ссылка для входа:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🎪 Войти в канал", url=invite_link.invite_link)
                ]])
            )
        except Exception as e:
            await callback.message.answer(
                MESSAGES["already_approved"],
                parse_mode=ParseMode.MARKDOWN
            )
        await callback.answer()
        return
    
    # Генерируем новую капчу
    captcha_text, captcha_answer = generate_simple_captcha()
    
    # Сохраняем капчу
    active_captchas[user_id] = {
        'question': captcha_text,
        'answer': str(captcha_answer),
        'attempts': 3,
        'start_time': datetime.now(),
        'user_input': "",
        'message_id': None
    }
    
    # Отправляем сообщение с капчей
    try:
        captcha_message = await callback.message.answer(
            f"👤 *Пользователь:* {user_name}\n\n"
            f"🔐 *Проверка безопасности*\n\n"
            f"📝 *Вопрос:* *{captcha_text}*\n\n"
            f"✏️ *Введи ответ:*\n\n"
            f"⚠️ *Попыток осталось:* 3/3\n"
            f"⏱ *Время:* 5 минут",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=create_captcha_keyboard()
        )
        
        # Сохраняем ID сообщения
        active_captchas[user_id]['message_id'] = captcha_message.message_id
        await callback.answer("🔐 Проверка начата!")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке капчи: {e}")
        await callback.answer("❌ Ошибка! Попробуй снова.")
    
    try:
        await callback.message.delete()
    except:
        pass

# Обработка ввода цифр
@dp.callback_query(lambda c: c.data.startswith("num_"))
async def process_number(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_captchas:
        await callback.answer("❌ Сессия истекла! Нажми /start", show_alert=True)
        return
    
    # Проверяем время
    captcha_data = active_captchas[user_id]
    if datetime.now() - captcha_data['start_time'] > timedelta(minutes=5):
        del active_captchas[user_id]
        await callback.answer("⏰ Время вышло!", show_alert=True)
        await callback.message.edit_text(MESSAGES["timeout"], parse_mode=ParseMode.MARKDOWN)
        return
    
    # Получаем цифру
    digit = callback.data.split("_")[1]
    
    # Обновляем ввод
    captcha_data['user_input'] += digit
    
    # Обновляем сообщение
    await callback.message.edit_text(
        f"👤 *Пользователь:* {callback.from_user.first_name}\n\n"
        f"🔐 *Проверка безопасности*\n\n"
        f"📝 *Вопрос:* *{captcha_data['question']}*\n\n"
        f"✏️ *Твой ответ:* `{captcha_data['user_input']}`\n\n"
        f"⚠️ *Попыток осталось:* {captcha_data['attempts']}/3\n"
        f"⏱ *Осталось времени:* {5 - (datetime.now() - captcha_data['start_time']).seconds // 60} мин.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=callback.message.reply_markup
    )
    
    await callback.answer(f"Добавлено: {digit}")

# Удаление символа
@dp.callback_query(lambda c: c.data == "delete")
async def delete_char(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_captchas:
        await callback.answer("❌ Нет активной сессии", show_alert=True)
        return
    
    captcha_data = active_captchas[user_id]
    
    if captcha_data['user_input']:
        captcha_data['user_input'] = captcha_data['user_input'][:-1]
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"👤 *Пользователь:* {callback.from_user.first_name}\n\n"
            f"🔐 *Проверка безопасности*\n\n"
            f"📝 *Вопрос:* *{captcha_data['question']}*\n\n"
            f"✏️ *Твой ответ:* `{captcha_data['user_input']}`\n\n"
            f"⚠️ *Попыток осталось:* {captcha_data['attempts']}/3\n"
            f"⏱ *Осталось времени:* {5 - (datetime.now() - captcha_data['start_time']).seconds // 60} мин.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=callback.message.reply_markup
        )
        
        await callback.answer("🗑 Последний символ удален")
    else:
        await callback.answer("📭 Нечего удалять", show_alert=True)

# Отправка ответа на проверку
@dp.callback_query(lambda c: c.data == "submit")
async def submit_answer(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_captchas:
        await callback.answer("❌ Сессия истекта", show_alert=True)
        return
    
    captcha_data = active_captchas[user_id]
    
    if not captcha_data['user_input']:
        await callback.answer("✏️ Введи ответ сначала", show_alert=True)
        return
    
    user_answer = captcha_data['user_input'].strip().lower()
    correct_answer = captcha_data['answer'].lower()
    
    logger.info(f"Проверка ответа: {user_answer} vs {correct_answer} для {user_id}")
    
    # Проверяем ответ
    if user_answer == correct_answer:
        # УСПЕХ!
        await callback.message.edit_text(
            "🎯 *Проверяем ответ...*\n\n⏳ Создаем приглашение...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Добавляем пользователя
        approved_users.add(user_id)
        save_data()
        
        try:
            # Создаем приглашение
            invite_link = await bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                member_limit=1,
                expire_date=datetime.now() + timedelta(hours=24),
                name=f"Для {callback.from_user.first_name}"
            )
            
            # Отправляем успешное сообщение
            await callback.message.answer(
                "✅ *Поздравляем!*\n\nТы успешно прошел проверку!\n\n"
                "🎁 *Твоя награда:* приглашение в закрытый канал!\n\n"
                "Ссылка действительна 24 часа ⏳",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Отправляем ссылку
            await callback.message.answer(
                f"✨ *Приглашение отправлено!*\n\n"
                f"Нажми на ссылку ниже:\n\n"
                f"{invite_link.invite_link}\n\n"
                f"✅ Ссылка активна 24 часа",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🎪 Войти в канал", url=invite_link.invite_link),
                    InlineKeyboardButton(text="📞 Админ", url="https://t.me/DedlyxBr")
                ]])
            )
            
            logger.info(f"Пользователь {user_id} прошел проверку")
            
            # Уведомляем админа
            if user_id in ADMIN_IDS:  # Если это не сам админ
                for admin_id in ADMIN_IDS:
                    if admin_id != user_id:
                        try:
                            await bot.send_message(
                                admin_id,
                                f"✅ *Новый участник!*\n\n"
                                f"👤 *Имя:* {callback.from_user.full_name}\n"
                                f"🆔 *ID:* {user_id}\n"
                                f"📅 *Время:* {datetime.now().strftime('%H:%M:%S')}",
                                parse_mode=ParseMode.MARKDOWN
                            )
                        except Exception as e:
                            logger.error(f"Не удалось уведомить админа: {e}")
            
        except Exception as e:
            logger.error(f"Ошибка создания приглашения: {e}")
            await callback.message.answer(
                "⚠️ *Ошибка!*\n\nНе удалось создать приглашение.\n\n📞 Напиши @DedlyxBr",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="start_captcha")
                ]])
            )
        
        # Удаляем капчу
        if user_id in active_captchas:
            del active_captchas[user_id]
            
    else:
        # НЕПРАВИЛЬНЫЙ ОТВЕТ
        captcha_data['attempts'] -= 1
        
        if captcha_data['attempts'] > 0:
            # Новая капча
            new_question, new_answer = generate_simple_captcha()
            captcha_data['question'] = new_question
            captcha_data['answer'] = str(new_answer)
            captcha_data['user_input'] = ""
            
            await callback.message.edit_text(
                f"❌ *Неверный ответ!*\n\n"
                f"🔄 Попробуй еще раз!\n\n"
                f"📝 *Новый вопрос:* *{new_question}*\n\n"
                f"⚠️ *Попыток осталось:* {captcha_data['attempts']}/3",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=callback.message.reply_markup
            )
        else:
            # КОНЕЦ ПОПЫТОК
            await callback.message.edit_text(
                "😔 *Попытки закончились*\n\n"
                "Ты использовал все 3 попытки.\n\n"
                "🔄 Попробуй снова через 1 час\n"
                "📞 Или свяжись: @DedlyxBr",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="📞 Связаться с админом", url="https://t.me/DedlyxBr")
                ]])
            )
            if user_id in active_captchas:
                del active_captchas[user_id]
    
    await callback.answer()

# Обновление вопроса
@dp.callback_query(lambda c: c.data == "refresh")
async def refresh_question(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in active_captchas:
        await callback.answer("❌ Нет активной сессии", show_alert=True)
        return
    
    # Новая капча
    new_question, new_answer = generate_simple_captcha()
    captcha_data = active_captchas[user_id]
    captcha_data['question'] = new_question
    captcha_data['answer'] = str(new_answer)
    captcha_data['user_input'] = ""
    
    await callback.message.edit_text(
        f"🔄 *Вопрос обновлен!*\n\n"
        f"🔐 *Проверка безопасности*\n\n"
        f"📝 *Вопрос:* *{new_question}*\n\n"
        f"✏️ *Введи ответ:*\n\n"
        f"⚠️ *Попыток осталось:* {captcha_data['attempts']}/3\n"
        f"⏱ *Осталось времени:* {5 - (datetime.now() - captcha_data['start_time']).seconds // 60} мин.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=callback.message.reply_markup
    )
    
    await callback.answer("🔄 Вопрос обновлен!")

# Ввод текста (для слов)
@dp.callback_query(lambda c: c.data == "text_input")
async def text_input_mode(callback: types.CallbackQuery):
    await callback.answer(
        "✏️ Для ввода слов просто напиши ответ в чат!\n"
        "Например, если вопрос 'красный' - напиши 'красный'",
        show_alert=True
    )

# Обработка текстовых сообщений (для ввода слов)
@dp.message(F.text)
async def handle_text_input(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in active_captchas:
        return  # Игнорируем, если нет активной сессии
    
    captcha_data = active_captchas[user_id]
    
    # Проверяем время
    if datetime.now() - captcha_data['start_time'] > timedelta(minutes=5):
        del active_captchas[user_id]
        await message.answer(MESSAGES["timeout"], parse_mode=ParseMode.MARKDOWN)
        return
    
    # Используем введенный текст как ответ
    captcha_data['user_input'] = message.text.strip()
    
    # Обновляем сообщение с капчей
    try:
        if captcha_data['message_id']:
            await bot.edit_message_text(
                chat_id=user_id,
                message_id=captcha_data['message_id'],
                text=f"👤 *Пользователь:* {message.from_user.first_name}\n\n"
                     f"🔐 *Проверка безопасности*\n\n"
                     f"📝 *Вопрос:* *{captcha_data['question']}*\n\n"
                     f"✏️ *Твой ответ:* `{captcha_data['user_input']}`\n\n"
                     f"⚠️ *Попыток осталось:* {captcha_data['attempts']}/3\n"
                     f"⏱ *Осталось времени:* {5 - (datetime.now() - captcha_data['start_time']).seconds // 60} мин.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=create_captcha_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка обновления сообщения: {e}")
    
    await message.delete()

# Правила
@dp.callback_query(lambda c: c.data == "rules")
async def show_rules(callback: types.CallbackQuery):
    rules_text = (
        "📜 *Правила проверки:*\n\n"
        "1. ✅ Одна проверка — одно приглашение\n"
        "2. ⏱ На проверку дается 5 минут\n"
        "3. 🔄 3 попытки на решение\n"
        "4. 🚫 Запрещено использовать ботов\n\n"
        
        "💡 *Примеры вопросов:*\n"
        "• `5 + 3` → ответ `8`\n"
        "• `красный` → ответ `красный`\n"
        "• `123` → ответ `123`\n\n"
        
        "❓ *Вопросы?* Пиши @DedlyxBr"
    )
    
    await callback.message.answer(
        rules_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Начать проверку", callback_data="start_captcha"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")
        ]])
    )
    
    await callback.answer()

# Возврат к началу
@dp.callback_query(lambda c: c.data == "back_to_start")
async def back_to_start(callback: types.CallbackQuery):
    user_name = callback.from_user.first_name
    welcome_msg = (
        f"👋 *Привет, {user_name}!*\n\n"
        "🎉 *Добро пожаловать!*\n\n"
        "Чтобы получить доступ к закрытому каналу, необходимо пройти простую проверку.\n\n"
        "📋 *Что нужно сделать:*\n"
        "1️⃣ Нажми кнопку *«Начать проверку»*\n"
        "2️⃣ Ответь на простой вопрос\n"
        "3️⃣ Получи приглашение в канал\n\n"
        "⏱ *У тебя есть 5 минут и 3 попытки*"
    )
    
    await callback.message.edit_text(
        welcome_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=create_main_keyboard()
    )

# ==================== АДМИН-ПАНЕЛЬ ====================

# Проверка админа
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Команда /admin
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав администратора!")
        return
    
    admin_text = (
        "⚙️ *Админ-панель*\n\n"
        f"👑 Админ: {message.from_user.full_name}\n"
        f"🆔 ID: {user_id}\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        admin_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=create_admin_keyboard()
    )

# Статистика
@dp.callback_query(lambda c: c.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав!")
        return
    
    now = datetime.now()
    new_24h = 0
    new_7d = 0
    
    for data in user_data.values():
        first_seen = datetime.fromisoformat(data['first_seen'])
        days_diff = (now - first_seen).days
        
        if days_diff <= 1:
            new_24h += 1
        if days_diff <= 7:
            new_7d += 1
    
    stats_text = (
        f"📊 *Статистика бота*\n\n"
        f"• 👥 Всего пользователей: `{len(user_data)}`\n"
        f"• ✅ Одобрено: `{len(approved_users)}`\n"
        f"• 🔐 Активные проверки: `{len(active_captchas)}`\n"
        f"• 📅 Новые за 24ч: `{new_24h}`\n"
        f"• 📈 Новые за 7д: `{new_7d}`\n\n"
        f"🔄 Обновлено: `{now.strftime('%H:%M:%S')}`"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        stats_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )
    await callback.answer()

# Возврат в админку
@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    admin_text = (
        "⚙️ *Админ-панель*\n\n"
        f"👑 Админ: {callback.from_user.full_name}\n"
        f"🆔 ID: {callback.from_user.id}\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        admin_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=create_admin_keyboard()
    )
    await callback.answer()

# Остальные функции админки (рассылка, поиск и т.д.)
# ... [код из предыдущего сообщения для админ-панели]
# Для экономии места, добавьте сюда функции админ-панели из предыдущего кода

# ==================== ОБРАБОТКА ЗАЯВОК ====================

@dp.chat_join_request()
async def handle_join_request(join_request: types.ChatJoinRequest):
    user_id = join_request.from_user.id
    save_user_info(join_request.from_user)
    
    logger.info(f"Новая заявка от {join_request.from_user.full_name} (ID: {user_id})")
    
    if user_id in approved_users:
        try:
            await join_request.approve()
            await bot.send_message(
                user_id,
                "🎉 *Добро пожаловать!*\n\nТвоя заявка одобрена автоматически!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Ошибка при одобрении {user_id}: {e}")
    else:
        try:
            await bot.send_message(
                user_id,
                f"👋 *Привет, {join_request.from_user.first_name}!*\n\n"
                "Чтобы вступить в закрытый канал, нужно пройти быструю проверку.\n\n"
                "📲 *Нажми кнопку ниже:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🚀 Начать проверку", callback_data="start_captcha")
                ]])
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение {user_id}: {e}")

# ==================== ОЧИСТКА ====================

async def cleanup_task():
    while True:
        await asyncio.sleep(300)
        now = datetime.now()
        expired = []
        
        for user_id, data in active_captchas.items():
            if now - data['start_time'] > timedelta(minutes=5):
                expired.append(user_id)
        
        for user_id in expired:
            try:
                await bot.send_message(
                    user_id,
                    "⏰ *Время вышло!*\n\nСессия проверки истекла.\n\n🔄 Нажми /start чтобы начать заново.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            del active_captchas[user_id]
        
        if expired:
            logger.info(f"Очищено {len(expired)} устаревших сессий")

# ==================== ЗАПУСК ====================

async def main():
    load_data()
    asyncio.create_task(cleanup_task())
    
    bot_info = await bot.get_me()
    logger.info("=" * 50)
    logger.info(f"🤖 Бот запущен: @{bot_info.username}")
    logger.info(f"👑 Админы: {ADMIN_IDS}")
    logger.info(f"👥 Пользователей: {len(user_data)}")
    logger.info(f"✅ Одобрено: {len(approved_users)}")
    logger.info("=" * 50)
    
    try:
        await dp.start_polling(bot)
    finally:
        save_data()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())