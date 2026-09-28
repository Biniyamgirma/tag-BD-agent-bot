import os
import re
import asyncio
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()


ADMIN_USERNAMES = {
    4: "Temesgen",
        11: "Bereket",
        29: "Elham",
        49: "Mentesnot",
        115: "Kalewengel",
        117: "@Joasap",
        121: "Ermias",
        198: "@Himeba1",
        201: "@Biniyam_girma_1",
        222: "@Belopiia",
        225: "@chere_7",
        227: "Meseret",
        228: "@GkGGKKGG",
        229: "@Mudu13",
        240: "Bereket",
        243: "Kalewengel",
        258: "Mubarek",
        261: "@Biniyam_girma_1",
        279: "Bereket",
        299: "Mubarak",
        323: "@sileshiab",
        365: "@yeab81"
}

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
SQL_DATABASE_URL = os.environ.get("SQL_DATABASE_URL")
if not BOT_TOKEN or not SQL_DATABASE_URL:
    raise RuntimeError("Set the TELEGRAM_BOT_TOKEN and DATABASE_URL environment variables.")

sql_engine = create_async_engine(SQL_DATABASE_URL, pool_pre_ping=True)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
# --- DATABASE SETUP ---
async def init_db():
    """Creates the user_info table if it doesn't exist."""
    create_table_query = text("""
        CREATE TABLE IF NOT EXISTS user_info (
            chat_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            admin_id INT
        )
    """)
    try:
        async with sql_engine.begin() as conn:
            await conn.execute(create_table_query)
        print("Database 'user_info' table is ready.")
    except Exception as e:
        print(f"Failed to create table: {e}")

# --- START COMMAND HANDLER ---
def get_admin_id_by_username(username: str):
    """Matches a Telegram username to an Admin ID from our dictionary."""
    if not username:
        return None
    search_uname = username.lower().replace("@", "")
    for aid, uname in ADMIN_USERNAMES.items():
        if uname.lower().replace("@", "") == search_uname:
            return aid
    return None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the user's Chat ID when they start the bot."""
    user = update.effective_user
    chat_id = user.id
    username = user.username
    
    # 1. Check if they provided an admin ID (e.g., /start 4)
    admin_id = None
    if context.args and context.args[0].isdigit():
        admin_id = int(context.args[0])
    else:
        # 2. Try to auto-detect their admin ID using their Telegram username
        admin_id = get_admin_id_by_username(username)
        
    # Upsert Query: Insert new user or update existing user
    # Upsert Query: Insert new user or update existing user (MySQL Syntax)
    upsert_query = text("""
        INSERT INTO user_info (chat_id, username, admin_id) 
        VALUES (:chat_id, :username, :admin_id)
        ON DUPLICATE KEY UPDATE 
        username = :username, admin_id = :admin_id
    """)
    
    try:
        async with sql_engine.begin() as conn:
            await conn.execute(upsert_query, {
                "chat_id": chat_id,
                "username": username,
                "admin_id": admin_id
            })
        if admin_id:
            await update.message.reply_text(
                f"✅ Success! Your account is registered.\n\n"
                f"Your Chat ID: {chat_id}\n"
                f"You will now receive direct notifications from the group!"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Your Chat ID ({chat_id}) is saved, but I couldn't find your Admin ID.\n\n"
                f"If you are a Business Developer, please link your ID by typing:\n"
                f"`/start <Your_Admin_ID>` (For example: `/start 4`)",
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        print(f"DB Error on /start: {e}")
        await update.message.reply_text("An error occurred while saving your information.")

# --- DATABASE FETCH FUNCTIONS ---
async def get_restaurant_info(restaurant_name: str):
    """Fetches BD ID and Phone for a restaurant."""
    query = text("SELECT business_developer_id, phone FROM restaurants WHERE name = :restaurant_name")
    try:
        async with engine.connect() as connection:
            result = await connection.execute(query, {"restaurant_name": restaurant_name})
            row = result.fetchone()
            if row:
                return row[0], row[1]
    except SQLAlchemyError as e:
        print(f"Database error occurred: {e}")
    return None, None

async def get_saved_chat_id(admin_id: int):
    """Checks the PostgreSQL database for the BD's saved Chat ID."""
    query = text("SELECT chat_id FROM user_info WHERE admin_id = :admin_id")
    try:
        async with sql_engine.connect() as connection:
            result = await connection.execute(query, {"admin_id": admin_id})
            row = result.fetchone()
            if row:
                return row[0]
    except SQLAlchemyError as e:
        print(f"Error fetching chat_id: {e}")
    return None

# --- MESSAGE HANDLER ---
async def process_number_and_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        message_text = message.text
        
        if not message_text:
            return

        match = re.search(r'\(([^)]+)\)', message_text)
        
        if match:
            restaurant_name = match.group(1).strip()
            if not restaurant_name:
                return
                
            print(f"Extracted restaurant: {restaurant_name}") 
            
            admin_id, phone = await get_restaurant_info(restaurant_name)
            
            if admin_id:
                # 1. Get username for the group tag (fallback to 'Admin' if not in dictionary)
                tg_username = ADMIN_USERNAMES.get(admin_id, f"Admin {admin_id}")
                
                # 2. Check the database to see if they've started the bot
                saved_chat_id = await get_saved_chat_id(admin_id)
                
                # Group Message Configuration
                group_reply_text = f"{tg_username}, please review the above text for {restaurant_name}."
                if not saved_chat_id:
                    # Append a warning if they haven't started the bot yet
                    group_reply_text += "\n\n⚠️ Note to BD: Please send me a private message with `/start` so I can DM you!"
                
                await message.reply_text(group_reply_text, reply_to_message_id=message.message_id)
                
                # 3. If they have a saved Chat ID, send the DM
                if saved_chat_id:
                    chat_title = message.chat.title if message.chat.title else "Private Chat"
                    display_phone = phone if phone else "Not available"
                    message_link = message.link 
                    
                    inbox_text = (
                        f"🔔 <b>New Tag Alert!</b>\n\n"
                        f"<b>Group:</b> {html.escape(chat_title)}\n"
                        f"<b>Restaurant:</b> {html.escape(restaurant_name)}\n"
                        f"<b>Phone:</b> {html.escape(str(display_phone))}\n\n"
                        f"<b>Message:</b>\n<i>{html.escape(message_text)}</i>"
                    )
                    
                    reply_markup = None
                    if message_link:
                        keyboard = [[InlineKeyboardButton("Go to Group Message", url=message_link)]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    try:
                        await context.bot.send_message(
                            chat_id=saved_chat_id, 
                            text=inbox_text, 
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                        print(f"Successfully sent inbox message to Admin {admin_id}")
                    except (Forbidden, BadRequest) as e:
                        print(f"Failed to send DM to Admin {admin_id}. Error: {e}")

            else:
                error_text = f"Restaurant '{restaurant_name}' was not found in the database."
                await message.reply_text(error_text, reply_to_message_id=message.message_id)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

async def main():
    # Initialize the database table on startup
    # await init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add CommandHandler for /start
    application.add_handler(CommandHandler("start", start_command))
    
    # Add MessageHandler for normal text
    text_filter = filters.TEXT & ~filters.COMMAND
    application.add_handler(MessageHandler(text_filter, process_number_and_tag))
    
    print("Bot is running and routing orders...")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot safely shut down.")