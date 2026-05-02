"""
🏋️ YOG' YOQOTISH KALKULYATORI — Telegram Bot

Funksiyalar:
- Profil yaratish va saqlash
- Yog' foizini hisoblash (Hodgdon-Beckett / U.S. Navy)
- BMR va TDEE hisoblash
- Kunlik makro normasi (oqsil, yog', uglevod)
- Ovqat jurnali (kunlik)
- Statistika

Formulalar:
- BF% (Erkak): 495/(1.0324 - 0.19077·log10(qorin-bo'yin) + 0.15456·log10(bo'y)) - 450
- BF% (Ayol):  495/(1.29579 - 0.35004·log10(qorin+son-bo'yin) + 0.22100·log10(bo'y)) - 450
- LBM = Vazn × (1 - BF%/100)
- BMR = 4.32 × Yog'_massa + 24.07 × LBM
- TDEE = BMR × Faollik
- Oqsil = LBM × ratio,  Yog' = LBM × ratio
- Uglevod = (Kkal - Oqsil×4 - Yog'×9) / 4
"""

import logging
import math
import sqlite3
import os
from datetime import datetime, date
from typing import Optional

from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DB_PATH = "calorie_bot.db"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# CONVERSATION STATES
# ═══════════════════════════════════════════════════════════
(
    PROFILE_GENDER, PROFILE_WEIGHT, PROFILE_HEIGHT, PROFILE_AGE,
    PROFILE_ABDOMEN, PROFILE_NECK, PROFILE_HIP, PROFILE_ACTIVITY,
    PROFILE_PROTEIN_RATIO, PROFILE_FAT_RATIO, PROFILE_GOAL,
    FOOD_NAME, FOOD_PROTEIN, FOOD_FAT, FOOD_CARBS, FOOD_KCAL,
) = range(16)

ACTIVITY_LEVELS = {
    "1.2 (~3 ming qadam)": 1.2,
    "1.3 (~5 ming qadam)": 1.3,
    "1.35 (~7 ming qadam)": 1.35,
    "1.4 (~10 ming qadam)": 1.4,
    "1.45 (~12 ming qadam)": 1.45,
    "1.5 (~15 ming qadam)": 1.5,
    "1.55 (~18 ming qadam)": 1.55,
    "1.6 (~20 ming qadam)": 1.6,
    "1.65 (~23 ming qadam)": 1.65,
    "1.7 (~26 ming qadam)": 1.7,
}

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
def init_db():
    """Database va jadvallarni yaratish"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            gender INTEGER,
            weight REAL,
            height REAL,
            age INTEGER,
            abdomen REAL,
            neck REAL,
            hip REAL,
            activity REAL,
            protein_ratio REAL DEFAULT 1.8,
            fat_ratio REAL DEFAULT 0.7,
            goal_kcal INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS food_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            food_name TEXT,
            protein REAL,
            fat REAL,
            carbs REAL,
            kcal REAL,
            log_date DATE DEFAULT (date('now')),
            log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    conn.commit()
    conn.close()

def get_user(user_id: int) -> Optional[dict]:
    """Foydalanuvchi ma'lumotlarini olish"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def save_user(user_id: int, username: str, data: dict):
    """Foydalanuvchi profilini saqlash/yangilash"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO users (user_id, username, gender, weight, height, age,
                          abdomen, neck, hip, activity, protein_ratio, fat_ratio, goal_kcal)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            gender=excluded.gender,
            weight=excluded.weight,
            height=excluded.height,
            age=excluded.age,
            abdomen=excluded.abdomen,
            neck=excluded.neck,
            hip=excluded.hip,
            activity=excluded.activity,
            protein_ratio=excluded.protein_ratio,
            fat_ratio=excluded.fat_ratio,
            goal_kcal=excluded.goal_kcal,
            updated_at=CURRENT_TIMESTAMP
    ''', (
        user_id, username,
        data.get('gender'), data.get('weight'), data.get('height'), data.get('age'),
        data.get('abdomen'), data.get('neck'), data.get('hip'),
        data.get('activity'),
        data.get('protein_ratio', 1.8),
        data.get('fat_ratio', 0.7),
        data.get('goal_kcal', 0),
    ))
    conn.commit()
    conn.close()

def update_user_field(user_id: int, field: str, value):
    """Bitta maydon yangilash"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
              (value, user_id))
    conn.commit()
    conn.close()

def add_food_log(user_id: int, food_name: str, protein: float, fat: float,
                 carbs: float, kcal: float):
    """Ovqat jurnaliga yozish"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO food_log (user_id, food_name, protein, fat, carbs, kcal)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, food_name, protein, fat, carbs, kcal))
    conn.commit()
    conn.close()

def get_today_food(user_id: int) -> list:
    """Bugungi ovqatlar"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT * FROM food_log
        WHERE user_id = ? AND log_date = date('now')
        ORDER BY log_time
    ''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_last_food(user_id: int) -> bool:
    """Oxirgi yozuvni o'chirish"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        DELETE FROM food_log
        WHERE id = (
            SELECT id FROM food_log
            WHERE user_id = ? AND log_date = date('now')
            ORDER BY log_time DESC LIMIT 1
        )
    ''', (user_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def clear_today_food(user_id: int):
    """Bugungi barcha yozuvlarni o'chirish"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM food_log WHERE user_id = ? AND log_date = date('now')", (user_id,))
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════════════════════
# HISOBLASH FORMULALARI
# ═══════════════════════════════════════════════════════════
def calc_bf_percent(gender: int, abdomen: float, neck: float,
                    height: float, hip: float = 0) -> float:
    """Yog' foizi (Hodgdon-Beckett, U.S. Navy)"""
    try:
        if gender == 1:  # Erkak
            return round(495 / (1.0324 - 0.19077 * math.log10(abdomen - neck)
                                + 0.15456 * math.log10(height)) - 450, 1)
        else:  # Ayol
            return round(495 / (1.29579 - 0.35004 * math.log10(abdomen + hip - neck)
                                + 0.22100 * math.log10(height)) - 450, 1)
    except (ValueError, ZeroDivisionError):
        return 0.0

def calc_lbm(weight: float, bf_percent: float) -> float:
    """Yog'siz tana vazni"""
    return round(weight * (1 - bf_percent / 100), 1)

def calc_bmr(fat_mass: float, lbm: float) -> int:
    """BMR = 4.32 × Yog' + 24.07 × LBM"""
    return round(4.32 * fat_mass + 24.07 * lbm)

def calc_tdee(bmr: int, activity: float) -> int:
    """TDEE = BMR × Faollik"""
    return round(bmr * activity)

def calc_macros(lbm: float, protein_ratio: float, fat_ratio: float, daily_kcal: int) -> dict:
    """Makrolarni hisoblash"""
    protein_g = round(lbm * protein_ratio)
    fat_g = round(lbm * fat_ratio)
    carbs_g = round((daily_kcal - protein_g * 4 - fat_g * 9) / 4)
    return {'protein': protein_g, 'fat': fat_g, 'carbs': carbs_g, 'kcal': daily_kcal}

def get_full_calculation(user: dict) -> dict:
    """Foydalanuvchi uchun to'liq hisoblash"""
    bf = calc_bf_percent(user['gender'], user['abdomen'], user['neck'],
                         user['height'], user.get('hip') or 0)
    fat_mass = round(user['weight'] * bf / 100, 1)
    lbm = calc_lbm(user['weight'], bf)
    bmr = calc_bmr(fat_mass, lbm)
    tdee = calc_tdee(bmr, user['activity'])

    daily_kcal = user['goal_kcal'] if user['goal_kcal'] > 0 else tdee
    macros = calc_macros(lbm, user['protein_ratio'], user['fat_ratio'], daily_kcal)

    return {
        'bf_percent': bf,
        'fat_mass': fat_mass,
        'lbm': lbm,
        'bmr': bmr,
        'tdee': tdee,
        'daily_kcal': daily_kcal,
        'protein': macros['protein'],
        'fat': macros['fat'],
        'carbs': macros['carbs'],
    }

def get_bf_category(gender: int, bf: float) -> str:
    """Yog' foizi kategoriyasi"""
    if gender == 1:  # Erkak
        if bf < 10: return "⚠️ Juda oz (xavfli)"
        elif bf <= 15: return "✅ Salomatlik va Estetika"
        elif bf <= 19: return "✅ Norma"
        elif bf <= 25: return "⚠️ Dastlabki Semizlik"
        else: return "❌ Semizlik"
    else:  # Ayol
        if bf < 16: return "⚠️ Juda oz"
        elif bf <= 24: return "✅ Salomatlik va Estetika"
        elif bf <= 31: return "✅ Norma"
        elif bf <= 38: return "⚠️ Dastlabki Semizlik"
        else: return "❌ Semizlik"

# ═══════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════
def main_menu_kb():
    return ReplyKeyboardMarkup([
        ["📊 Mening profilim", "🔥 Hisoblash"],
        ["🍽️ Ovqat qo'shish", "📝 Bugungi jurnal"],
        ["✏️ Profilni tahrirlash", "ℹ️ Yordam"],
    ], resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup([["❌ Bekor qilish"]], resize_keyboard=True)

def gender_kb():
    return ReplyKeyboardMarkup([["👨 Erkak", "👩 Ayol"], ["❌ Bekor qilish"]],
                                resize_keyboard=True, one_time_keyboard=True)

def activity_kb():
    keys = list(ACTIVITY_LEVELS.keys())
    rows = [keys[i:i+2] for i in range(0, len(keys), 2)]
    rows.append(["❌ Bekor qilish"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)

# ═══════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user and user.get('gender'):
        await update.message.reply_text(
            f"🏋️ <b>Salom, {update.effective_user.first_name}!</b>\n\n"
            "Yog' yoqotish kalkulyatoriga xush kelibsiz.\n"
            "Profilingiz allaqachon mavjud — quyidagi menudan tanlang:",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    else:
        await update.message.reply_text(
            f"🏋️ <b>Salom, {update.effective_user.first_name}!</b>\n\n"
            "Men yog' yoqotish kalkulyatoriman. Sizga quyidagilarda yordam beraman:\n\n"
            "📏 Yog' foizini hisoblash\n"
            "🔥 BMR va kunlik kaloriya sarfi\n"
            "🍽️ Makro normalar (oqsil/yog'/uglevod)\n"
            "📝 Kunlik ovqat jurnali\n\n"
            "Boshlash uchun /profil buyrug'ini bering.",
            parse_mode="HTML"
        )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>📋 Mavjud buyruqlar:</b>\n\n"
        "/start - Botni ishga tushirish\n"
        "/profil - Profil yaratish/yangilash\n"
        "/hisoblash - To'liq hisoblash natijasi\n"
        "/ovqat - Ovqat qo'shish\n"
        "/jurnal - Bugungi ovqat jurnali\n"
        "/tozalash - Bugungi jurnalni tozalash\n"
        "/yordam - Yordam\n\n"
        "<b>📐 Hisoblash formulalari:</b>\n"
        "• Yog' foizi: Hodgdon-Beckett (U.S. Navy)\n"
        "• LBM = Vazn × (1 - BF%/100)\n"
        "• BMR = 4.32 × Yog' + 24.07 × LBM\n"
        "• TDEE = BMR × Faollik\n"
        "• Oqsil/Yog' = LBM × ratio\n"
        "• Uglevod = qolgan kaloriyadan",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

# ═══════════════════════════════════════════════════════════
# PROFIL YARATISH (Conversation)
# ═══════════════════════════════════════════════════════════
async def cmd_profile_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['profile'] = {}
    await update.message.reply_text(
        "👋 <b>Profil yaratish</b>\n\nJinsingizni tanlang:",
        parse_mode="HTML",
        reply_markup=gender_kb()
    )
    return PROFILE_GENDER

async def profile_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "Erkak" in text:
        context.user_data['profile']['gender'] = 1
    elif "Ayol" in text:
        context.user_data['profile']['gender'] = 2
    else:
        await update.message.reply_text("❌ Iltimos, tugmani tanlang.")
        return PROFILE_GENDER

    await update.message.reply_text(
        "⚖️ <b>Vazningizni kiriting (kg):</b>\nMasalan: <code>85</code> yoki <code>72.5</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    return PROFILE_WEIGHT

async def profile_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        w = float(update.message.text.replace(",", "."))
        if not (30 <= w <= 300):
            raise ValueError()
        context.user_data['profile']['weight'] = w
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 30-300 oralig'ida son kiriting.")
        return PROFILE_WEIGHT

    await update.message.reply_text(
        "📏 <b>Bo'yingizni kiriting (sm):</b>\nMasalan: <code>175</code>",
        parse_mode="HTML"
    )
    return PROFILE_HEIGHT

async def profile_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        h = float(update.message.text.replace(",", "."))
        if not (100 <= h <= 250):
            raise ValueError()
        context.user_data['profile']['height'] = h
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 100-250 oralig'ida son kiriting.")
        return PROFILE_HEIGHT

    await update.message.reply_text(
        "🎂 <b>Yoshingizni kiriting:</b>\nMasalan: <code>30</code>",
        parse_mode="HTML"
    )
    return PROFILE_AGE

async def profile_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        a = int(update.message.text)
        if not (10 <= a <= 100):
            raise ValueError()
        context.user_data['profile']['age'] = a
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 10-100 oralig'ida son kiriting.")
        return PROFILE_AGE

    await update.message.reply_text(
        "📐 <b>Qorin / bel o'lchamini kiriting (sm):</b>\n"
        "💡 Kindik darajasida, nafas chiqargan holda o'lchang.\nMasalan: <code>95</code>",
        parse_mode="HTML"
    )
    return PROFILE_ABDOMEN

async def profile_abdomen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if not (40 <= v <= 200):
            raise ValueError()
        context.user_data['profile']['abdomen'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 40-200 oralig'ida son kiriting.")
        return PROFILE_ABDOMEN

    await update.message.reply_text(
        "📐 <b>Bo'yin o'lchamini kiriting (sm):</b>\n"
        "💡 Bo'yin eng tor joyidan o'lchang.\nMasalan: <code>38</code>",
        parse_mode="HTML"
    )
    return PROFILE_NECK

async def profile_neck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if not (20 <= v <= 80):
            raise ValueError()
        context.user_data['profile']['neck'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 20-80 oralig'ida son kiriting.")
        return PROFILE_NECK

    if context.user_data['profile']['gender'] == 2:
        await update.message.reply_text(
            "📐 <b>Son o'lchamini kiriting (sm):</b>\n"
            "💡 Son eng keng joyidan o'lchang.\nMasalan: <code>95</code>",
            parse_mode="HTML"
        )
        return PROFILE_HIP
    else:
        context.user_data['profile']['hip'] = 0
        return await ask_activity(update, context)

async def profile_hip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if not (40 <= v <= 200):
            raise ValueError()
        context.user_data['profile']['hip'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 40-200 oralig'ida son kiriting.")
        return PROFILE_HIP

    return await ask_activity(update, context)

async def ask_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏃 <b>Faollik darajangizni tanlang:</b>\n\n"
        "💡 Kunlik qadamlar soniga qarab tanlang:",
        parse_mode="HTML",
        reply_markup=activity_kb()
    )
    return PROFILE_ACTIVITY

async def profile_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text not in ACTIVITY_LEVELS:
        await update.message.reply_text("❌ Iltimos, ro'yxatdan tanlang.")
        return PROFILE_ACTIVITY

    context.user_data['profile']['activity'] = ACTIVITY_LEVELS[text]

    await update.message.reply_text(
        "🥩 <b>Oqsil koeffitsienti (g/kg LBM):</b>\n\n"
        "💡 Tavsiya: 1.6–2.2 g/kg yog'siz tana vazni\n"
        "Standart: <code>1.8</code>\n\n"
        "Standart qiymatni ishlatish uchun <code>1.8</code> yozing yoki o'zingizni kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    return PROFILE_PROTEIN_RATIO

async def profile_protein_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if not (0.5 <= v <= 4):
            raise ValueError()
        context.user_data['profile']['protein_ratio'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 0.5-4 oralig'ida son kiriting.")
        return PROFILE_PROTEIN_RATIO

    await update.message.reply_text(
        "🥑 <b>Yog' koeffitsienti (g/kg LBM):</b>\n\n"
        "💡 Tavsiya: 0.6–1.0 g/kg yog'siz tana vazni\n"
        "Standart: <code>0.7</code>",
        parse_mode="HTML"
    )
    return PROFILE_FAT_RATIO

async def profile_fat_ratio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if not (0.3 <= v <= 2):
            raise ValueError()
        context.user_data['profile']['fat_ratio'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 0.3-2 oralig'ida son kiriting.")
        return PROFILE_FAT_RATIO

    await update.message.reply_text(
        "🎯 <b>Maqsad kaloriya (Kkal):</b>\n\n"
        "💡 0 kiritsangiz TDEE avtomatik ishlatiladi (vazn saqlash).\n"
        "Yog' yoqotish uchun TDEE dan 300-500 Kkal kam qiymat tanlang.\n\n"
        "Masalan: <code>2000</code> yoki <code>0</code>",
        parse_mode="HTML"
    )
    return PROFILE_GOAL

async def profile_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = int(float(update.message.text.replace(",", ".")))
        if v < 0 or v > 10000:
            raise ValueError()
        context.user_data['profile']['goal_kcal'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 0-10000 oralig'ida son kiriting.")
        return PROFILE_GOAL

    # Saqlash
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    save_user(user_id, username, context.user_data['profile'])

    await update.message.reply_text(
        "✅ <b>Profil muvaffaqiyatli saqlandi!</b>\n\n"
        "Endi /hisoblash buyrug'i bilan natijalarni ko'rishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

    # Avtomatik hisoblashni ko'rsatish
    await show_calculation(update, context)
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=main_menu_kb()
    )
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════
# HISOBLASH
# ═══════════════════════════════════════════════════════════
async def show_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user.get('gender'):
        await update.message.reply_text(
            "❗ Avval profil yarating: /profil",
            reply_markup=main_menu_kb()
        )
        return

    calc = get_full_calculation(user)
    cat = get_bf_category(user['gender'], calc['bf_percent'])
    gender_text = "👨 Erkak" if user['gender'] == 1 else "👩 Ayol"

    text = (
        "📊 <b>HISOBLASH NATIJASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>👤 Profil:</b>\n"
        f"  {gender_text} | {user['age']} yosh\n"
        f"  ⚖️ Vazn: <b>{user['weight']} kg</b>\n"
        f"  📏 Bo'y: <b>{user['height']} sm</b>\n"
        f"  🏃 Faollik: <b>×{user['activity']}</b>\n\n"
        "<b>📏 Tana tarkibi:</b>\n"
        f"  Yog' foizi: <b>{calc['bf_percent']}%</b>\n"
        f"  Holat: {cat}\n"
        f"  Yog' massa: <b>{calc['fat_mass']} kg</b>\n"
        f"  Yog'siz tana (LBM): <b>{calc['lbm']} kg</b>\n\n"
        "<b>🔥 Energiya:</b>\n"
        f"  BMR (tinch holatda): <b>{calc['bmr']} Kkal</b>\n"
        f"  TDEE (kunlik sarf): <b>{calc['tdee']} Kkal</b>\n\n"
        "<b>🍽️ Kunlik norma:</b>\n"
        f"  🥩 Oqsil: <b>{calc['protein']} g</b>\n"
        f"  🥑 Yog': <b>{calc['fat']} g</b>\n"
        f"  🍞 Uglevod: <b>{calc['carbs']} g</b>\n"
        f"  🔥 Kkal: <b>{calc['daily_kcal']}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 Ovqat qo'shish uchun /ovqat\n"
        "📝 Bugungi jurnal: /jurnal"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

async def cmd_calculation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_calculation(update, context)

async def cmd_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user or not user.get('gender'):
        await update.message.reply_text(
            "❗ Profilingiz yo'q. /profil buyrug'i bilan yarating.",
            reply_markup=main_menu_kb()
        )
        return

    gender_text = "👨 Erkak" if user['gender'] == 1 else "👩 Ayol"
    hip_text = f"\n  Son: {user['hip']} sm" if user['gender'] == 2 else ""
    goal_text = "TDEE (avtomatik)" if user['goal_kcal'] == 0 else f"{user['goal_kcal']} Kkal"

    text = (
        "👤 <b>MENING PROFILIM</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"  {gender_text}\n"
        f"  ⚖️ Vazn: <b>{user['weight']} kg</b>\n"
        f"  📏 Bo'y: <b>{user['height']} sm</b>\n"
        f"  🎂 Yosh: <b>{user['age']}</b>\n\n"
        "<b>📐 O'lchamlar:</b>\n"
        f"  Qorin: {user['abdomen']} sm\n"
        f"  Bo'yin: {user['neck']} sm{hip_text}\n\n"
        "<b>⚙️ Sozlamalar:</b>\n"
        f"  🏃 Faollik: ×{user['activity']}\n"
        f"  🥩 Oqsil: {user['protein_ratio']} g/kg LBM\n"
        f"  🥑 Yog': {user['fat_ratio']} g/kg LBM\n"
        f"  🎯 Maqsad: {goal_text}\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "✏️ Tahrirlash: /profil"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

# ═══════════════════════════════════════════════════════════
# OVQAT QO'SHISH
# ═══════════════════════════════════════════════════════════
async def cmd_food_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user or not user.get('gender'):
        await update.message.reply_text(
            "❗ Avval profil yarating: /profil",
            reply_markup=main_menu_kb()
        )
        return ConversationHandler.END

    context.user_data['food'] = {}
    await update.message.reply_text(
        "🍽️ <b>Ovqat qo'shish</b>\n\n"
        "Mahsulot nomini kiriting:\nMasalan: <code>Tovuq go'shti 200g</code>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
    return FOOD_NAME

async def food_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❌ Nom juda qisqa.")
        return FOOD_NAME

    context.user_data['food']['name'] = name
    await update.message.reply_text(
        "🥩 <b>Oqsil miqdori (g):</b>\nMasalan: <code>40</code>",
        parse_mode="HTML"
    )
    return FOOD_PROTEIN

async def food_protein(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if v < 0 or v > 1000:
            raise ValueError()
        context.user_data['food']['protein'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat. 0-1000 oralig'ida son.")
        return FOOD_PROTEIN

    await update.message.reply_text(
        "🥑 <b>Yog' miqdori (g):</b>\nMasalan: <code>10</code>",
        parse_mode="HTML"
    )
    return FOOD_FAT

async def food_fat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if v < 0 or v > 500:
            raise ValueError()
        context.user_data['food']['fat'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat.")
        return FOOD_FAT

    await update.message.reply_text(
        "🍞 <b>Uglevod miqdori (g):</b>\nMasalan: <code>30</code>",
        parse_mode="HTML"
    )
    return FOOD_CARBS

async def food_carbs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if v < 0 or v > 1000:
            raise ValueError()
        context.user_data['food']['carbs'] = v
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat.")
        return FOOD_CARBS

    # Auto-calc kcal
    f = context.user_data['food']
    auto_kcal = round(f['protein'] * 4 + f['fat'] * 9 + f['carbs'] * 4)
    context.user_data['food']['auto_kcal'] = auto_kcal

    await update.message.reply_text(
        f"🔥 <b>Kaloriya (Kkal):</b>\n\n"
        f"💡 Avtomatik hisob: <b>{auto_kcal} Kkal</b>\n"
        f"(P×4 + Y×9 + U×4)\n\n"
        f"Avtomatik qiymatni ishlatish uchun <code>{auto_kcal}</code> yoki o'zingizning qiymatingizni kiriting:",
        parse_mode="HTML"
    )
    return FOOD_KCAL

async def food_kcal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        v = float(update.message.text.replace(",", "."))
        if v < 0 or v > 10000:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri qiymat.")
        return FOOD_KCAL

    user_id = update.effective_user.id
    f = context.user_data['food']
    add_food_log(user_id, f['name'], f['protein'], f['fat'], f['carbs'], v)

    await update.message.reply_text(
        f"✅ <b>Qo'shildi!</b>\n\n"
        f"🍽️ {f['name']}\n"
        f"🥩 Oqsil: {f['protein']}g | 🥑 Yog': {f['fat']}g | 🍞 Uglevod: {f['carbs']}g\n"
        f"🔥 {round(v)} Kkal",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

    # Bugungi jurnalni ko'rsatish
    await show_today_log(update, context)
    return ConversationHandler.END

# ═══════════════════════════════════════════════════════════
# JURNAL
# ═══════════════════════════════════════════════════════════
async def show_today_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    foods = get_today_food(user_id)

    if not foods:
        await update.message.reply_text(
            "📭 <b>Bugun hech narsa qo'shilmagan.</b>\n\n"
            "🍽️ Ovqat qo'shish: /ovqat",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
        return

    calc = get_full_calculation(user)
    total_p = sum(f['protein'] for f in foods)
    total_f = sum(f['fat'] for f in foods)
    total_c = sum(f['carbs'] for f in foods)
    total_k = sum(f['kcal'] for f in foods)

    # Bar progress
    def bar(current, target, width=10):
        if target <= 0: return "—"
        pct = min(100, int(current / target * 100))
        filled = int(pct / 100 * width)
        return f"{'█' * filled}{'░' * (width - filled)} {pct}%"

    today = date.today().strftime("%d.%m.%Y")
    text = f"📝 <b>BUGUNGI JURNAL</b> ({today})\n━━━━━━━━━━━━━━━━━━━\n\n"

    for i, f in enumerate(foods, 1):
        text += (
            f"<b>{i}. {f['food_name']}</b>\n"
            f"   🥩 {f['protein']:.0f}g | 🥑 {f['fat']:.0f}g | 🍞 {f['carbs']:.0f}g | 🔥 {f['kcal']:.0f}\n"
        )

    text += "\n━━━━━━━━━━━━━━━━━━━\n"
    text += "<b>📊 JAMI / NORMA:</b>\n\n"
    text += f"🥩 Oqsil: <b>{total_p:.0f} / {calc['protein']} g</b>\n"
    text += f"   {bar(total_p, calc['protein'])}\n\n"
    text += f"🥑 Yog': <b>{total_f:.0f} / {calc['fat']} g</b>\n"
    text += f"   {bar(total_f, calc['fat'])}\n\n"
    text += f"🍞 Uglevod: <b>{total_c:.0f} / {calc['carbs']} g</b>\n"
    text += f"   {bar(total_c, calc['carbs'])}\n\n"
    text += f"🔥 Kkal: <b>{total_k:.0f} / {calc['daily_kcal']}</b>\n"
    text += f"   {bar(total_k, calc['daily_kcal'])}\n\n"
    text += "━━━━━━━━━━━━━━━━━━━\n"

    remaining_k = calc['daily_kcal'] - total_k
    if remaining_k > 0:
        text += f"✅ <b>Qolgan: {remaining_k:.0f} Kkal</b>\n"
    else:
        text += f"⚠️ <b>Normadan {abs(remaining_k):.0f} Kkal ortiq!</b>\n"

    text += "\n🍽️ Yana qo'shish: /ovqat\n"
    text += "🗑️ Tozalash: /tozalash"

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

async def cmd_journal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_today_log(update, context)

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Hammasini o'chirish", callback_data="clear_all")],
        [InlineKeyboardButton("⏪ Faqat oxirgisini", callback_data="clear_last")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="clear_cancel")],
    ])
    await update.message.reply_text(
        "🗑️ <b>Bugungi jurnalni tozalash:</b>\n\nNimani o'chirmoqchisiz?",
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "clear_all":
        clear_today_food(user_id)
        await query.edit_message_text("✅ Bugungi jurnal tozalandi.")
    elif query.data == "clear_last":
        if delete_last_food(user_id):
            await query.edit_message_text("✅ Oxirgi yozuv o'chirildi.")
        else:
            await query.edit_message_text("📭 Hech qanday yozuv topilmadi.")
    else:
        await query.edit_message_text("❌ Bekor qilindi.")

# ═══════════════════════════════════════════════════════════
# MENU TUGMALARI HANDLER
# ═══════════════════════════════════════════════════════════
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "Mening profilim" in text:
        await cmd_my_profile(update, context)
    elif "Hisoblash" in text:
        await show_calculation(update, context)
    elif "Bugungi jurnal" in text:
        await show_today_log(update, context)
    elif "Yordam" in text:
        await cmd_help(update, context)
    elif "Profilni tahrirlash" in text:
        return await cmd_profile_start(update, context)
    elif "Ovqat qo'shish" in text:
        return await cmd_food_start(update, context)
    else:
        await update.message.reply_text(
            "❓ Tushunmadim. Menyu tugmalaridan foydalaning yoki /yordam buyrug'i bilan yordam oling.",
            reply_markup=main_menu_kb()
        )

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
def main():
    init_db()

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ XATO: BOT_TOKEN o'rnatilmagan!")
        print("BotFather (@BotFather) dan token oling va environment variable qo'ying:")
        print("  export BOT_TOKEN='YOUR_TOKEN_HERE'")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Profil yaratish conversation
    profile_conv = ConversationHandler(
        entry_points=[
            CommandHandler("profil", cmd_profile_start),
            MessageHandler(filters.Regex("✏️ Profilni tahrirlash"), cmd_profile_start),
        ],
        states={
            PROFILE_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_gender)],
            PROFILE_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_weight)],
            PROFILE_HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_height)],
            PROFILE_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_age)],
            PROFILE_ABDOMEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_abdomen)],
            PROFILE_NECK: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_neck)],
            PROFILE_HIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_hip)],
            PROFILE_ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_activity)],
            PROFILE_PROTEIN_RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_protein_ratio)],
            PROFILE_FAT_RATIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_fat_ratio)],
            PROFILE_GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_goal)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("❌ Bekor qilish"), cancel_conversation),
            CommandHandler("bekor", cancel_conversation),
        ],
    )

    # Ovqat qo'shish conversation
    food_conv = ConversationHandler(
        entry_points=[
            CommandHandler("ovqat", cmd_food_start),
            MessageHandler(filters.Regex("🍽️ Ovqat qo'shish"), cmd_food_start),
        ],
        states={
            FOOD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_name)],
            FOOD_PROTEIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_protein)],
            FOOD_FAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_fat)],
            FOOD_CARBS: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_carbs)],
            FOOD_KCAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_kcal)],
        },
        fallbacks=[
            MessageHandler(filters.Regex("❌ Bekor qilish"), cancel_conversation),
            CommandHandler("bekor", cancel_conversation),
        ],
    )

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("yordam", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("hisoblash", cmd_calculation))
    app.add_handler(CommandHandler("jurnal", cmd_journal))
    app.add_handler(CommandHandler("tozalash", cmd_clear))
    app.add_handler(profile_conv)
    app.add_handler(food_conv)
    app.add_handler(CallbackQueryHandler(clear_callback, pattern="^clear_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

    print("🤖 Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
