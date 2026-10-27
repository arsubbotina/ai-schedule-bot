#!/usr/bin/env python3
"""
🤖 AI АГЕНТ ДЛЯ УПРАВЛЕНИЯ РАСПИСАНИЕМ
Telegram бот для управления расписанием занятий с AI-аналитикой
"""

import os
import ssl
import sqlite3
import logging
from datetime import datetime, timedelta
import html
from typing import Dict, List, Optional, Tuple
import json
import base64
import uuid

import httpx
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ============================
# КОНФИГУРАЦИЯ
# ============================

# Токен бота и API ключ
BOT_TOKEN = os.environ["BOT_TOKEN"]
GIGACHAT_API_KEY = os.environ["GIGACHAT_API_KEY"]

# Путь к базе данных
DB_PATH = os.getenv("SCHEDULE_DB_PATH", "schedule_bot.db")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================
# РАБОТА С БАЗОЙ ДАННЫХ
# ============================

def init_db():
    """Инициализация базы данных."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица расписания
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day_of_week TEXT,
            start_time TEXT,
            end_time TEXT,
            subject_name TEXT,
            subject_type TEXT,
            classroom TEXT,
            teacher TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица уведомлений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            enabled BOOLEAN DEFAULT 1,
            notify_before INTEGER DEFAULT 15,
            last_notified DATE,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица дедлайнов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            description TEXT,
            deadline_date DATE,
            deadline_time TEXT,
            subject_name TEXT,
            priority TEXT DEFAULT 'medium',
            completed BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    # Таблица предпочтений пользователя
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            preferred_start_time TEXT,
            preferred_end_time TEXT,
            max_classes_per_day INTEGER DEFAULT 4,
            preferred_days TEXT,
            productivity_periods TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")


def check_db_structure():
    """Проверка структуры базы данных."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        expected_tables = ['users', 'schedule', 'notifications', 'deadlines', 'user_preferences']
        existing_tables = [table[0] for table in tables]

        for table in expected_tables:
            if table not in existing_tables:
                logger.error(f"❌ Таблица {table} отсутствует в базе данных")
                conn.close()
                return False

        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке структуры БД: {e}")
        return False


def register_user(user_id: int, username: str = None,
                  first_name: str = None, last_name: str = None):
    """Регистрация нового пользователя."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name))

        cursor.execute('''
            INSERT OR IGNORE INTO notifications (user_id)
            VALUES (?)
        ''', (user_id,))

        conn.commit()
        conn.close()
        logger.info(f"👤 Пользователь {user_id} зарегистрирован")
    except Exception as e:
        logger.error(f"❌ Ошибка при регистрации пользователя {user_id}: {e}")


# ============================
# ФУНКЦИИ ДЛЯ РАБОТЫ С РАСПИСАНИЕМ
# ============================

def add_schedule_item(user_id: int, day_of_week: str, start_time: str,
                      end_time: str, subject_name: str, subject_type: str,
                      classroom: str = None, teacher: str = None) -> bool:
    """Добавление занятия в расписание."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO schedule
            (user_id, day_of_week, start_time, end_time, subject_name, subject_type, classroom, teacher)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, day_of_week, start_time, end_time,
              subject_name, subject_type, classroom, teacher))

        conn.commit()
        conn.close()
        logger.info(f"📝 Добавлено занятие для пользователя {user_id}: {subject_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении занятия: {e}")
        return False


def get_schedule_for_day(user_id: int, day_of_week: str) -> List[Dict]:
    """Получение расписания на конкретный день."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM schedule
            WHERE user_id = ? AND day_of_week = ?
            ORDER BY start_time
        ''', (user_id, day_of_week))

        schedule = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return schedule
    except Exception as e:
        logger.error(f"❌ Ошибка при получении расписания: {e}")
        return []


def get_schedule_for_week(user_id: int) -> Dict[str, List[Dict]]:
    """Получение расписания на всю неделю."""
    days = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']
    schedule = {}

    for day in days:
        schedule[day] = get_schedule_for_day(user_id, day)

    return schedule


def delete_schedule_item(user_id: int, item_id: int) -> bool:
    """Удаление занятия из расписания."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM schedule
            WHERE id = ? AND user_id = ?
        ''', (item_id, user_id))

        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if deleted:
            logger.info(f"🗑️ Удалено занятие {item_id} для пользователя {user_id}")
        return deleted
    except Exception as e:
        logger.error(f"❌ Ошибка при удалении занятия: {e}")
        return False


def get_all_subjects(user_id: int) -> List[Dict]:
    """Получение списка всех предметов."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT DISTINCT subject_name, subject_type, classroom, teacher
            FROM schedule
            WHERE user_id = ?
            ORDER BY subject_name
        ''', (user_id,))

        subjects = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return subjects
    except Exception as e:
        logger.error(f"❌ Ошибка при получении предметов: {e}")
        return []


# ============================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ДЕДЛАЙНАМИ
# ============================

def add_deadline(user_id: int, title: str, description: str,
                 deadline_date: str, deadline_time: str = None,
                 subject_name: str = None, priority: str = 'medium') -> bool:
    """Добавление дедлайна."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO deadlines
            (user_id, title, description, deadline_date, deadline_time, subject_name, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, title, description, deadline_date, deadline_time, subject_name, priority))

        conn.commit()
        conn.close()
        logger.info(f"⏰ Добавлен дедлайн для пользователя {user_id}: {title}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении дедлайна: {e}")
        return False


def get_upcoming_deadlines(user_id: int, days_ahead: int = 7) -> List[Dict]:
    """Получение предстоящих дедлайнов."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM deadlines
            WHERE user_id = ?
            AND deadline_date >= date('now')
            AND deadline_date <= date('now', ?)
            AND completed = 0
            ORDER BY deadline_date, deadline_time
        ''', (user_id, f'+{days_ahead} days'))

        deadlines = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return deadlines
    except Exception as e:
        logger.error(f"❌ Ошибка при получении дедлайнов: {e}")
        return []


def complete_deadline(user_id: int, deadline_id: int) -> bool:
    """Отметка дедлайна как выполненного."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE deadlines
            SET completed = 1
            WHERE id = ? AND user_id = ?
        ''', (deadline_id, user_id))

        updated = cursor.rowcount > 0
        conn.commit()
        conn.close()

        if updated:
            logger.info(f"✅ Дедлайн {deadline_id} отмечен как выполненный")
        return updated
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении дедлайна: {e}")
        return False


def get_user_preferences(user_id: int) -> Dict:
    """Получение предпочтений пользователя."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM user_preferences WHERE user_id = ?
        ''', (user_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        else:
            return {}
    except Exception as e:
        logger.error(f"❌ Ошибка при получении предпочтений: {e}")
        return {}


def save_user_preferences(user_id: int, preferences: Dict) -> bool:
    """Сохранение предпочтений пользователя."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('DELETE FROM user_preferences WHERE user_id = ?', (user_id,))

        cursor.execute('''
            INSERT INTO user_preferences
            (user_id, preferred_start_time, preferred_end_time, max_classes_per_day, preferred_days, productivity_periods)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            preferences.get('preferred_start_time'),
            preferences.get('preferred_end_time'),
            preferences.get('max_classes_per_day', 4),
            json.dumps(preferences.get('preferred_days', [])),
            json.dumps(preferences.get('productivity_periods', []))
        ))

        conn.commit()
        conn.close()
        logger.info(f"💾 Сохранены предпочтения для пользователя {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении предпочтений: {e}")
        return False


# ============================
# AI ИНТЕГРАЦИЯ (GIGACHAT) - ИСПРАВЛЕННАЯ ВЕРСИЯ
# ============================

async def call_gigachat_api(prompt: str) -> str:
    """Вызов API GigaChat."""
    try:
        # Проверяем и декодируем API ключ
        try:
            # API ключ должен быть в формате client_id:client_secret в base64
            decoded_key = base64.b64decode(GIGACHAT_API_KEY).decode('utf-8')
            client_id, client_secret = decoded_key.split(':')
        except Exception as e:
            logger.error(f"❌ Ошибка декодирования API ключа: {e}")
            return "❌ Неверный формат API ключа. Проверьте правильность ключа."

        # Шаг 1: Получение токена доступа
        auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

        # Создаем Basic Auth заголовок из client_id:client_secret
        auth_string = f"{client_id}:{client_secret}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "scope": "GIGACHAT_API_PERS"
        }

        async with httpx.AsyncClient(verify=ssl.create_default_context(cafile=os.getenv("SSL_CERT_FILE") or None)) as client:
            # Получаем токен
            auth_response = await client.post(
                auth_url,
                headers=headers,
                data=data,
                timeout=30.0
            )

            if auth_response.status_code != 200:
                logger.error(f"❌ Ошибка авторизации: {auth_response.status_code}")
                return "❌ Ошибка подключения к AI-системе. Проверьте API ключ."

            access_token = auth_response.json().get("access_token")

            if not access_token:
                return "❌ Не удалось получить токен доступа"

            # Шаг 2: Отправляем запрос к GigaChat API
            api_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
            api_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }

            api_data = {
                "model": "GigaChat",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }

            api_response = await client.post(
                api_url,
                headers=api_headers,
                json=api_data,
                timeout=30.0
            )

            if api_response.status_code != 200:
                logger.error(f"❌ Ошибка API: {api_response.status_code}")
                return "❌ Ошибка при анализе данных."

            result = api_response.json()
            return result["choices"][0]["message"]["content"]

    except httpx.TimeoutException:
        logger.error("⏰ Таймаут при подключении к GigaChat API")
        return "❌ Превышено время ожидания ответа от AI-системы."
    except httpx.HTTPError as e:
        logger.error(f"🌐 HTTP ошибка: {e}")
        return "❌ Ошибка подключения к AI-системе."
    except Exception as e:
        logger.error(f"🤖 AI ошибка: {e}")
        return f"❌ Ошибка AI-системы: {str(e)}"


async def analyze_schedule_with_ai(user_id: int) -> str:
    """Анализ расписания с помощью AI."""
    try:
        schedule = get_schedule_for_week(user_id)

        if not any(schedule.values()):
            return "📭 Ваше расписание пусто. Добавьте занятия для анализа."

        schedule_summary = ""
        for day, classes in schedule.items():
            if classes:
                schedule_summary += f"{day}:\n"
                for cls in classes:
                    schedule_summary += f"  - {cls['start_time']}-{cls['end_time']}: {cls['subject_name']} ({cls['subject_type']})\n"

        prompt = f"""
        Проанализируй учебное расписание студента и дай рекомендации:

        Расписание на неделю:
        {schedule_summary}

        Проанализируй и дай рекомендации по:
        1. Равномерности распределения нагрузки по дням
        2. Плотности занятий в каждый день
        3. Возможным перегрузкам
        4. Рекомендации по оптимизации расписания
        5. Советы по тайм-менеджменту

        Ответ дай на русском языке, структурированно и конкретно.
        Будь дружелюбным и поддерживающим.
        """

        ai_response = await call_gigachat_api(prompt)
        return ai_response

    except Exception as e:
        logger.error(f"❌ Ошибка при анализе расписания AI: {e}")
        return "Не удалось проанализировать расписание. Попробуйте позже."


async def analyze_deadlines_with_ai(user_id: int) -> str:
    """Анализ дедлайнов с помощью AI."""
    try:
        deadlines = get_upcoming_deadlines(user_id, 30)

        if not deadlines:
            return "🎉 У вас нет предстоящих дедлайнов. Добавьте их для анализа."

        deadlines_summary = ""
        for i, dl in enumerate(deadlines, 1):
            time_str = f" в {dl['deadline_time']}" if dl['deadline_time'] else ""
            deadlines_summary += f"{i}. {dl['title']} - {dl['deadline_date']}{time_str} ({dl['priority']} приоритет)\n"

        prompt = f"""
        Проанализируй список дедлайнов студента и дай рекомендации:

        Дедлайны (ближайшие 30 дней):
        {deadlines_summary}

        Проанализируй и дай рекомендации по:
        1. Распределению дедлайнов по времени
        2. Приоритетности задач
        3. Планированию выполнения каждого дедлайна
        4. Советы по избежанию прокрастинации
        5. Рекомендации по расстановке приоритетов

        Ответ дай на русском языке, структурированно и конкретно.
        Будь дружелюбным и поддерживающим.
        """

        ai_response = await call_gigachat_api(prompt)
        return ai_response

    except Exception as e:
        logger.error(f"❌ Ошибка при анализе дедлайнов AI: {e}")
        return "Не удалось проанализировать дедлайны. Попробуйте позже."


async def create_optimized_schedule_with_ai(user_id: int, preferences: str) -> str:
    """Создание оптимизированного расписания с учетом предпочтений."""
    try:
        current_schedule = get_schedule_for_week(user_id)

        current_summary = ""
        for day, classes in current_schedule.items():
            if classes:
                current_summary += f"{day}:\n"
                for cls in classes:
                    current_summary += f"  - {cls['start_time']}-{cls['end_time']}: {cls['subject_name']}\n"

        prompt = f"""
        Создай оптимизированное учебное расписание на основе:

        Текущее расписание:
        {current_summary if current_summary else "Расписание пустое"}

        Предпочтения пользователя:
        {preferences}

        Учти следующие факторы:
        1. Равномерное распределение нагрузки в течение недели
        2. Время для отдыха и перерывов между занятиями
        3. Подготовку к экзаменам/дедлайнам
        4. Личные предпочтения пользователя
        5. Оптимальное время для сложных предметов

        Предложи конкретное расписание по дням недели с временными слотами.

        Ответ дай на русском языке, структурированно.
        Будь креативным и практичным в своих рекомендациях.
        """

        ai_response = await call_gigachat_api(prompt)
        return ai_response

    except Exception as e:
        logger.error(f"❌ Ошибка при создании расписания AI: {e}")
        return "Не удалось создать оптимизированное расписание. Попробуйте позже."


async def get_time_management_recommendations(user_id: int) -> str:
    """Получение рекомендаций по тайм-менеджменту."""
    try:
        schedule = get_schedule_for_week(user_id)
        deadlines = get_upcoming_deadlines(user_id, 30)
        preferences = get_user_preferences(user_id)

        prompt = f"""
        На основе следующей информации о студенте дай персональные рекомендации по тайм-менеджменту:

        Текущее расписание:
        {json.dumps(schedule, ensure_ascii=False, indent=2) if any(schedule.values()) else "Расписание пустое"}

        Предстоящие дедлайны:
        {json.dumps(deadlines, ensure_ascii=False, indent=2) if deadlines else "Нет дедлайнов"}

        Предпочтения пользователя:
        {json.dumps(preferences, ensure_ascii=False, indent=2) if preferences else "Предпочтения не указаны"}

        Дай конкретные рекомендации по:
        1. Оптимальному распределению времени
        2. Методам борьбы с прокрастинацией
        3. Техникам концентрации
        4. Балансу учебы и отдыха
        5. Планированию подготовки

        Ответ дай на русском языке, структурированно и конкретно.
        Будь мотивирующим и практичным.
        """

        recommendations = await call_gigachat_api(prompt)
        return recommendations

    except Exception as e:
        logger.error(f"❌ Ошибка при получении рекомендаций: {e}")
        return "Не удалось получить рекомендации. Попробуйте позже."


# ============================
# ФОРМАТИРОВАНИЕ ТЕКСТА (HTML)
# ============================

def format_schedule(schedule: List[Dict]) -> str:
    """Форматирование расписания в текст с HTML разметкой."""
    if not schedule:
        return "📭 На этот день занятий нет."

    current_day = None
    result = ""
    for item in schedule:
        day = item['day_of_week']
        if day != current_day:
            if current_day is not None:
                result += "\n"
            current_day = day
            result += f"<b>📅 {html.escape(day.capitalize())}</b>\n\n"

        start_time = html.escape(item['start_time'])
        end_time = html.escape(item['end_time'])
        subject_name = html.escape(item['subject_name'])
        subject_type = html.escape(item['subject_type'])
        classroom = html.escape(item['classroom']) if item['classroom'] else "не указана"
        teacher = html.escape(item['teacher']) if item['teacher'] else "не указан"

        result += f"⏰ <b>{start_time} - {end_time}</b>\n"
        result += f"📚 <i>{subject_name}</i>\n"
        result += f"🎓 {subject_type}\n"
        result += f"🏫 Аудитория: {classroom}\n"
        result += f"👨‍🏫 Преподаватель: {teacher}\n\n"

    return result


def format_deadlines(deadlines: List[Dict]) -> str:
    """Форматирование списка дедлайнов."""
    if not deadlines:
        return "🎉 Нет предстоящих дедлайнов."

    result = "<b>📅 Предстоящие дедлайны:</b>\n\n"
    for i, deadline in enumerate(deadlines, 1):
        title = html.escape(deadline['title'])
        description = html.escape(deadline['description']) if deadline['description'] else "нет описания"
        date = deadline['deadline_date']
        time = f" в {deadline['deadline_time']}" if deadline['deadline_time'] else ""
        priority = deadline['priority']

        priority_emoji = {
            'high': '🔴',
            'medium': '🟡',
            'low': '🟢'
        }.get(priority, '⚪')

        result += f"{priority_emoji} <b>{i}. {title}</b>\n"
        result += f"   📝 {description}\n"
        result += f"   📅 {date}{time}\n"
        if deadline['subject_name']:
            result += f"   📚 Предмет: {html.escape(deadline['subject_name'])}\n"
        result += f"   🔢 ID: {deadline['id']}\n\n"

    return result


# ============================
# КРАСИВЫЕ КЛАВИАТУРЫ
# ============================

def get_main_keyboard():
    """Основная клавиатура."""
    keyboard = [
        [KeyboardButton("📅 Сегодня"), KeyboardButton("📅 Завтра")],
        [KeyboardButton("📋 Неделя"), KeyboardButton("➕ Добавить занятие")],
        [KeyboardButton("⏰ Добавить дедлайн"), KeyboardButton("📚 Мои предметы")],
        [KeyboardButton("🗑️ Удалить"), KeyboardButton("🤖 AI Анализ")],
        [KeyboardButton("🔔 Уведомления"), KeyboardButton("🎯 Мои предпочтения")],
        [KeyboardButton("❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, input_field_placeholder="Выберите действие...")


def get_ai_keyboard():
    """Клавиатура для AI функций."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Анализ расписания", callback_data="ai_analyze_schedule"),
            InlineKeyboardButton("📈 Анализ дедлайнов", callback_data="ai_analyze_deadlines")
        ],
        [
            InlineKeyboardButton("✨ Оптимизировать расписание", callback_data="ai_optimize_schedule"),
            InlineKeyboardButton("🎯 Рекомендации", callback_data="ai_time_management")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_days_keyboard(action: str = "view"):
    """Клавиатура с днями недели."""
    days = [
        ["Понедельник", "Вторник", "Среда"],
        ["Четверг", "Пятница", "Суббота"],
        ["Воскресенье", "⬅️ Назад"]
    ]

    keyboard = []
    for row in days:
        keyboard_row = []
        for day in row:
            if day == "⬅️ Назад":
                callback_data = "back_to_main"
            else:
                callback_data = f"{action}_day:{day.lower()}"
            keyboard_row.append(InlineKeyboardButton(day, callback_data=callback_data))
        keyboard.append(keyboard_row)

    return InlineKeyboardMarkup(keyboard)


def get_subject_type_keyboard():
    """Клавиатура для выбора типа занятия."""
    types = [
        ["📚 Лекция", "✏️ Практика", "🔬 Лабораторная"],
        ["💬 Семинар", "📝 Экзамен", "👨‍🏫 Консультация"],
        ["✅ Зачет", "📖 Самостоятельная", "⬅️ Назад"]
    ]

    keyboard = []
    for row in types:
        keyboard_row = []
        for type_ in row:
            if type_ == "⬅️ Назад":
                callback_data = "back_to_add"
            else:
                clean_type = type_.split(" ", 1)[1] if " " in type_ else type_
                callback_data = f"select_type:{clean_type}"
            keyboard_row.append(InlineKeyboardButton(type_, callback_data=callback_data))
        keyboard.append(keyboard_row)

    return InlineKeyboardMarkup(keyboard)


def get_priority_keyboard():
    """Клавиатура для выбора приоритета дедлайна."""
    keyboard = [
        [
            InlineKeyboardButton("🔴 Высокий", callback_data="priority:high"),
            InlineKeyboardButton("🟡 Средний", callback_data="priority:medium")
        ],
        [
            InlineKeyboardButton("🟢 Низкий", callback_data="priority:low"),
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_add_deadline")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_preferences_keyboard():
    """Клавиатура для настроек предпочтений."""
    keyboard = [
        [
            InlineKeyboardButton("⏰ Время занятий", callback_data="pref_time"),
            InlineKeyboardButton("📅 Предпочтительные дни", callback_data="pref_days")
        ],
        [
            InlineKeyboardButton("⚡ Периоды продуктивности", callback_data="pref_productivity"),
            InlineKeyboardButton("📊 Макс. занятия в день", callback_data="pref_max_classes")
        ],
        [
            InlineKeyboardButton("👀 Мои предпочтения", callback_data="pref_view"),
            InlineKeyboardButton("🔄 Сбросить", callback_data="pref_reset")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


# ============================
# ОБРАБОТЧИКИ КОМАНД
# ============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    user_id = user.id

    register_user(user_id, user.username, user.first_name, user.last_name)

    if not check_db_structure():
        await update.message.reply_text(
            "❌ <b>Ошибка базы данных. Пожалуйста, перезапустите бота.</b>",
            parse_mode=ParseMode.HTML
        )
        return

    welcome_text = (
        f"👋 <b>Привет, {html.escape(user.first_name or 'друг')}!</b>\n\n"
        "Я твой персональный ИИ-помощник для управления учебным расписанием и дедлайнами.\n\n"
        "🌟 <b>Что я умею:</b>\n"
        "• 📅 Управление расписанием занятий\n"
        "• ⏰ Отслеживание дедлайнов и экзаменов\n"
        "• 🤖 AI-анализ учебной нагрузки\n"
        "• 🎯 Персональные рекомендации\n"
        "• 🔔 Умные напоминания\n\n"
        "Используй кнопки ниже или команду /help для получения справки."
    )

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help."""
    help_text = (
        "📚 <b>Справка по командам:</b>\n\n"
        "<b>Основные команды:</b>\n"
        "• /start - Начать работу\n"
        "• /help - Эта справка\n"
        "• /week - Расписание на неделю\n"
        "• /today - Расписание на сегодня\n"
        "• /tomorrow - Расписание на завтра\n"
        "• /deadlines - Предстоящие дедлайны\n\n"
        "<b>Управление расписанием:</b>\n"
        "• /add - Добавить занятие\n"
        "• /delete - Удалить занятие\n"
        "• /subjects - Список предметов\n\n"
        "<b>AI функции:</b>\n"
        "• /analyze - AI-анализ нагрузки\n"
        "• /optimize - Оптимизация расписания\n"
        "• /recommend - Рекомендации\n\n"
        "💡 <i>Также можно использовать кнопки меню</i>"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /week."""
    user_id = update.effective_user.id
    schedule = get_schedule_for_week(user_id)

    if any(schedule.values()):
        keyboard = get_days_keyboard("view")
        await update.message.reply_text(
            "📅 <b>Выберите день для просмотра:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "📭 Ваше расписание пусто. Добавьте занятия через меню '➕ Добавить занятие'",
            parse_mode=ParseMode.HTML
        )


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /today."""
    user_id = update.effective_user.id

    today_english = datetime.now().strftime("%A").lower()
    day_map = {
        'monday': 'понедельник',
        'tuesday': 'вторник',
        'wednesday': 'среда',
        'thursday': 'четверг',
        'friday': 'пятница',
        'saturday': 'суббота',
        'sunday': 'воскресенье'
    }

    russian_day = day_map.get(today_english, 'понедельник')
    schedule = get_schedule_for_day(user_id, russian_day)

    if schedule:
        schedule_text = f"<b>📅 Расписание на сегодня ({russian_day}):</b>\n\n"
        schedule_text += format_schedule(schedule)
    else:
        schedule_text = f"🎉 Сегодня ({russian_day}) занятий нет!"

    # Добавляем информацию о дедлайнах на сегодня
    deadlines_today = []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM deadlines
            WHERE user_id = ? AND deadline_date = date('now') AND completed = 0
            ORDER BY deadline_time
        ''', (user_id,))
        deadlines_today = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка при получении дедлайнов: {e}")

    if deadlines_today:
        schedule_text += "\n\n<b>⏰ Дедлайны на сегодня:</b>\n"
        for deadline in deadlines_today:
            time = f" в {deadline['deadline_time']}" if deadline['deadline_time'] else ""
            schedule_text += f"• {html.escape(deadline['title'])}{time}\n"

    await update.message.reply_text(schedule_text, parse_mode=ParseMode.HTML)


async def tomorrow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /tomorrow."""
    user_id = update.effective_user.id

    tomorrow_english = (datetime.now() + timedelta(days=1)).strftime("%A").lower()
    day_map = {
        'monday': 'понедельник',
        'tuesday': 'вторник',
        'wednesday': 'среда',
        'thursday': 'четверг',
        'friday': 'пятница',
        'saturday': 'суббота',
        'sunday': 'воскресенье'
    }

    russian_day = day_map.get(tomorrow_english, 'понедельник')
    schedule = get_schedule_for_day(user_id, russian_day)

    if schedule:
        schedule_text = f"<b>📅 Расписание на завтра ({russian_day}):</b>\n\n"
        schedule_text += format_schedule(schedule)
    else:
        schedule_text = f"🎉 Завтра ({russian_day}) занятий нет!"

    # Добавляем информацию о дедлайнах на завтра
    deadlines_tomorrow = []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM deadlines
            WHERE user_id = ? AND deadline_date = date('now', '+1 day') AND completed = 0
            ORDER BY deadline_time
        ''', (user_id,))
        deadlines_tomorrow = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logger.error(f"❌ Ошибка при получении дедлайнов: {e}")

    if deadlines_tomorrow:
        schedule_text += "\n\n<b>⏰ Дедлайны на завтра:</b>\n"
        for deadline in deadlines_tomorrow:
            time = f" в {deadline['deadline_time']}" if deadline['deadline_time'] else ""
            schedule_text += f"• {html.escape(deadline['title'])}{time}\n"

    await update.message.reply_text(schedule_text, parse_mode=ParseMode.HTML)


async def deadlines_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /deadlines."""
    user_id = update.effective_user.id
    deadlines = get_upcoming_deadlines(user_id, 30)

    if deadlines:
        deadlines_text = format_deadlines(deadlines)
    else:
        deadlines_text = "🎉 У вас нет предстоящих дедлайнов на ближайшие 30 дней!"

    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить дедлайн", callback_data="add_deadline"),
            InlineKeyboardButton("✅ Отметить выполненным", callback_data="complete_deadline_menu")
        ],
        [
            InlineKeyboardButton("🤖 AI Анализ дедлайнов", callback_data="ai_analyze_deadlines")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
        ]
    ]

    await update.message.reply_text(
        deadlines_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ai_analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /analyze."""
    await update.message.reply_text(
        "🤖 <b>Выберите тип AI-анализа:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_keyboard()
    )


async def preferences_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /preferences."""
    await update.message.reply_text(
        "🎯 <b>Настройка ваших предпочтений</b>\n\n"
        "Укажите ваши предпочтения, чтобы я мог создать для вас оптимальное расписание:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_preferences_keyboard()
    )


# ============================
# ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ
# ============================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений."""
    text = update.message.text
    user_id = update.effective_user.id

    # Обработка кнопок главного меню
    if text == "📅 Сегодня":
        await today_command(update, context)
    elif text == "📅 Завтра":
        await tomorrow_command(update, context)
    elif text == "📋 Неделя":
        await week_command(update, context)
    elif text == "➕ Добавить занятие":
        await start_adding_schedule(update, context)
    elif text == "⏰ Добавить дедлайн":
        await start_adding_deadline(update, context)
    elif text == "📚 Мои предметы":
        await subjects_command(update, context)
    elif text == "🗑️ Удалить":
        await delete_command(update, context)
    elif text == "🤖 AI Анализ":
        await ai_analyze_command(update, context)
    elif text == "🔔 Уведомления":
        await notify_command(update, context)
    elif text == "🎯 Мои предпочтения":
        await preferences_command(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)

    # Обработка добавления занятия
    elif context.user_data.get('adding_schedule'):
        await handle_schedule_addition(update, context, text)

    # Обработка добавления дедлайна
    elif context.user_data.get('adding_deadline'):
        await handle_deadline_addition(update, context, text)

    # Обработка настроек предпочтений
    elif context.user_data.get('setting_preferences'):
        await handle_preferences_setting(update, context, text)

    # Обработка ожидания предпочтений для оптимизации
    elif context.user_data.get('awaiting_optimization_prefs'):
        await handle_optimization_preferences(update, context, text)


async def start_adding_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса добавления занятия."""
    context.user_data['adding_schedule'] = True
    context.user_data['step'] = 1

    await update.message.reply_text(
        "📝 <b>Добавление нового занятия</b>\n\n"
        "Шаг 1/6: Введите название предмета:",
        parse_mode=ParseMode.HTML
    )


async def start_adding_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса добавления дедлайна."""
    context.user_data['adding_deadline'] = True
    context.user_data['step'] = 1

    await update.message.reply_text(
        "⏰ <b>Добавление нового дедлайна</b>\n\n"
        "Шаг 1/5: Введите название дедлайна:",
        parse_mode=ParseMode.HTML
    )


async def handle_schedule_addition(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обработка добавления занятия."""
    user_id = update.effective_user.id
    step = context.user_data.get('step', 1)

    if step == 1:  # Название предмета
        context.user_data['subject_name'] = text
        context.user_data['step'] = 2

        await update.message.reply_text(
            "Шаг 2/6: Выберите тип занятия:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_subject_type_keyboard()
        )

    elif step == 3:  # Время начала
        if not validate_time(text):
            await update.message.reply_text(
                "❌ Неверный формат времени. Используйте ЧЧ:ММ (например, 09:30):"
            )
            return

        context.user_data['start_time'] = text
        context.user_data['step'] = 4

        await update.message.reply_text(
            "Шаг 4/6: Введите время окончания (ЧЧ:ММ):"
        )

    elif step == 4:  # Время окончания
        if not validate_time(text):
            await update.message.reply_text(
                "❌ Неверный формат времени. Используйте ЧЧ:ММ (например, 11:00):"
            )
            return

        context.user_data['end_time'] = text
        context.user_data['step'] = 5

        await update.message.reply_text(
            "Шаг 5/6: Введите аудиторию (или напишите 'пропустить' чтобы пропустить):"
        )

    elif step == 5:  # Аудитория
        if text.lower() != 'пропустить':
            context.user_data['classroom'] = text

        context.user_data['step'] = 6

        await update.message.reply_text(
            "Шаг 6/6: Введите имя преподавателя (или 'пропустить' чтобы пропустить):"
        )

    elif step == 6:  # Преподаватель
        if text.lower() != 'пропустить':
            context.user_data['teacher'] = text

        # Все данные собраны, сохраняем
        success = add_schedule_item(
            user_id=user_id,
            day_of_week=context.user_data['day_of_week'],
            start_time=context.user_data['start_time'],
            end_time=context.user_data['end_time'],
            subject_name=context.user_data['subject_name'],
            subject_type=context.user_data['subject_type'],
            classroom=context.user_data.get('classroom'),
            teacher=context.user_data.get('teacher')
        )

        context.user_data.clear()

        if success:
            await update.message.reply_text(
                "✅ <b>Занятие успешно добавлено!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ <b>Ошибка при добавлении занятия. Попробуйте еще раз.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )


async def handle_deadline_addition(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обработка добавления дедлайна."""
    user_id = update.effective_user.id
    step = context.user_data.get('step', 1)

    if step == 1:  # Название дедлайна
        context.user_data['title'] = text
        context.user_data['step'] = 2

        await update.message.reply_text(
            "Шаг 2/5: Введите описание дедлайна:"
        )

    elif step == 2:  # Описание
        context.user_data['description'] = text
        context.user_data['step'] = 3

        await update.message.reply_text(
            "Шаг 3/5: Введите дату дедлайна в формате ГГГГ-ММ-ДД (например, 2024-12-31):"
        )

    elif step == 3:  # Дата
        if not validate_date(text):
            await update.message.reply_text(
                "❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД (например, 2024-12-31):"
            )
            return

        context.user_data['deadline_date'] = text
        context.user_data['step'] = 4

        await update.message.reply_text(
            "Шаг 4/5: Введите время дедлайна в формате ЧЧ:ММ (или 'пропустить' чтобы пропустить):"
        )

    elif step == 4:  # Время
        if text.lower() != 'пропустить':
            if not validate_time(text):
                await update.message.reply_text(
                    "❌ Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30):"
                )
                return
            context.user_data['deadline_time'] = text

        context.user_data['step'] = 5

        await update.message.reply_text(
            "Шаг 5/5: Выберите приоритет дедлайна:",
            reply_markup=get_priority_keyboard()
        )

    elif step == 6:  # Предмет (опционально)
        if text.lower() != 'пропустить':
            context.user_data['subject_name'] = text

        # Все данные собраны, сохраняем
        success = add_deadline(
            user_id=user_id,
            title=context.user_data['title'],
            description=context.user_data['description'],
            deadline_date=context.user_data['deadline_date'],
            deadline_time=context.user_data.get('deadline_time'),
            subject_name=context.user_data.get('subject_name'),
            priority=context.user_data.get('priority', 'medium')
        )

        context.user_data.clear()

        if success:
            await update.message.reply_text(
                "✅ <b>Дедлайн успешно добавлен!</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ <b>Ошибка при добавлении дедлайна. Попробуйте еще раз.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_keyboard()
            )


async def handle_preferences_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обработка настроек предпочтений."""
    user_id = update.effective_user.id
    pref_type = context.user_data.get('pref_type')

    if pref_type == 'time':
        if ':' in text:
            parts = text.split('-')
            if len(parts) == 2:
                start_time, end_time = parts
                if validate_time(start_time.strip()) and validate_time(end_time.strip()):
                    preferences = get_user_preferences(user_id)
                    preferences['preferred_start_time'] = start_time.strip()
                    preferences['preferred_end_time'] = end_time.strip()
                    save_user_preferences(user_id, preferences)

                    await update.message.reply_text(
                        f"✅ <b>Предпочтительное время установлено:</b> {start_time.strip()} - {end_time.strip()}",
                        parse_mode=ParseMode.HTML,
                        reply_markup=get_preferences_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        "❌ Неверный формат времени. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 09:00-18:00)"
                    )
                    return
            else:
                await update.message.reply_text(
                    "❌ Неверный формат. Используйте ЧЧ:ММ-ЧЧ:ММ (например, 09:00-18:00)"
                )
                return

    elif pref_type == 'max_classes':
        try:
            max_classes = int(text)
            if 1 <= max_classes <= 8:
                preferences = get_user_preferences(user_id)
                preferences['max_classes_per_day'] = max_classes
                save_user_preferences(user_id, preferences)

                await update.message.reply_text(
                    f"✅ <b>Максимальное количество занятий в день установлено:</b> {max_classes}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_preferences_keyboard()
                )
            else:
                await update.message.reply_text(
                    "❌ Введите число от 1 до 8"
                )
                return
        except ValueError:
            await update.message.reply_text(
                "❌ Введите целое число"
            )
            return

    context.user_data.pop('setting_preferences', None)
    context.user_data.pop('pref_type', None)


async def handle_optimization_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Обработка предпочтений для оптимизации расписания."""
    user_id = update.effective_user.id

    await update.message.reply_text(
        "🤖 <b>Создаю оптимизированное расписание на основе ваших предпочтений...</b>",
        parse_mode=ParseMode.HTML
    )

    optimized_schedule = await create_optimized_schedule_with_ai(user_id, text)

    context.user_data.clear()

    await update.message.reply_text(
        f"✨ <b>Ваше оптимизированное расписание:</b>\n\n{optimized_schedule}",
        parse_mode=ParseMode.HTML,
        reply_markup=get_ai_keyboard()
    )


def validate_time(time_str: str) -> bool:
    """Проверка формата времени."""
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False


def validate_date(date_str: str) -> bool:
    """Проверка формата даты."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ============================
# ОБРАБОТЧИК НАЖАТИЙ НА КНОПКИ
# ============================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на Inline-кнопки."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = update.effective_user.id

    # Просмотр расписания по дням
    if data.startswith("view_day:"):
        day = data.split(":")[1]
        schedule = get_schedule_for_day(user_id, day)

        if schedule:
            schedule_text = f"<b>📅 Расписание на {day}:</b>\n\n"
            schedule_text += format_schedule(schedule)
        else:
            schedule_text = f"📭 В {day} занятий нет"

        keyboard = get_days_keyboard("view")

        await query.edit_message_text(
            text=schedule_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

    # Выбор типа занятия при добавлении
    elif data.startswith("select_type:"):
        subject_type = data.split(":")[1]
        context.user_data['subject_type'] = subject_type
        context.user_data['step'] = 3

        keyboard = get_days_keyboard("select")

        await query.edit_message_text(
            text="Шаг 3/6: Выберите день недели:",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

    # Выбор дня при добавлении занятия
    elif data.startswith("select_day:"):
        day = data.split(":")[1]
        context.user_data['day_of_week'] = day
        context.user_data['step'] = 3

        await query.edit_message_text(
            text="Шаг 3/6: Введите время начала (ЧЧ:ММ):",
            parse_mode=ParseMode.HTML
        )

    # Выбор приоритета дедлайна
    elif data.startswith("priority:"):
        priority = data.split(":")[1]
        context.user_data['priority'] = priority
        context.user_data['step'] = 6

        await query.edit_message_text(
            text="Введите название предмета (или 'пропустить' чтобы пропустить):",
            parse_mode=ParseMode.HTML
        )

    # AI функции
    elif data == "ai_analyze_schedule":
        await query.edit_message_text(
            text="🤖 <b>Анализирую ваше расписание...</b>",
            parse_mode=ParseMode.HTML
        )

        analysis = await analyze_schedule_with_ai(user_id)

        await query.edit_message_text(
            text=f"📊 <b>AI Анализ вашего расписания:</b>\n\n{analysis}",
            parse_mode=ParseMode.HTML,
            reply_markup=get_ai_keyboard()
        )

    elif data == "ai_analyze_deadlines":
        await query.edit_message_text(
            text="🤖 <b>Анализирую ваши дедлайны...</b>",
            parse_mode=ParseMode.HTML
        )

        analysis = await analyze_deadlines_with_ai(user_id)

        await query.edit_message_text(
            text=f"📈 <b>AI Анализ ваших дедлайнов:</b>\n\n{analysis}",
            parse_mode=ParseMode.HTML,
            reply_markup=get_ai_keyboard()
        )

    elif data == "ai_optimize_schedule":
        context.user_data['awaiting_optimization_prefs'] = True

        preferences = get_user_preferences(user_id)

        prompt_text = "✨ <b>Для оптимизации расписания расскажите о ваших предпочтениях:</b>\n\n"

        if preferences:
            prompt_text += "<i>Ваши текущие предпочтения:</i>\n"
            if preferences.get('preferred_start_time'):
                prompt_text += f"• Предпочтительное время начала: {preferences['preferred_start_time']}\n"
            if preferences.get('preferred_end_time'):
                prompt_text += f"• Предпочтительное время окончания: {preferences['preferred_end_time']}\n"
            if preferences.get('max_classes_per_day'):
                prompt_text += f"• Макс. занятий в день: {preferences['max_classes_per_day']}\n"
            prompt_text += "\n"

        prompt_text += (
            "Пожалуйста, укажите:\n"
            "1. Предпочитаемое время начала занятий\n"
            "2. Желаемое количество занятий в день\n"
            "3. Предметы, которые требуют больше времени на подготовку\n"
            "4. Дни, когда вы предпочитаете отдыхать\n"
            "5. Ваши периоды наибольшей продуктивности\n\n"
            "Напишите все одним сообщением:"
        )

        await query.edit_message_text(
            text=prompt_text,
            parse_mode=ParseMode.HTML
        )

    elif data == "ai_time_management":
        await query.edit_message_text(
            text="🤖 <b>Генерирую персональные рекомендации...</b>",
            parse_mode=ParseMode.HTML
        )

        recommendations = await get_time_management_recommendations(user_id)

        await query.edit_message_text(
            text=f"🎯 <b>Персональные рекомендации:</b>\n\n{recommendations}",
            parse_mode=ParseMode.HTML,
            reply_markup=get_ai_keyboard()
        )

    # Настройки предпочтений
    elif data == "pref_time":
        context.user_data['setting_preferences'] = True
        context.user_data['pref_type'] = 'time'

        await query.edit_message_text(
            text="⏰ <b>Укажите предпочтительное время занятий</b>\n\n"
                 "Введите время в формате ЧЧ:ММ-ЧЧ:ММ (например, 09:00-18:00):",
            parse_mode=ParseMode.HTML
        )

    elif data == "pref_max_classes":
        context.user_data['setting_preferences'] = True
        context.user_data['pref_type'] = 'max_classes'

        await query.edit_message_text(
            text="📊 <b>Укажите максимальное количество занятий в день</b>\n\n"
                 "Введите число от 1 до 8:",
            parse_mode=ParseMode.HTML
        )

    elif data == "pref_view":
        preferences = get_user_preferences(user_id)

        if preferences:
            text = "🎯 <b>Ваши предпочтения:</b>\n\n"
            if preferences.get('preferred_start_time'):
                text += f"• ⏰ Время начала: {preferences['preferred_start_time']}\n"
            if preferences.get('preferred_end_time'):
                text += f"• ⏰ Время окончания: {preferences['preferred_end_time']}\n"
            if preferences.get('max_classes_per_day'):
                text += f"• 📊 Макс. занятий в день: {preferences['max_classes_per_day']}\n"
            if preferences.get('preferred_days'):
                days = json.loads(preferences['preferred_days'])
                if days:
                    text += f"• 📅 Предпочтительные дни: {', '.join(days)}\n"
            if preferences.get('productivity_periods'):
                periods = json.loads(preferences['productivity_periods'])
                if periods:
                    text += f"• ⚡ Периоды продуктивности: {', '.join(periods)}\n"
        else:
            text = "📭 У вас еще нет сохраненных предпочтений."

        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_preferences_keyboard()
        )

    elif data == "pref_reset":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM user_preferences WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

        await query.edit_message_text(
            text="🔄 <b>Ваши предпочтения сброшены</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_preferences_keyboard()
        )

    # Добавление дедлайна
    elif data == "add_deadline":
        await query.edit_message_text(
            text="⏰ <b>Добавление нового дедлайна</b>\n\n"
                 "Шаг 1/5: Введите название дедлайна:",
            parse_mode=ParseMode.HTML
        )
        context.user_data['adding_deadline'] = True
        context.user_data['step'] = 1

    # Возврат на главную
    elif data == "back_to_main":
        await query.edit_message_text(
            text="🏠 <b>Главное меню</b>",
            parse_mode=ParseMode.HTML
        )
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Выберите действие:",
            reply_markup=get_main_keyboard()
        )

    # Возврат к добавлению занятия
    elif data == "back_to_add":
        await query.edit_message_text(
            text="📝 <b>Добавление нового занятия</b>\n\n"
                 "Шаг 1/6: Введите название предмета:",
            parse_mode=ParseMode.HTML
        )
        context.user_data['adding_schedule'] = True
        context.user_data['step'] = 1

    # Возврат к добавлению дедлайна
    elif data == "back_to_add_deadline":
        await query.edit_message_text(
            text="⏰ <b>Добавление нового дедлайна</b>\n\n"
                 "Шаг 1/5: Введите название дедлайна:",
            parse_mode=ParseMode.HTML
        )
        context.user_data['adding_deadline'] = True
        context.user_data['step'] = 1


# ============================
# ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ
# ============================

async def subjects_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /subjects."""
    user_id = update.effective_user.id
    subjects = get_all_subjects(user_id)

    if subjects:
        text = "📚 <b>Ваши предметы:</b>\n\n"
        for i, subject in enumerate(subjects, 1):
            name = html.escape(subject['subject_name'])
            type_ = html.escape(subject['subject_type'])
            classroom = html.escape(subject['classroom']) if subject['classroom'] else "не указана"
            teacher = html.escape(subject['teacher']) if subject['teacher'] else "не указан"

            text += f"<b>{i}.</b> {name} ({type_})\n"
            text += f"   🏫 Аудитория: {classroom}\n"
            text += f"   👨‍🏫 Преподаватель: {teacher}\n\n"
    else:
        text = "📭 У вас еще нет предметов. Добавьте их через меню '➕ Добавить занятие'"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /delete."""
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, day_of_week, start_time, subject_name
        FROM schedule
        WHERE user_id = ?
        ORDER BY day_of_week, start_time
    ''', (user_id,))

    items = cursor.fetchall()
    conn.close()

    if items:
        keyboard = []
        for item in items:
            btn_text = f"{item['day_of_week']} {item['start_time']} - {item['subject_name'][:20]}"
            keyboard.append([InlineKeyboardButton(
                btn_text, callback_data=f"delete_item:{item['id']}"
            )])

        keyboard.append([InlineKeyboardButton("⬅️ Отмена", callback_data="cancel_delete")])

        await update.message.reply_text(
            "🗑️ <b>Выберите занятие для удаления:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "📭 У вас нет занятий для удаления.",
            parse_mode=ParseMode.HTML
        )


async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /notify."""
    keyboard = [
        [
            InlineKeyboardButton("🔔 Включить", callback_data="notify:on"),
            InlineKeyboardButton("🔕 Выключить", callback_data="notify:off")
        ],
        [
            InlineKeyboardButton("⏰ За 15 мин", callback_data="notify_before:15"),
            InlineKeyboardButton("⏰ За 30 мин", callback_data="notify_before:30"),
            InlineKeyboardButton("⏰ За 60 мин", callback_data="notify_before:60")
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
        ]
    ]

    await update.message.reply_text(
        "🔔 <b>Настройка уведомлений</b>\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ============================
# ОБРАБОТЧИК ОШИБОК
# ============================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок."""
    error = context.error
    logger.error(f"❌ Произошла ошибка: {error}")

    if update and hasattr(update, 'effective_chat'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ <b>Произошла ошибка при обработке запроса</b>\n\n"
                     "Попробуйте еще раз или используйте /help для справки.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"❌ Не удалось отправить сообщение об ошибке: {e}")


# ============================
# ЗАПУСК БОТА
# ============================

def main():
    """Запуск бота."""
    # Инициализация базы данных
    init_db()

    print("=" * 60)
    print("🤖 ЗАПУСК AI АГЕНТА ДЛЯ РАСПИСАНИЯ")
    print("=" * 60)
    print(f"База данных: {DB_PATH}")
    print("=" * 60)
    print("🚀 Бот запускается...")
    print("📱 Откройте Telegram и найдите бота по имени")
    print("💡 Используйте /start для начала работы")
    print("=" * 60)

    if not check_db_structure():
        print("❌ Ошибка: Не удалось инициализировать базу данных")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CommandHandler("tomorrow", tomorrow_command))
    application.add_handler(CommandHandler("deadlines", deadlines_command))
    application.add_handler(CommandHandler("analyze", ai_analyze_command))
    application.add_handler(CommandHandler("preferences", preferences_command))
    application.add_handler(CommandHandler("subjects", subjects_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("notify", notify_command))

    # Регистрируем обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))

    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Регистрируем обработчик ошибок
    application.add_error_handler(error_handler)

    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
