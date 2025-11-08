import os
import json
import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta

# === CONFIG ===
TOKEN = os.getenv("DISCORD_TOKEN")  # from Render env
OWNER_ID = int(os.getenv("BOT_OWNER_ID", 0))  # optional owner id
DATA_FILE = "data.json"

# === SETUP ===
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # For slash commands

# === STORAGE ===
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# === UTILS ===
async def fetch_torn_data(endpoint, key):
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://api.torn.com/{endpoint}?key={key}&comment=bankbot") as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                return None

# === COMMANDS ===
@tree.command(name="key", description="Register your limited access Torn API key")
async def key_command(interaction: discord.Interaction, api_key: str):
    data = load_data()
    user_id = str(interaction.user.id)

    # Verify key
    torn_data = await fetch_torn_data("user", api_key)
    if not torn_data or "error" in torn_data:
        await interaction.response.send_message("❌ Invalid Torn API key. Please check and try again.", ephemeral=True)
        return

    player_name = torn_data.get("name", "Unknown")
    data[user_id] = {"key": api_key, "player": player_name}
    save_data(data)

    await interaction.response.send_message(f"✅ Your API key has been saved, **{player_name}**!", ephemeral=True)

@tree.command(name="deletekey", description="Remove your saved Torn API key")
async def deletekey(interaction: discord.Interaction):
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id in data:
        del data[user_id]
        save_data(data)
        await interaction.response.send_message("🗑️ Your Torn API key has been removed.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ You don't have an API key saved.", ephemeral=True)

@tree.command(name="bank", description="View your last 2 months of Torn money transactions")
async def bank(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    data = load_data()
    user_id = str(interaction.user.id)

    if user_id not in data:
        await interaction.followup.send("⚠️ You must register first using `/key <your_torn_api_key>`", ephemeral=True)
        return

    api_key = data[user_id]["key"]
    player = data[user_id]["player"]

    # Fetch logs
    logs = await fetch_torn_data("user?selections=log", api_key)
    networth_data = await fetch_torn_data("user?selections=networth", api_key)

    if not logs or "error" in logs:
        await interaction.followup.send("❌ Failed to fetch Torn logs. Try again later.", ephemeral=True)
        return

    message_lines = [f"💳 **{player}'s Bank Report (Last 2 Months)**", ""]

    cutoff = datetime.utcnow() - timedelta(days=60)
    entries = logs.get("log", {})

    filtered = []
    for log_id, log_entry in entries.items():
        timestamp = datetime.utcfromtimestamp(log_entry["timestamp"])
        if timestamp >= cutoff:
            if any(word in log_entry["title"].lower() for word in [
                "paid", "deposit", "withdraw", "sold", "received", "sent"
            ]):
                filtered.append(log_entry)

    if not filtered:
        message_lines.append("No relevant money transactions found in the past 2 months.")
    else:
        for entry in sorted(filtered, key=lambda x: x["timestamp"], reverse=True)[:25]:
            t = datetime.utcfromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M")
            message_lines.append(f"• **{t}** — {entry['title']} ({entry['category']})")

    # Networth
    if networth_data and "networth" in networth_data:
        net = networth_data["networth"].get("total", 0)
        message_lines.append(f"\n💰 **Networth:** ${net:,.0f}")

    await interaction.followup.send("\n".join(message_lines), ephemeral=True)

# === OTHER ===
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user} | Commands synced.")

# Optional prefix command fallback
@bot.command()
async def bank(ctx):
    await ctx.send("⚠️ Please use the slash command `/bank` instead.", delete_after=10)

bot.run(TOKEN)