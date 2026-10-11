from telegram import CopyTextButton
#!/usr/bin/env python3
# Free Fire Like Bot — Telegram bot starter
# Python 3.10+ | python-telegram-bot 22.x
# Configure secrets with environment variables; never share your bot token.

import asyncio
import os
import re
import json
import sqlite3
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("fflike")

# =========================
# SETTINGS — edit as needed
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "fflikeBd07_BOT").strip().lstrip("@")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8669357832"))
BKASH_NUMBER = os.getenv("BKASH_NUMBER", "01825808125")
HISTORY_CHANNEL = os.getenv("HISTORY_CHANNEL", "@dailylikehistory07")
JOIN_CHANNEL_1 = os.getenv("JOIN_CHANNEL_1", "@dailylikehistory07")
JOIN_CHANNEL_2 = os.getenv("JOIN_CHANNEL_2", "@likeupdateofc")
JOIN_LINK_1 = os.getenv("JOIN_LINK_1", "https://t.me/dailylikehistory07")
JOIN_LINK_2 = os.getenv("JOIN_LINK_2", "https://t.me/likeupdateofc")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/redwan_islam007")
LIKE_API_URL = os.getenv("LIKE_API_URL", "").strip()
LIKE_API_KEY = os.getenv("LIKE_API_KEY", "").strip()
DB_PATH = os.getenv("DB_PATH", os.path.expanduser("~/likebot/bot.sqlite3"))
TZ = ZoneInfo("Asia/Dhaka")
PRICE = 15.0
LIKES_PER_ORDER = 200
MIN_DEPOSIT = 10.0
JOIN_BONUS = 1.0
REFERRAL_COMMISSION_PERCENT = 10.0
RESET_HOUR = 4  # daily UID limit resets at 04:00 Asia/Dhaka

if not BOT_TOKEN:
    raise SystemExit("ERROR: BOT_TOKEN is missing. Set it in ~/.bashrc, then run: source ~/.bashrc")

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


def now_dt():
    return datetime.now(TZ)


def now_str():
    return now_dt().strftime("%Y-%m-%d %I:%M:%S %p (BDT)")


def money(value):
    return f"৳{float(value):.2f}"


def db_init():
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, username TEXT,
          balance REAL NOT NULL DEFAULT 0, referrer_id INTEGER, join_date TEXT NOT NULL,
          referral_earnings REAL NOT NULL DEFAULT 0, total_referrals INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS deposits(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
          method TEXT NOT NULL, trxid TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'Pending Approval',
          created_at TEXT NOT NULL, reviewed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, game_uid TEXT NOT NULL,
          player_name TEXT, likes INTEGER NOT NULL, price REAL NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, period_key TEXT
        );
        CREATE TABLE IF NOT EXISTS referrals(
          id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL UNIQUE,
          bonus REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS balance_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
          amount REAL NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
        # Migration safety for databases created by earlier versions.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "referral_earnings" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN referral_earnings REAL NOT NULL DEFAULT 0")
        if "total_referrals" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN total_referrals INTEGER NOT NULL DEFAULT 0")


db_init()


def get_user(uid):
    return conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()


def ensure_user(tg_user, start_arg=None):
    uid = tg_user.id
    existed = get_user(uid)
    full_name = (tg_user.full_name or "Telegram User")[:200]
    username = tg_user.username
    if existed:
        with conn:
            conn.execute("UPDATE users SET full_name=?, username=? WHERE user_id=?",
                         (full_name, username, uid))
        return False
    referrer = None
    if start_arg and start_arg.startswith("REF"):
        try:
            candidate = int(start_arg[3:])
            if candidate != uid and get_user(candidate):
                referrer = candidate
        except ValueError:
            pass
    with conn:
        conn.execute(
            "INSERT INTO users(user_id,full_name,username,balance,referrer_id,join_date) VALUES(?,?,?,?,?,?)",
            (uid, full_name, username, 0, referrer, now_str())
        )
        if referrer:
            conn.execute("INSERT OR IGNORE INTO referrals(referrer_id,referred_id,bonus,created_at) VALUES(?,?,?,?)",
                         (referrer, uid, JOIN_BONUS, now_str()))
            if conn.execute("SELECT changes()").fetchone()[0]:
                conn.execute("UPDATE users SET balance=balance+?, referral_earnings=referral_earnings+?, total_referrals=total_referrals+1 WHERE user_id=?",
                             (JOIN_BONUS, JOIN_BONUS, referrer))
    return True


def main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🛒 BUY DAILY LIKE"), KeyboardButton("💰 ADD MONEY")],
        [KeyboardButton("👑 MY INFO"), KeyboardButton("📋 MY HISTORY")],
        [KeyboardButton("🎁 REFER & EARN"), KeyboardButton("💬 SUPPORT")],
        [KeyboardButton("🔄 REFRESH BOT")]
    ], resize_keyboard=True)


def back_kb(*buttons):
    rows = []
    for b in buttons:
        rows.append([InlineKeyboardButton(b[0], callback_data=b[1])])
    return InlineKeyboardMarkup(rows)


def channel_gate(missing_channels):
    rows = []
    if 1 in missing_channels:
        rows.append([
            InlineKeyboardButton("📢 JOIN CHANNEL 1", url=JOIN_LINK_1)
        ])
    if 2 in missing_channels:
        rows.append([
            InlineKeyboardButton("📢 JOIN CHANNEL 2", url=JOIN_LINK_2)
        ])
    rows.append([
        InlineKeyboardButton("✅ VERIFY", callback_data="verify")
    ])
    return InlineKeyboardMarkup(rows)


async def is_member(bot, uid, channel):
    try:
        member = await bot.get_chat_member(
            chat_id=channel, user_id=uid
        )
        return member.status in ("member", "administrator", "creator")
    except Exception as exc:
        log.warning("Membership check failed for %s: %s", channel, exc)
        return False


async def check_gate(update_or_query, context, uid):
    ok1, ok2 = await asyncio.gather(
        is_member(context.bot, uid, JOIN_CHANNEL_1),
        is_member(context.bot, uid, JOIN_CHANNEL_2),
    )
    return ok1 and ok2


async def show_gate(target, context):
    uid = (
        target.effective_user.id
        if isinstance(target, Update)
        else target.from_user.id
    )

    ok1 = await is_member(context.bot, uid, JOIN_CHANNEL_1)
    ok2 = await is_member(context.bot, uid, JOIN_CHANNEL_2)

    missing = []
    missing_names = []

    if not ok1:
        missing.append(1)
        missing_names.append(JOIN_CHANNEL_1)
    if not ok2:
        missing.append(2)
        missing_names.append(JOIN_CHANNEL_2)

    if not missing:
        if isinstance(target, Update):
            await welcome(target, context)
        else:
            await target.edit_message_text(
                "✅ CHANNEL VERIFICATION SUCCESSFUL!"
            )
            await context.bot.send_message(
                uid, "🏠 Main Menu", reply_markup=main_keyboard()
            )
        return

    channels_text = "\n".join(f"➖ {name}" for name in missing_names)
    text = (
        "⚠️ CHANNEL JOIN REQUIRED!\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "🎉 বট ব্যবহার করতে নিচের যে চ্যানেলে নেই, সেটিতে Join করুন।\n\n"
        f"{channels_text}\n\n"
        "জয়েন করার পর VERIFY বাটনে ক্লিক করুন।\n"
        "━━━━━━━━━━━━━━━━━━━"
    )

    markup = channel_gate(missing)

    if isinstance(target, Update):
        message = target.effective_message
        if message is None:
            log.error("Cannot show channel gate: no effective message")
            return
        await message.reply_text(text, reply_markup=markup)
    else:
        await target.edit_message_text(text, reply_markup=markup)


async def welcome(update, context):
    u = update.effective_user
    row = get_user(u.id)
    name = row["full_name"] if row else u.full_name
    uname = f"@{row['username']}" if row and row["username"] else "Not set"
    balance = row["balance"] if row else 0
    text = (
        "🔥 WELCOME TO FIRE LIKE BOT!\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Name: {name}\n📝 Username: {uname}\n🆔 User ID: {u.id}\n💰 Balance: {money(balance)}\n\n"
        "🌟 স্বাগতম! বট ব্যবহার করার জন্য ধন্যবাদ!\n\n"
        "🤖 FREE FIRE DAILY LIKE BOT\n"
        "═════════════════════\n"
        "🔥 Get 200+ Likes Daily\n💎 Auto Like Service\n⚡ Instant Delivery\n🛡️ 100% Trusted\n\n"
        "━━━━━━━━━━━━━━━━━━━"
    )
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0] if context.args else None
    is_new = ensure_user(update.effective_user, arg)
    new_row = get_user(update.effective_user.id)
    if is_new and new_row and new_row["referrer_id"]:
        ref = get_user(new_row["referrer_id"])
        await send_history(context,
            "🎁 NEW REFERRAL!\n━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Referrer ID: {new_row['referrer_id']}\n🆔 Referred ID: {update.effective_user.id}\n"
            f"👑 Total Referrals: {ref['total_referrals'] if ref else 0}\n"
            f"💰 Referrer Balance: {money(ref['balance'] if ref else 0)}\n"
            f"🕐 Time: {now_str()}\n━━━━━━━━━━━━━━━━━━━")
    if not await check_gate(update, context, update.effective_user.id):
        await show_gate(update, context)
        return
    await welcome(update, context)


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_gate(update, context, q.from_user.id):
        await q.edit_message_text("✅ CHANNEL VERIFICATION SUCCESSFUL!")
        row = get_user(q.from_user.id)
        if row:
            name = row["full_name"]
            uname = f"@{row['username']}" if row["username"] else "Not set"
            text = (
                "🔥 WELCOME TO FIRE LIKE BOT!\n━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Name: {name}\n📝 Username: {uname}\n🆔 User ID: {q.from_user.id}\n"
                f"💰 Balance: {money(row['balance'])}\n\n"
                "🌟 স্বাগতম! বট ব্যবহার করার জন্য ধন্যবাদ!\n\n"
                "🤖 FREE FIRE DAILY LIKE BOT\n═════════════════════\n"
                "🔥 Get 200+ Likes Daily\n💎 Auto Like Service\n⚡ Instant Delivery\n🛡️ 100% Trusted\n\n━━━━━━━━━━━━━━━━━━━"
            )
        else:
            text = "✅ Verified! Send /start to continue."
        await context.bot.send_message(q.from_user.id, text, reply_markup=main_keyboard())
    else:
        await q.answer("দুটি Channel-এই Join করো, তারপর আবার Verify করো।", show_alert=True)


def current_period_key():
    now = now_dt()
    if now.hour < RESET_HOUR:
        from datetime import timedelta
        now = now - timedelta(days=1)
    return now.strftime("%Y-%m-%d")


async def send_history(context, text):
    if not HISTORY_CHANNEL:
        return
    try:
        await context.bot.send_message(chat_id=HISTORY_CHANNEL, text=text)
    except Exception:
        log.exception("Could not post to history channel. Check bot admin/post permission.")


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = (msg.text or "").strip()
    uid = update.effective_user.id
    if uid != ADMIN_ID and not await check_gate(update, context, uid):
        context.user_data["state"] = None
        await show_gate(update, context)
        return
    user = get_user(uid)
    if text == "🔄 REFRESH BOT":
        await start(update, context)
        return
    if text == "🛒 BUY DAILY LIKE":
        balance = user["balance"] if user else 0
        await msg.reply_text(
            f"💰 Your Balance: {money(balance)}\n💎 Price: {money(PRICE)}\n📈 Likes You Get: {LIKES_PER_ORDER}\n🚨 15.0 Taka for 200 Likes",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("☑ CONTINUE", callback_data="buy_continue"),
                                                InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]])
        )
        return
    if text == "💰 ADD MONEY":
        context.user_data["state"] = "deposit_amount"
        await msg.reply_text(
            "💵 ADD MONEY\n━━━━━━━━━━━━━━━━━━━\n🔽 Please enter amount:\n(Minimum: 10 BDT)\n━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
            ])
        )
        return
    if text == "👑 MY INFO":
        row = get_user(uid)
        name = row["full_name"] if row else msg.from_user.full_name
        username = f"@{row['username']}" if row and row["username"] else "Not set"
        balance = row["balance"] if row else 0

        total_deposit = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM deposits WHERE user_id=? AND status='Approved'",
            (uid,)
        ).fetchone()["total"]

        total_spent = conn.execute(
            "SELECT COALESCE(SUM(price), 0) AS total FROM orders WHERE user_id=? AND status IN ('Completed', 'Success', 'Approved')",
            (uid,)
        ).fetchone()["total"]

        channel_status = "ℹ️ Check via VERIFY"

        await msg.reply_text(
            "👤 MY INFO\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            f"👑 Name: {name}\n"
            f"📝 Username: {username}\n"
            f"🆔 User ID: {uid}\n"
            f"💰 Balance: {money(balance)}\n"
            f"💵 Total Deposit: {money(total_deposit)}\n"
            f"💸 Total Spent: {money(total_spent)}\n"
            f"📅 Join Date: {row['join_date'] if row else now_str()}\n"
            f"🔗 Channel Status: {channel_status}\n"
            "━━━━━━━━━━━━━━━━━━━"
        )
        return
    if text == "📋 MY HISTORY":
        await msg.reply_text("📋 MY HISTORY", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Like Orders", callback_data="like_history")],
            [InlineKeyboardButton("💰 Deposit History", callback_data="deposit_history")],
            [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
        ]))
        return
    if text == "🎁 REFER & EARN":
        link = f"https://t.me/{BOT_USERNAME}?start=REF{uid}"
        row = get_user(uid)
        await msg.reply_text(
            "⚠️ REFER & EARN নিয়ম\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💸 Invite Friends & Earn Money!\n\n"
            f"🎁 লিংক শেয়ার করার সাথে সাথে আপনি {money(1)} পাবেন (নতুন ইউজার চ্যানেলে জয়েন করার পর)।\n\n"
            f"💰 আপনার বন্ধুর প্রতিটি Deposit থেকে পাবেন {REFERRAL_COMMISSION_PERCENT:.0f}% কমিশন।\n\n"
            "নতুন ইউজারকে অবশ্যই আমাদের সবগুলো চ্যানেলে জয়েন করতে হবে।\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "🔗 Your Referral Link:\n"
            f"{link}\n\n"
            f"👥 Total Referrals: {row['total_referrals'] if row else 0}\n"
            f"💰 Referral Earnings: {money(row['referral_earnings'] if row else 0)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 COPY REFERRAL LINK", copy_text=CopyTextButton(link))],
                [InlineKeyboardButton("📜 REFERRAL HISTORY", callback_data="ref_history")],
                [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
            ])
        )
        return
    if text == "💬 SUPPORT":
        await msg.reply_text("🆘 SUPPORT\n━━━━━━━━━━━━━━━━━━━\n👨‍💼 For any problems, contact admin!\n━━━━━━━━━━━━━━━━━━━",
                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📩 CONTACT ADMIN", url=SUPPORT_LINK)]]))
        return
    if text.startswith("/"):
        return
    # Input states (UID, deposit amount, trx, admin search, admin amount)
    state = context.user_data.get("state")
    if state == "deposit_amount":
        try:
            amount = float(text)
            if amount < MIN_DEPOSIT or amount > 100000:
                raise ValueError()
        except ValueError:
            await msg.reply_text("❌ Invalid amount. Minimum: 10 BDT. Please enter amount again.")
            return
        context.user_data["deposit_amount"] = round(amount, 2)
        context.user_data["state"] = None
        await msg.reply_text(f"💳 PAYMENT METHOD\n💵 Amount: {money(amount)}",
                             reply_markup=InlineKeyboardMarkup([
                                 [InlineKeyboardButton("💸 PAY WITH bKash", callback_data="bkash_pay")],
                                 [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
                             ]))
        return
    if state == "enter_uid":
        if not re.fullmatch(r"\d{5,20}", text):
            await msg.reply_text("❌ INVALID UID!\nPlease enter a valid numeric Free Fire UID.")
            return
        game_uid = text
        period = current_period_key()
        previous = conn.execute("SELECT * FROM orders WHERE game_uid=? AND period_key=? AND status IN ('Success','Processing')",
                                (game_uid, period)).fetchone()
        if previous:
            await msg.reply_text(
                f"⚠️ ALREADY LIKED!\n━━━━━━━━━━━━━━━━━━━\n🎮 UID: {game_uid}\n👤 Player: {previous['player_name'] or 'Unknown'}\n"
                "🌍 Server: BD\n📈 Current Likes: Not available\n🔄 Status: Already processed\n\nℹ️ This UID already has likes!\n🌟 No charge was made.\n━━━━━━━━━━━━━━━━━━━",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]])
            )
            context.user_data["state"] = None
            return
        row = get_user(uid)
        if not row or row["balance"] < PRICE:
            context.user_data["state"] = None
            await msg.reply_text(f"🚫 INSUFFICIENT BALANCE!\n💰 Your Balance: {money(row['balance'] if row else 0)}\n💵 Required: {money(PRICE)}\n❌ You don't have enough balance!\nℹ️ Please add money to continue.",
                                 reply_markup=InlineKeyboardMarkup([
                                     [InlineKeyboardButton("💵 ADD MONEY", callback_data="add_money")],
                                     [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
                                 ]))
            return
        if not LIKE_API_URL:
            await msg.reply_text("⚠️ LIKE API NOT CONFIGURED\nYour UID was not charged. Add your authorized Like API URL in Termux settings before ordering.",
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]]))
            context.user_data["state"] = None
            return
        try:
            result = call_like_api(game_uid)
            if not result.get("success"):
                raise RuntimeError(str(result.get("message", "API did not confirm success")))
            before = result.get("before", "Unknown")
            after = result.get("after", "Unknown")
            player = str(result.get("player_name", "Unknown"))
            with conn:
                conn.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (PRICE, uid, PRICE))
                conn.execute("INSERT INTO orders(user_id,game_uid,player_name,likes,price,status,created_at,period_key) VALUES(?,?,?,?,?,?,?,?)",
                             (uid, game_uid, player, LIKES_PER_ORDER, PRICE, "Success", now_str(), period))
            await msg.reply_text(
                f"✅ LIKES ADDED SUCCESSFULLY!\n━━━━━━━━━━━━━━━━━━━\n🎮 UID: {game_uid}\n👤 Player: {player}\n🌍 Server: {result.get('server','BD')}\n"
                f"📈 Before: {before}\n📈 Given: {LIKES_PER_ORDER}\n📈 After: {after}\n💰 Price: {money(PRICE)}\n━━━━━━━━━━━━━━━━━━━",
                reply_markup=main_keyboard()
            )
        except Exception as exc:
            log.exception("Like API request failed")
            await msg.reply_text("❌ LIKE ORDER FAILED\nNo success was confirmed. Please contact support; do not retry repeatedly if the API may have processed it.")
        context.user_data["state"] = None
        return
    if state == "deposit_trx":
        trxid = text.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{5,80}", trxid):
            await msg.reply_text("❌ Invalid Transaction ID. Please enter the correct ID.")
            return
        amount = float(context.user_data.get("deposit_amount", 0))
        try:
            with conn:
                conn.execute("INSERT INTO deposits(user_id,amount,method,trxid,status,created_at) VALUES(?,?,?,?,?,?)",
                             (uid, amount, "bKash Personal", trxid, "Pending Approval", now_str()))
        except sqlite3.IntegrityError:
            await msg.reply_text("❌ This Transaction ID has already been submitted.")
            return
        context.user_data["state"] = None
        await msg.reply_text(
            f"✅ DEPOSIT REQUEST SUBMITTED!\n━━━━━━━━━━━━━━━━━━━\n💵 Amount: {money(amount)}\n💳 Payment Method: bKash Personal\n"
            f"🧾 Transaction ID: {trxid}\n⏳ Status: Pending Approval\n📩 Your deposit request has been sent to Admin.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 CONTACT ADMIN", url="https://t.me/redwan_islam007")],
                [InlineKeyboardButton("🏠 MAIN MENU", callback_data="main_menu")]
            ])
        )
        username = f"@{msg.from_user.username}" if msg.from_user.username else "Not set"
        admin_text = (
            "💳 NEW DEPOSIT REQUEST\n━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Name: {msg.from_user.full_name}\n📝 Username: {username}\n🆔 User ID: {uid}\n"
            f"💵 Amount: {money(amount)}\n💳 Method: bKash Personal\n🧾 Transaction ID: {trxid}\n"
            f"🕐 Time: {now_str()}\n━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(ADMIN_ID, admin_text, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ APPROVE", callback_data=f"approve:{trxid}"),
            InlineKeyboardButton("❌ REJECT", callback_data=f"reject:{trxid}")
        ]]))
        return
    if state == "admin_search":
        if uid != ADMIN_ID:
            return
        target = None
        if text.isdigit():
            target = get_user(int(text))
        else:
            target = conn.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (text.lstrip("@"),)).fetchone()
        if not target:
            await msg.reply_text("❌ User not found.")
            return
        context.user_data["admin_target"] = target["user_id"]
        context.user_data["state"] = None
        await msg.reply_text(f"👤 User ID: {target['user_id']}\nName: {target['full_name']}\nBalance: {money(target['balance'])}",
                             reply_markup=InlineKeyboardMarkup([
                                 [InlineKeyboardButton("➕ ADD BALANCE", callback_data="admin_add")],
                                 [InlineKeyboardButton("➖ REMOVE BALANCE", callback_data="admin_remove")]
                             ]))
        return
    if state == "admin_amount":
        if uid != ADMIN_ID:
            return
        try:
            amount = round(float(text), 2)
            if amount <= 0 or amount > 10000000:
                raise ValueError()
        except ValueError:
            await msg.reply_text("Enter a valid positive amount.")
            return
        action = context.user_data.get("admin_action")
        target_id = context.user_data.get("admin_target")
        target = get_user(target_id) if target_id else None
        if not target:
            await msg.reply_text("User not found.")
            context.user_data["state"] = None
            return
        with conn:
            if action == "add":
                conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target_id))
            else:
                cur = conn.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?", (amount, target_id, amount))
                if cur.rowcount == 0:
                    await msg.reply_text("❌ Amount exceeds current balance; no change made.")
                    context.user_data["state"] = None
                    return
            conn.execute("INSERT INTO balance_logs(admin_id,target_id,amount,action,created_at) VALUES(?,?,?,?,?)",
                         (uid, target_id, amount, action, now_str()))
        context.user_data["state"] = None
        await msg.reply_text(f"✅ Balance updated.\nUser: {target_id}\nAmount: {money(amount)}\nAction: {action}\nNew balance: {money(get_user(target_id)['balance'])}")
        return


def call_like_api(game_uid):
    """Generic placeholder integration. Adapt request/response keys to your authorized API docs."""
    params = {"uid": game_uid, "likes": str(LIKES_PER_ORDER)}
    url = LIKE_API_URL
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(url + separator + urllib.parse.urlencode(params))
    if LIKE_API_KEY:
        request.add_header("Authorization", f"Bearer {LIKE_API_KEY}")
        request.add_header("X-API-Key", LIKE_API_KEY)
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    # API-specific mapping is required; never assume success from HTTP 200 alone.
    if not isinstance(payload, dict):
        return {"success": False, "message": "Unexpected API response"}
    success = payload.get("success") is True or str(payload.get("status", "")).lower() in ("success", "ok", "completed")
    return {
        "success": success,
        "message": payload.get("message", ""),
        "before": payload.get("before", payload.get("likes_before", "Unknown")),
        "after": payload.get("after", payload.get("likes_after", "Unknown")),
        "player_name": payload.get("player_name", payload.get("name", "Unknown")),
        "server": payload.get("server", "BD")
    }


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""
    if data == "verify":
        await verify_callback(update, context)
        return
    if uid != ADMIN_ID and not await check_gate(update, context, uid):
        context.user_data["state"] = None
        await show_gate(q, context)
        return
    if data == "buy_continue":
        row = get_user(uid)
        if not row or row["balance"] < PRICE:
            await q.edit_message_text(
                f"🚫 INSUFFICIENT BALANCE!\n💰 Your Balance: {money(row['balance'] if row else 0)}\n💵 Required: {money(PRICE)}\n❌ You don't have enough balance!\nℹ️ Please add money to continue.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💵 ADD MONEY", callback_data="add_money")],
                    [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
                ]))
        else:
            context.user_data["state"] = "enter_uid"
            await q.edit_message_text("📝 ENTER YOUR GAME UID")
        return
    if data == "bkash_pay":
        amount = context.user_data.get("deposit_amount", 0)
        await q.edit_message_text(
            f"💸 PAY WITH bKash\n━━━━━━━━━━━━━━━━━━━\n💳 Payment Method: bKash Personal\n📱 Number: {BKASH_NUMBER}\n"
            f"💵 Amount: {money(amount)}\n📝 উপরের নম্বরে টাকা Send Money করুন।\n⚠️ Please enter the correct Transaction ID after payment.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I HAVE PAID", callback_data="paid")],
                [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
            ]))
        return
    if data == "paid":
        context.user_data["state"] = "deposit_trx"
        amount = context.user_data.get("deposit_amount", 0)
        await q.edit_message_text(f"🧾 ENTER TRANSACTION ID\n━━━━━━━━━━━━━━━━━━━\n💳 Payment Method: bKash Personal\n💵 Amount: {money(amount)}\n📝 Please enter your bKash Transaction ID:")
        return
    if data == "add_money":
        context.user_data["state"] = "deposit_amount"
        await q.edit_message_text(
            "💵 ADD MONEY\n━━━━━━━━━━━━━━━━━━━\n🔽 Please enter amount:\n(Minimum: 10 BDT)\n━━━━━━━━━━━━━━━━━━━",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]
            ])
        )
        return
    if data in ("like_history", "deposit_history", "ref_history"):
        if data == "like_history":
            rows = conn.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
            if not rows:
                text = "📭 No Like Orders Found!"
            else:
                text = "🛒 LIKE ORDERS HISTORY\n━━━━━━━━━━━━━━━━━━━\n"
                for r in rows:
                    text += (f"\n🎮 Game UID: {r['game_uid']}\n📈 Likes: {r['likes']}\n💰 Price: {money(r['price'])}\n"
                             f"📌 Status: {r['status']}\n🕐 Date & Time: {r['created_at']}\n━━━━━━━━━━━━━━━━━━━\n")
        elif data == "deposit_history":
            rows = conn.execute("SELECT * FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
            if not rows:
                text = "📭 No Deposit History Found!"
            else:
                text = "💰 DEPOSIT HISTORY\n━━━━━━━━━━━━━━━━━━━\n"
                for r in rows:
                    text += (f"\n💵 Amount: {money(r['amount'])}\n💳 Payment Method: {r['method']}\n🧾 Transaction ID: {r['trxid']}\n"
                             f"📌 Status: {r['status']}\n🕐 Date & Time: {r['created_at']}\n━━━━━━━━━━━━━━━━━━━\n")
        else:
            rows = conn.execute("SELECT * FROM referrals WHERE referrer_id=? ORDER BY id DESC LIMIT 10", (uid,)).fetchall()
            if not rows:
                text = "📭 No Referral History Found!"
            else:
                text = "🎁 REFERRAL HISTORY\n━━━━━━━━━━━━━━━━━━━\n"
                for r in rows:
                    text += f"\n🆔 Referred ID: {r['referred_id']}\n🎁 Join Bonus: {money(r['bonus'])}\n🕐 Date & Time: {r['created_at']}\n━━━━━━━━━━━━━━━━━━━\n"
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 ◁ BACK", callback_data="back")]]))
        return
    if data.startswith("approve:") or data.startswith("reject:"):
        if uid != ADMIN_ID:
            await q.answer("Admin only.", show_alert=True)
            return
        action, trxid = data.split(":", 1)
        dep = conn.execute("SELECT * FROM deposits WHERE trxid=?", (trxid,)).fetchone()
        if not dep or dep["status"] != "Pending Approval":
            await q.edit_message_text("⚠️ Deposit request not found or already reviewed.")
            return
        if action == "approve":
            # Admin must verify payment manually before pressing Approve.
            with conn:
                conn.execute("UPDATE deposits SET status='Approved', reviewed_at=? WHERE trxid=?", (now_str(), trxid))
                conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (dep["amount"], dep["user_id"]))
                user = get_user(dep["user_id"])
                if user and user["referrer_id"]:
                    commission = round(dep["amount"] * REFERRAL_COMMISSION_PERCENT / 100, 2)
                    conn.execute("UPDATE users SET balance=balance+?, referral_earnings=referral_earnings+? WHERE user_id=?",
                                 (commission, commission, user["referrer_id"]))
            await q.edit_message_text(f"✅ DEPOSIT APPROVED!\nUser ID: {dep['user_id']}\nAmount: {money(dep['amount'])}\nTrxID: {trxid}")
            await context.bot.send_message(dep["user_id"], f"✅ DEPOSIT APPROVED!\n💵 Amount: {money(dep['amount'])}\n💰 New Balance: {money(get_user(dep['user_id'])['balance'])}")
            await send_history(context, f"💰 NEW DEPOSIT!\n━━━━━━━━━━━━━━━━━━━\n🆔 User ID: {dep['user_id']}\n💵 Amount: {money(dep['amount'])}\n🕐 Time: {now_str()}\n━━━━━━━━━━━━━━━━━━━")
        else:
            with conn:
                conn.execute("UPDATE deposits SET status='Rejected', reviewed_at=? WHERE trxid=?", (now_str(), trxid))
            await q.edit_message_text(f"❌ DEPOSIT REJECTED\nUser ID: {dep['user_id']}\nAmount: {money(dep['amount'])}\nTrxID: {trxid}")
            await context.bot.send_message(dep["user_id"], f"❌ DEPOSIT REJECTED\n💵 Amount: {money(dep['amount'])}\n🧾 Transaction ID: {trxid}")
        return
    if uid != ADMIN_ID and data.startswith("admin_"):
        await q.answer("Admin only.", show_alert=True)
        return
    if data == "main_menu":
        context.user_data["state"] = None
        row = get_user(uid)
        name = row["full_name"] if row else q.from_user.full_name
        balance = row["balance"] if row else 0
        text = (
            "🔥 MAIN MENU\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: {name}\n"
            f"💰 Balance: {money(balance)}\n"
            "⬇️ Select an option below:"
        )
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_text(text, reply_markup=main_keyboard())
        return

    if data == "back":
        context.user_data["state"] = None
        row = get_user(uid)
        name = row["full_name"] if row else q.from_user.full_name
        balance = row["balance"] if row else 0
        text = (
            "🔥 MAIN MENU\n"
            "━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Name: {name}\n"
            f"💰 Balance: {money(balance)}\n"
            "⬇️ Select an option below:"
        )
        await q.edit_message_text(text)
        await context.bot.send_message(
            chat_id=uid,
            text="⬇️ Select an option below:",
            reply_markup=main_keyboard()
        )
        return
    if data == "admin_panel":
        await q.edit_message_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 DEPOSIT REQUESTS", callback_data="admin_deposits")],
            [InlineKeyboardButton("➕ ADD USER BALANCE", callback_data="admin_search_add")],
            [InlineKeyboardButton("➖ REMOVE USER BALANCE", callback_data="admin_search_remove")],
            [InlineKeyboardButton("🔎 SEARCH USER", callback_data="admin_search")]
        ]))
        return
    if data in ("admin_search_add", "admin_search_remove", "admin_search"):
        context.user_data["state"] = "admin_search"
        context.user_data["admin_action"] = "add" if data.endswith("add") else "remove" if data.endswith("remove") else None
        await q.edit_message_text("🔎 Enter target user's numeric Telegram ID or username (without @).")
        return
    if data in ("admin_add", "admin_remove"):
        context.user_data["admin_action"] = "add" if data == "admin_add" else "remove"
        context.user_data["state"] = "admin_amount"
        await q.edit_message_text(f"Enter amount to {context.user_data['admin_action']} for user {context.user_data.get('admin_target')}:")
        return
    if data == "admin_deposits":
        if uid != ADMIN_ID:
            return
        rows = conn.execute("SELECT * FROM deposits WHERE status='Pending Approval' ORDER BY id LIMIT 10").fetchall()
        if not rows:
            await q.edit_message_text("📭 No pending deposits.")
            return
        for r in rows:
            await context.bot.send_message(ADMIN_ID, f"💳 DEPOSIT REQUEST\nUser: {r['user_id']}\nAmount: {money(r['amount'])}\nTrxID: {r['trxid']}\nTime: {r['created_at']}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ APPROVE", callback_data=f"approve:{r['trxid']}"),
                                                    InlineKeyboardButton("❌ REJECT", callback_data=f"reject:{r['trxid']}")]]))
        await q.edit_message_text(f"Sent {len(rows)} pending request(s) above.")
        return


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("⛔ Access denied.")
        return
    await update.effective_message.reply_text("👑 ADMIN PANEL", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 DEPOSIT REQUESTS", callback_data="admin_deposits")],
        [InlineKeyboardButton("➕ ADD USER BALANCE", callback_data="admin_search_add")],
        [InlineKeyboardButton("➖ REMOVE USER BALANCE", callback_data="admin_search_remove")],
        [InlineKeyboardButton("🔎 SEARCH USER", callback_data="admin_search")]
    ]))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled bot error", exc_info=context.error)



async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        await msg.reply_text("⛔ Unauthorized.")
        return

    if len(context.args) != 2:
        await msg.reply_text("Usage: /add USER_ID AMOUNT")
        return

    try:
        target_id = int(context.args[0])
        amount = round(float(context.args[1]), 2)
        if target_id <= 0 or amount <= 0 or amount > 10000000:
            raise ValueError()
    except ValueError:
        await msg.reply_text("❌ Invalid user ID or amount.")
        return

    target = get_user(target_id)
    if not target:
        await msg.reply_text("❌ User not found in bot database.")
        return

    with conn:
        cur = conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, target_id)
        )
        if cur.rowcount != 1:
            await msg.reply_text("❌ Balance was not updated.")
            return
        conn.execute(
            "INSERT INTO balance_logs(admin_id,target_id,amount,action,created_at) VALUES(?,?,?,?,?)",
            (user.id, target_id, amount, "add", now_str())
        )

    updated = get_user(target_id)
    await msg.reply_text(
        f"✅ Balance added successfully.\n"
        f"🆔 User ID: {target_id}\n"
        f"➕ Added: {money(amount)}\n"
        f"💰 New balance: {money(updated['balance'])}"
    )

    await send_history(
        context,
        f"💰 NEW DEPOSIT!\n━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: {target_id}\n"
        f"💵 Amount: {money(amount)}\n"
        f"🕐 Time: {now_str()}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    if not user or user.id != ADMIN_ID:
        await msg.reply_text("⛔ Unauthorized.")
        return

    text = " ".join(context.args).strip()
    if not text:
        await msg.reply_text(
            "ব্যবহার: /broadcast তোমার ঘোষণা এখানে লিখো"
        )
        return

    rows = conn.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    failed = 0

    await msg.reply_text(f"📢 Broadcast শুরু হচ্ছে... মোট user: {len(rows)}")

    for row in rows:
        try:
            await context.bot.send_message(chat_id=row["user_id"], text=text)
            sent += 1
        except Exception as e:
            failed += 1
            log.warning("Broadcast failed for user %s: %s", row["user_id"], e)

    await msg.reply_text(
        f"✅ Broadcast শেষ!\n📨 পাঠানো হয়েছে: {sent}\n❌ পাঠানো যায়নি: {failed}"
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("add", add_balance_command))
    app.add_handler(CommandHandler("post", broadcast_command))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    app.add_error_handler(error_handler)
    log.info("Bot starting as @%s", BOT_USERNAME)
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
