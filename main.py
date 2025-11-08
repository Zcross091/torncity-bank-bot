import os
import json
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from aiohttp import web # New: Import web for the server

# === CONFIG & SETUP ===
TOKEN = os.getenv("DISCORD_TOKEN")
# Render provides the PORT variable. We default to 9080 if it's not set.
# Ensure you set the PORT environment variable to 9080 in Render settings if you want to use it.
PORT = int(os.environ.get("PORT", 9080))
DATA_FILE = "data.json"

# === INTENTS (FIX) ===
# Explicitly enable the privileged Message Content Intent for bot commands/listeners
intents = discord.Intents.default()
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# === STORAGE (CAUTION: NON-PERSISTENT) ===
# WARNING: This file storage is NOT persistent on Render Web Services and will reset 
# on every deploy. Consider switching to a database (like Render's PostgreSQL or Redis) 
# for production use.
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    """Loads user data from the local JSON file."""
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_data(data):
    """Saves user data to the local JSON file."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === UTILS (IMPROVED) ===
async def fetch_torn_data(selections: str, key: str):
    """
    Fetches Torn API data for the 'user' endpoint with combined selections.
    
    Args:
        selections: A comma-separated string of API selections (e.g., "log,networth").
        key: The user's Torn API key.
    
    Returns:
        The JSON response data or None on network/API failure.
    """
    url = f"https://api.torn.com/user?selections={selections}&key={key}&comment=bankbot"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                print(f"Torn API Request Failed: Status {resp.status} for URL: {url}")
                # You could also log the response text here for more details
                return None

# === COMMANDS (MINOR UPDATES) ===
@tree.command(name="key", description="Register your limited access Torn API key")
async def key_command(interaction: discord.Interaction, api_key: str):
    data = load_data()
    user_id = str(interaction.user.id)

    # Verify key using the basic 'basic' selection
    torn_data = await fetch_torn_data("basic", api_key) 
    
    if not torn_data or "error" in torn_data:
        # Better error handling for the API response
        error_msg = torn_data.get("error", {}).get("error", "Invalid or restricted API key.") if torn_data else "Failed to connect to Torn API."
        await interaction.response.send_message(f"❌ API Key Error: {error_msg}", ephemeral=True)
        return

    player_name = torn_data.get("name", "Unknown")
    data[user_id] = {"key": api_key, "player": player_name}
    save_data(data)

    await interaction.response.send_message(f"✅ Your API key has been saved, **{player_name}**!", ephemeral=True)

# ... (deletekey command is unchanged)

@tree.command(name="bank", description="View your last 2 months of Torn money transactions and networth")
async def bank(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("⚠️ You must register first using `/key <your_torn_api_key>`", ephemeral=True)
        return

    api_key = data[user_id]["key"]
    player = data[user_id]["player"]

    # Fetch logs AND networth in ONE efficient API call
    all_data = await fetch_torn_data("log,networth", api_key) 

    if not all_data or "error" in all_data:
        error_msg = all_data.get("error", {}).get("error", "Failed to fetch Torn data.") if all_data else "Failed to connect to Torn API."
        await interaction.followup.send(f"❌ Torn API Error: {error_msg}", ephemeral=True)
        return

    logs = all_data.get("log", {})
    networth_data = all_data.get("networth", {})

    message_lines = [f"💳 **{player}'s Bank Report (Last 2 Months)**", ""]

    cutoff = datetime.utcnow() - timedelta(days=60)
    
    filtered = []
    # Filter logs based on date and keywords
    for log_entry in logs.values():
        timestamp = datetime.utcfromtimestamp(log_entry["timestamp"])
        if timestamp >= cutoff:
            if any(word in log_entry["title"].lower() for word in [
                "paid", "deposit", "withdraw", "sold", "received", "sent"
            ]):
                filtered.append(log_entry)

    if not filtered:
        message_lines.append("No relevant money transactions found in the past 2 months.")
    else:
        # Show top 25 newest entries
        for entry in sorted(filtered, key=lambda x: x["timestamp"], reverse=True)[:25]:
            t = datetime.utcfromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M")
            message_lines.append(f"• **{t}** — {entry['title']}")

    # Networth
    if networth_data:
        net = networth_data.get("total", 0)
        message_lines.append(f"\n💰 **Networth:** ${net:,.0f}")

    await interaction.followup.send("\n".join(message_lines), ephemeral=True)

# === BOT EVENTS & RENDER SERVER (CRITICAL FIX) ===

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} | Commands synced.")

# Optional prefix command fallback
@bot.command()
async def bank(ctx):
    # This command now requires 'intents.message_content = True' to work
    await ctx.send("⚠️ Please use the slash command `/bank` instead.", delete_after=10)

# --- RENDER WEB SERVER IMPLEMENTATION (The deployment fix) ---
async def health_check(request):
    """Minimal endpoint for Render's health check."""
    return web.Response(text="Bot is running!")

async def start_server():
    """Sets up and runs the aiohttp web server."""
    app = web.Application()
    app.add_routes([web.get('/', health_check)])
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=PORT) 
    await site.start()
    print(f"Web server started on port {PORT}")

async def main():
    """Runs both the web server and the Discord bot concurrently."""
    await start_server() 
    await bot.start(TOKEN)

# --- EXECUTION BLOCK ---
if __name__ == '__main__':
    import asyncio
    
    if not TOKEN:
        print("FATAL: DISCORD_TOKEN environment variable not set.")
    else:
        try:
            # Run the combined asynchronous tasks
            asyncio.run(main())
        except KeyboardInterrupt:
            print("Bot and server shut down gracefully.")
        except discord.LoginFailure:
            print("Bot failed to log in. Check your DISCORD_TOKEN.")
