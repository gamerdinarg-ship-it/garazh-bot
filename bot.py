import os
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                           MessageHandler, filters, ContextTypes, ConversationHandler)

BOT_TOKEN = os.environ.get('BOT_TOKEN')

CARS = {
    'logan': '🚗 Renault Logan',
    'vesta': '🚙 Lada Vesta',
    'crv':   '🏎 Honda CR-V',
}

WAITING_KM, WAITING_COST, WAITING_INTERVAL = range(3)


# ─── База данных ────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect('cars.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS oil_changes (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        car_id TEXT    NOT NULL,
        date   TEXT    NOT NULL,
        km     INTEGER NOT NULL,
        cost   REAL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS car_settings (
        car_id   TEXT    PRIMARY KEY,
        interval INTEGER NOT NULL DEFAULT 10000
    )''')
    conn.commit()
    conn.close()

def get_interval(car_id):
    conn = sqlite3.connect('cars.db')
    row = conn.execute('SELECT interval FROM car_settings WHERE car_id=?', (car_id,)).fetchone()
    conn.close()
    return row[0] if row else 10000

def set_interval(car_id, interval):
    conn = sqlite3.connect('cars.db')
    conn.execute('INSERT OR REPLACE INTO car_settings (car_id, interval) VALUES (?,?)', (car_id, interval))
    conn.commit()
    conn.close()

def get_last(car_id):
    conn = sqlite3.connect('cars.db')
    row = conn.execute(
        'SELECT date, km, cost FROM oil_changes WHERE car_id=? ORDER BY km DESC LIMIT 1',
        (car_id,)
    ).fetchone()
    conn.close()
    return row

def get_history(car_id):
    conn = sqlite3.connect('cars.db')
    rows = conn.execute(
        'SELECT date, km, cost FROM oil_changes WHERE car_id=? ORDER BY km DESC',
        (car_id,)
    ).fetchall()
    conn.close()
    return rows

def save_change(car_id, km, cost=None):
    conn = sqlite3.connect('cars.db')
    conn.execute(
        'INSERT INTO oil_changes (car_id, date, km, cost) VALUES (?,?,?,?)',
        (car_id, datetime.now().strftime('%d.%m.%Y'), km, cost)
    )
    conn.commit()
    conn.close()

def get_totals(car_id):
    conn = sqlite3.connect('cars.db')
    row = conn.execute(
        'SELECT COALESCE(SUM(cost),0), COUNT(*) FROM oil_changes WHERE car_id=?', (car_id,)
    ).fetchone()
    conn.close()
    return row  # (total_cost, count)


# ─── Форматирование ─────────────────────────────────────────

def fkm(km):
    return f"{km:,}".replace(',', ' ')

def fcost(cost):
    return f"{int(cost):,} ₽".replace(',', ' ') if cost else "не указана"

def bar(done, total, n=18):
    pct = min(done / total, 1.0)
    f = int(n * pct)
    return f"{'█'*f}{'░'*(n-f)} {int(pct*100)}%"


# ─── Главное меню ────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = []
    for car_id, car_name in CARS.items():
        last = get_last(car_id)
        interval = get_interval(car_id)
        if last:
            _, km, _ = last
            next_km = km + interval
            label = f"{car_name}  📍 {fkm(km)} км"
        else:
            label = f"{car_name}  ❓ нет данных"
        rows.append([InlineKeyboardButton(label, callback_data=f'car_{car_id}')])

    rows.append([InlineKeyboardButton("💰 Расходы по всему гаражу", callback_data='expenses_all')])
    markup = InlineKeyboardMarkup(rows)
    text = "🔧 *Семейный гараж*\n\nВыберите автомобиль:"

    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')


# ─── Карточка машины ────────────────────────────────────────

async def show_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id   = q.data.replace('car_', '')
    car_name = CARS[car_id]
    last     = get_last(car_id)
    interval = get_interval(car_id)

    text = f"*{car_name}*\n{'─'*32}\n\n"

    if last:
        date, km, cost = last
        text += f"🔧 *Последняя замена масла:*\n"
        text += f"   📅 {date}\n"
        text += f"   📍 {fkm(km)} км\n"
        text += f"   💰 {fcost(cost)}\n\n"
        text += f"⚙️ Интервал замены: *{fkm(interval)} км*\n"
        text += f"📌 Следующая при *{fkm(km + interval)} км*\n"
        text += f"`{bar(0, interval)}`\n"
    else:
        text += "❗ *Замен масла ещё не записано*\n\n"
        text += f"⚙️ Интервал замены: *{fkm(interval)} км*\n"

    text += f"\n{'─'*32}"

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Записать замену", callback_data=f'record_{car_id}')],
        [InlineKeyboardButton("📋 История",         callback_data=f'history_{car_id}'),
         InlineKeyboardButton("💰 Расходы",         callback_data=f'expenses_{car_id}')],
        [InlineKeyboardButton("⚙️ Изменить интервал", callback_data=f'interval_{car_id}')],
        [InlineKeyboardButton("🔙 Назад",           callback_data='back')],
    ])
    await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')


# ─── История ────────────────────────────────────────────────

async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id   = q.data.replace('history_', '')
    car_name = CARS[car_id]
    rows     = get_history(car_id)

    text = f"*{car_name}*\n📋 *История замен*\n{'─'*32}\n\n"

    if rows:
        for i, (date, km, cost) in enumerate(rows):
            text += f"*Замена №{len(rows)-i}*\n"
            text += f"   📅 {date}\n"
            text += f"   📍 {fkm(km)} км  💰 {fcost(cost)}\n"
            if i + 1 < len(rows):
                diff = km - rows[i+1][1]
                text += f"   ↕️ интервал: {fkm(diff)} км\n"
            text += "\n"

        total, count = get_totals(car_id)
        text += f"{'─'*32}\n"
        text += f"Всего замен: *{count}*\n"
        if total:
            text += f"Потрачено: *{fcost(total)}*"
    else:
        text += "Замен ещё не записано."

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'car_{car_id}')]])
    await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')


# ─── Расходы по машине ───────────────────────────────────────

async def show_expenses_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id   = q.data.replace('expenses_', '')
    car_name = CARS[car_id]
    rows     = get_history(car_id)

    text = f"*{car_name}*\n💰 *Расходы на масло*\n{'─'*32}\n\n"

    if rows:
        for date, km, cost in rows:
            text += f"📅 {date}  —  {fcost(cost)}\n"
        total, count = get_totals(car_id)
        text += f"\n{'─'*32}\n"
        text += f"Итого за {count} замен: *{fcost(total)}*"
    else:
        text += "Замен ещё не записано."

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'car_{car_id}')]])
    await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')


# ─── Расходы по всему гаражу ────────────────────────────────

async def show_expenses_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    text = f"💰 *Расходы по всему гаражу*\n{'─'*32}\n\n"
    grand_total = 0
    grand_count = 0

    for car_id, car_name in CARS.items():
        total, count = get_totals(car_id)
        grand_total += total
        grand_count += count
        text += f"{car_name}\n"
        if count:
            text += f"   {count} замен  →  *{fcost(total)}*\n\n"
        else:
            text += f"   нет данных\n\n"

    text += f"{'─'*32}\n"
    text += f"🏦 *Итого: {fcost(grand_total)}*\n"
    text += f"_({grand_count} замен по всем машинам)_"

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='back')]])
    await q.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')


# ─── Запись замены ───────────────────────────────────────────

async def start_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id = q.data.replace('record_', '')
    context.user_data['car_id'] = car_id

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f'car_{car_id}')]])
    await q.edit_message_text(
        f"*{CARS[car_id]}*\n\n"
        f"📝 *Запись замены масла*\n{'─'*32}\n\n"
        f"*Шаг 1 из 2* — Пробег\n\n"
        f"📍 Сколько км сейчас на спидометре?\n\n"
        f"_Введи цифрами, например:_ `87450`",
        reply_markup=markup, parse_mode='Markdown'
    )
    return WAITING_KM

async def got_km(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(' ', '').replace(',', '').replace('.', '')
    if not raw.isdigit():
        await update.message.reply_text("❌ Введи только цифры, например: `87450`", parse_mode='Markdown')
        return WAITING_KM

    car_id = context.user_data['car_id']
    context.user_data['km'] = int(raw)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Пропустить", callback_data='skip_cost')],
        [InlineKeyboardButton("❌ Отмена",    callback_data=f'car_{car_id}')],
    ])
    await update.message.reply_text(
        f"*{CARS[car_id]}*\n\n"
        f"📝 *Запись замены масла*\n{'─'*32}\n\n"
        f"*Шаг 2 из 2* — Стоимость\n\n"
        f"💰 Сколько потратили на замену (₽)?\n\n"
        f"_Введи цифрами, например:_ `2800`\n"
        f"_Или нажми_ *Пропустить*",
        reply_markup=markup, parse_mode='Markdown'
    )
    return WAITING_COST

async def got_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(' ', '').replace(',', '').replace('₽', '')
    if not raw.isdigit():
        await update.message.reply_text("❌ Введи только цифры, например: `2800`", parse_mode='Markdown')
        return WAITING_COST
    context.user_data['cost'] = int(raw)
    await show_confirm(update.message, context)
    return ConversationHandler.END

async def skip_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['cost'] = None
    await show_confirm(update.callback_query, context)
    return ConversationHandler.END

async def show_confirm(src, context):
    car_id   = context.user_data['car_id']
    km       = context.user_data['km']
    cost     = context.user_data.get('cost')
    car_name = CARS[car_id]
    date     = datetime.now().strftime('%d.%m.%Y')

    text = (
        f"*{car_name}*\n\n"
        f"📝 *Проверь данные:*\n{'─'*32}\n\n"
        f"   📅 Дата:       {date}\n"
        f"   📍 Пробег:     {fkm(km)} км\n"
        f"   💰 Стоимость:  {fcost(cost)}\n\n"
        f"{'─'*32}\nВсё верно?"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Сохранить",  callback_data='confirm_save'),
         InlineKeyboardButton("✏️ Заново",    callback_data=f'record_{car_id}')],
        [InlineKeyboardButton("❌ Отмена",    callback_data=f'car_{car_id}')],
    ])
    if hasattr(src, 'edit_message_text'):
        await src.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await src.reply_text(text, reply_markup=markup, parse_mode='Markdown')

async def do_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id   = context.user_data['car_id']
    km       = context.user_data['km']
    cost     = context.user_data.get('cost')
    interval = get_interval(car_id)
    save_change(car_id, km, cost)

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 К машине",     callback_data=f'car_{car_id}')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back')],
    ])
    await q.edit_message_text(
        f"✅ *Записано!*\n\n"
        f"{CARS[car_id]}\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y')}\n"
        f"📍 {fkm(km)} км\n"
        f"💰 {fcost(cost)}\n\n"
        f"📌 Следующая замена при *{fkm(km + interval)} км*",
        reply_markup=markup, parse_mode='Markdown'
    )


# ─── Изменить интервал ───────────────────────────────────────

async def ask_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    car_id  = q.data.replace('interval_', '')
    current = get_interval(car_id)
    context.user_data['interval_car'] = car_id

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data=f'car_{car_id}')]])
    await q.edit_message_text(
        f"*{CARS[car_id]}*\n\n"
        f"⚙️ *Интервал замены масла*\n\n"
        f"Сейчас: *{fkm(current)} км*\n\n"
        f"Введи новый интервал в км:\n"
        f"_Например:_ `7500` _или_ `10000`",
        reply_markup=markup, parse_mode='Markdown'
    )
    return WAITING_INTERVAL

async def save_interval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip().replace(' ', '')
    if not raw.isdigit():
        await update.message.reply_text("❌ Только цифры, например: `10000`", parse_mode='Markdown')
        return WAITING_INTERVAL

    car_id = context.user_data['interval_car']
    set_interval(car_id, int(raw))

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 К машине", callback_data=f'car_{car_id}')]])
    await update.message.reply_text(
        f"✅ *Готово!*\n\n{CARS[car_id]}\n"
        f"Интервал замены: *{fkm(int(raw))} км*",
        reply_markup=markup, parse_mode='Markdown'
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await start(update, context)
    return ConversationHandler.END


# ─── Запуск ─────────────────────────────────────────────────

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(start_record, pattern='^record_')],
        states={
            WAITING_KM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_km)],
            WAITING_COST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_cost),
                CallbackQueryHandler(skip_cost, pattern='^skip_cost$'),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', cancel)],
    ))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_interval, pattern='^interval_')],
        states={
            WAITING_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_interval_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel), CommandHandler('start', cancel)],
    ))

    app.add_handler(CallbackQueryHandler(do_save,           pattern='^confirm_save$'))
    app.add_handler(CallbackQueryHandler(show_car,          pattern='^car_'))
    app.add_handler(CallbackQueryHandler(show_history,      pattern='^history_'))
    app.add_handler(CallbackQueryHandler(show_expenses_car, pattern='^expenses_(?!all)'))
    app.add_handler(CallbackQueryHandler(show_expenses_all, pattern='^expenses_all$'))
    app.add_handler(CallbackQueryHandler(start,             pattern='^back$'))

    print("✅ Бот запущен!")
    app.run_polling()


if __name__ == '__main__':
    main()
