"""
SynexProtectBot - Discord utility & moderation helper bot.

Requirements:
    pip install -U "discord.py>=2.6" python-dotenv deep-translator

Create a .env file next to this script:
    DISCORD_TOKEN=your_bot_token_here

Enable these in the Discord Developer Portal -> Bot:
    - SERVER MEMBERS INTENT
    - MESSAGE CONTENT INTENT  (required for prefix commands like !ping)
"""

import asyncio
import io
import json
import os
import platform
import random
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

BOT_NAME = "SynexProtectBot"
BOT_VERSION = "1.11.0"

# Palette: black / charcoal / slate / steel / silver
INK = 0x0B0C0E
CHARCOAL = 0x1A1C20
SLATE = 0x2A2E35
STEEL = 0x4A505A
SILVER = 0x9AA1AC
ERROR = 0x4B1D1D

START_TIME = datetime.now(timezone.utc)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None, case_insensitive=True)

giveaways: dict[int, dict] = {}

DATA_DIR = Path(os.getenv("DATA_DIR") or Path(__file__).parent)
DATA_DIR.mkdir(parents=True, exist_ok=True)
REACTION_ROLES_FILE = DATA_DIR / "reaction_roles.json"
reaction_roles: dict[str, list[dict]] = {}

EMOJI_MARKUP_RE = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")
EMOJI_NAME_RE = re.compile(r":?([A-Za-z0-9_]{2,32}):?")
DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
DURATION_TOKEN_RE = re.compile(r"(?:\d+[smhdw])+", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
LETTERS = ["🇦", "🇧", "🇨", "🇩", "🇪"]
GIFT_EMOJI = "<:gift:1567900881809186889>"

COLOR_NAMES = {
    "Black": 0x0B0C0E,
    "Charcoal": 0x1A1C20,
    "Gray": 0x4A505A,
    "Silver": 0x9AA1AC,
    "White": 0xF2F3F5,
    "Blue": 0x3B82F6,
    "Navy": 0x1E3A8A,
    "Sky": 0x38BDF8,
    "Teal": 0x14B8A6,
    "Green": 0x22C55E,
    "Yellow": 0xFACC15,
    "Orange": 0xF97316,
    "Red": 0xEF4444,
    "Crimson": 0x9F1239,
    "Pink": 0xEC4899,
    "Purple": 0xA855F7,
    "Violet": 0x7C3AED,
    "Brown": 0x78350F,
}


# ---------------------------------------------------------------- helpers

def base_embed(title: str | None = None, description: str | None = None, color: int = CHARCOAL) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    if bot.user:
        embed.set_author(name=BOT_NAME, icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=f"{BOT_NAME} · v{BOT_VERSION}")
    return embed


def notice(text: str, color: int = CHARCOAL) -> discord.Embed:
    return discord.Embed(description=text, color=color)


def E(names, fallback: str = "") -> str:
    """Return a server emoji by name (bot must be in the server that owns it), else fallback."""
    wanted = [names] if isinstance(names, str) else list(names)
    for name in wanted:
        for emoji in bot.emojis:
            if emoji.name.lower() == name.lower():
                return str(emoji)
    return fallback


def error_notice(text: str) -> discord.Embed:
    return discord.Embed(description=f"{E('Error', '⚠️')} {text}", color=ERROR)


def load_reaction_roles() -> None:
    global reaction_roles
    try:
        reaction_roles = json.loads(REACTION_ROLES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        reaction_roles = {}


def save_reaction_roles() -> None:
    REACTION_ROLES_FILE.write_text(json.dumps(reaction_roles, indent=2), encoding="utf-8")


def emoji_key_from_partial(emoji: discord.PartialEmoji) -> str:
    return f"c{emoji.id}" if emoji.id else str(emoji.name).replace("\ufe0f", "")


def emoji_key_from_input(text: str) -> str | None:
    text = text.strip()
    match = EMOJI_MARKUP_RE.fullmatch(text)
    if match:
        return f"c{match.group(3)}"
    if text and not (text.isascii() and text.isalnum()):
        return text.replace("\ufe0f", "")
    return None


def parse_color(value: str | None) -> int:
    if not value:
        return CHARCOAL
    value = value.strip()
    for name, code in COLOR_NAMES.items():
        if name.lower() == value.lower():
            return code
    value = value.lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return int(value, 16)
    raise ValueError("invalid color")


async def color_autocomplete(interaction: discord.Interaction, current: str):
    text = current.lower().strip()
    return [
        app_commands.Choice(name=f"{name}  ·  #{code:06X}", value=name)
        for name, code in COLOR_NAMES.items()
        if text in name.lower()
    ][:25]


def parse_duration(text: str) -> int | None:
    matches = DURATION_RE.findall(text or "")
    if not matches:
        return None
    return sum(int(amount) * UNIT_SECONDS[unit.lower()] for amount, unit in matches)


def fmt_seconds(seconds: int) -> str:
    days, seconds = divmod(int(seconds), 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = [f"{v}{u}" for v, u in ((days, "d"), (hours, "h"), (minutes, "m"), (seconds, "s")) if v]
    return " ".join(parts) or "0s"


def progress_bar(percent: float, size: int = 12) -> str:
    filled = round(percent / 100 * size)
    return "▰" * filled + "▱" * (size - filled)


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


# ---------------------------------------------------------------- shared builders

def build_ping_embed() -> discord.Embed:
    ms = round(bot.latency * 1000)
    status = "Excellent" if ms < 100 else "Good" if ms < 200 else "Degraded"
    embed = base_embed("⚡ Latency", color=SLATE)
    embed.add_field(name="Response time", value=f"`{ms} ms`", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    return embed


def build_serverinfo_embed(guild: discord.Guild) -> discord.Embed:
    roles = [r for r in guild.roles if not r.is_default()]
    humans = sum(1 for m in guild.members if not m.bot)
    bots = sum(1 for m in guild.members if m.bot)

    embed = base_embed(guild.name, guild.description or "Server overview", CHARCOAL)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="Boost", value=f"Level {guild.premium_tier} · {guild.premium_subscription_count} boosts", inline=True)
    embed.add_field(name="Verification", value=str(guild.verification_level).title(), inline=True)
    embed.add_field(name="Members", value=f"**{guild.member_count:,}** total\n{humans:,} humans · {bots:,} bots", inline=True)
    embed.add_field(name="Channels", value=f"{len(guild.text_channels)} text · {len(guild.voice_channels)} voice", inline=True)
    embed.add_field(name="Roles", value=str(len(roles)), inline=True)
    embed.add_field(
        name="Created",
        value=f"{discord.utils.format_dt(guild.created_at, 'D')} · {discord.utils.format_dt(guild.created_at, 'R')}",
        inline=False,
    )
    embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=False)
    return embed


def build_userinfo_embed(member: discord.Member) -> discord.Embed:
    roles = [r for r in reversed(member.roles) if not r.is_default()]
    role_text = " ".join(r.mention for r in roles[:15]) + (f" +{len(roles) - 15} more" if len(roles) > 15 else "")

    embed = base_embed(str(member), f"Profile of {member.mention}", STEEL)
    embed.set_thumbnail(url=member.display_avatar.replace(size=1024).url)
    embed.add_field(name="Display name", value=member.display_name, inline=True)
    embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="Account type", value="Bot" if member.bot else "Member", inline=True)
    embed.add_field(
        name="Joined server",
        value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown",
        inline=True,
    )
    embed.add_field(name="Account created", value=discord.utils.format_dt(member.created_at, "D"), inline=True)
    embed.add_field(name=f"Roles · {len(roles)}", value=role_text or "None", inline=False)
    return embed


def build_botinfo_embed() -> discord.Embed:
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    total_users = sum(g.member_count or 0 for g in bot.guilds)

    embed = base_embed(BOT_NAME, "Utility and protection for your community.", INK)
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="Uptime", value=fmt_seconds(uptime), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Servers", value=f"{len(bot.guilds):,}", inline=True)
    embed.add_field(name="Users reached", value=f"{total_users:,}", inline=True)
    embed.add_field(name="Commands", value=str(len(bot.tree.get_commands())), inline=True)
    embed.add_field(
        name="Runtime",
        value=f"discord.py `{discord.__version__}` · Python `{platform.python_version()}`",
        inline=False,
    )
    return embed


def build_avatar(user: discord.abc.User) -> tuple[discord.Embed, discord.ui.View]:
    url = user.display_avatar.with_size(4096).url
    embed = base_embed(f"{user.display_name}", f"Avatar of {user.mention}", STEEL)
    embed.set_image(url=url)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Download", url=url, style=discord.ButtonStyle.link, emoji="⬇️"))
    return embed, view


# ---------------------------------------------------------------- events

@bot.event
async def on_ready():
    load_reaction_roles()
    load_tickets()
    load_welcomes()
    load_autoroles()
    await _sync_tickets_from_discord()
    bot.add_view(build_panel_view())
    for ticket in ticket_data["open"].values():
        if ticket.get("message_id"):
            bot.add_view(ticket_layout(ticket), message_id=ticket["message_id"])
    if not getattr(bot, "_tickets_loop_started", False):
        bot._tickets_loop_started = True
        asyncio.create_task(_inactivity_loop())
    # Global commands can take up to an hour to show. Syncing per guild makes them appear now.
    for guild in bot.guilds:
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"[sync] {guild.name}: {len(synced)} commands")
    await bot.tree.sync()
    print(f"{BOT_NAME} online as {bot.user} ({len(bot.guilds)} servers)")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure, commands.NoPrivateMessage)):
        return
    print(f"[prefix error] {error}")


def _find_rule(guild_id: int, emoji: discord.PartialEmoji, message_id: int) -> dict | None:
    key = emoji_key_from_partial(emoji)
    rules = reaction_roles.get(str(guild_id), [])
    exact = [r for r in rules if r["emoji"] == key and r["message_id"] == message_id]
    if exact:
        return exact[0]
    return next((r for r in rules if r["emoji"] == key and r["message_id"] is None), None)


@bot.tree.command(name="removeemojirole", description="Remove a reaction role rule.")
@app_commands.describe(emoji="The emoji of the rule to remove", message_id="Optional: only the rule for this message")
@app_commands.default_permissions(manage_roles=True)
@app_commands.guild_only()
async def removeemojirole(interaction: discord.Interaction, emoji: str, message_id: str | None = None):
    key = emoji_key_from_input(emoji)
    if key is None:
        return await interaction.response.send_message(embed=error_notice("Invalid emoji."), ephemeral=True)
    msg_id = None
    if message_id:
        try:
            msg_id = int(message_id.strip())
        except ValueError:
            return await interaction.response.send_message(embed=error_notice("Invalid message ID."), ephemeral=True)
    rules = reaction_roles.get(str(interaction.guild_id), [])
    before = len(rules)
    rules[:] = [r for r in rules if not (r["emoji"] == key and (msg_id is None or r["message_id"] == msg_id))]
    save_reaction_roles()
    removed = before - len(rules)
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} Removed {removed} rule(s) for {emoji}." if removed
                     else f"No rule found for {emoji}."),
        ephemeral=True,
    )


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return
    rule = _find_rule(payload.guild_id, payload.emoji, payload.message_id)
    if rule is None:
        return
    guild = bot.get_guild(payload.guild_id)
    role = guild.get_role(rule["role_id"]) if guild else None
    if role is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return
    if member.bot or role not in member.roles:
        return
    try:
        await member.remove_roles(role, reason="Reaction role removed")
    except discord.HTTPException as exc:
        print(f"[reaction roles] could not remove role: {exc}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return

    rules = reaction_roles.get(str(payload.guild_id), [])
    key = emoji_key_from_partial(payload.emoji)
    rule = _find_rule(payload.guild_id, payload.emoji, payload.message_id)
    if rule is None:
        print(f"[reaction roles] no rule for {key} on message {payload.message_id}")
        return

    guild = bot.get_guild(payload.guild_id)
    role = guild.get_role(rule["role_id"]) if guild else None
    if role is None:
        return

    member = payload.member or guild.get_member(payload.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
            return
    if member.bot or role in member.roles:
        return

    try:
        await member.add_roles(role, reason="Reaction role")
    except discord.HTTPException as exc:
        print(f"[reaction roles] could not add role: {exc}")
        return

    text = f"{E('true', '✅')} Role **{role.name}** granted."
    try:
        await member.send(embed=notice(text))
    except discord.HTTPException:
        channel = bot.get_channel(payload.channel_id)
        if channel:
            try:
                await channel.send(f"{member.mention} {text}", delete_after=6)
            except discord.HTTPException:
                pass


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        text = "You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        text = "I'm missing the permissions needed to run this command."
    else:
        text = "An unexpected error occurred. Please try again."
        print(f"[error] {error}")

    embed = error_notice(text)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- /bot-say (admin)

@bot.tree.command(name="bot-say", description="Send a message through the bot without revealing who sent it.")
@app_commands.describe(message="The message to send", channel="Channel to send it in (default: this one)")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def bot_say(interaction: discord.Interaction, message: str, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    await target.send(message, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Message sent to {target.mention}."), ephemeral=True)


# ---------------------------------------------------------------- /embed (admin)

@bot.tree.command(name="embed", description="Send a custom embed. Every field is optional.")
@app_commands.describe(
    title="Embed title",
    description="Embed body text",
    color="Pick a color name (Blue, Red, Purple…) or type a hex code",
    footer="Small text at the bottom",
    image="Upload a picture to show inside the embed",
    image_url="Or paste a direct image link",
)
@app_commands.autocomplete(color=color_autocomplete)
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def embed_cmd(
    interaction: discord.Interaction,
    title: str | None = None,
    description: str | None = None,
    color: str | None = None,
    footer: str | None = None,
    image: discord.Attachment | None = None,
    image_url: str | None = None,
):
    try:
        embed_color = parse_color(color)
    except ValueError:
        return await interaction.response.send_message(
            embed=error_notice("Invalid color. Pick a color name or use a 6-digit hex value such as `2B2D31`."),
            ephemeral=True,
        )

    if image and not (image.content_type or "").startswith("image/"):
        return await interaction.response.send_message(
            embed=error_notice("The attached file must be an image."), ephemeral=True
        )

    embed = discord.Embed(title=title, description=description, color=embed_color)
    if footer:
        embed.set_footer(text=footer)
    if image:
        embed.set_image(url=image.url)
    elif image_url:
        embed.set_image(url=image_url)

    if not (title or description or image or image_url):
        embed.description = "​"

    await interaction.channel.send(embed=embed)
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Embed sent."), ephemeral=True)


# ---------------------------------------------------------------- /emojisteal (admin)

@bot.tree.command(name="emojisteal", description="Copy a custom emoji from another server into this one.")
@app_commands.describe(
    emoji="The custom emoji to copy (paste it or type its name)",
    name="Optional new name for the emoji",
)
@app_commands.default_permissions(manage_emojis_and_stickers=True)
@app_commands.guild_only()
async def emojisteal(interaction: discord.Interaction, emoji: str, name: str | None = None):
    await interaction.response.defer(ephemeral=True)

    partial = None
    match = EMOJI_MARKUP_RE.search(emoji)
    if match:
        partial = discord.PartialEmoji(animated=bool(match.group(1)), name=match.group(2), id=int(match.group(3)))
    else:
        name_match = EMOJI_NAME_RE.fullmatch(emoji.strip())
        if name_match:
            wanted = name_match.group(1).lower()
            found = next((e for e in bot.emojis if e.name.lower() == wanted), None)
            if found:
                partial = discord.PartialEmoji(animated=found.animated, name=found.name, id=found.id)

    if partial is None:
        return await interaction.followup.send(
            embed=error_notice("I couldn't find that emoji. Paste the emoji itself, or use a name from a server the bot is in."),
            ephemeral=True,
        )

    guild = interaction.guild
    base_name = (name or partial.name or "emoji").strip()[:32]
    if len(base_name) < 2:
        base_name = (base_name + "_emoji")[:32]

    existing = {e.name for e in guild.emojis}
    final_name, counter = base_name, 1
    while final_name in existing:
        suffix = f"_{counter}"
        final_name = f"{base_name[:32 - len(suffix)]}{suffix}"
        counter += 1

    try:
        image = await partial.read()
        created = await guild.create_custom_emoji(
            name=final_name,
            image=image,
            reason=f"Copied by {interaction.user} via /emojisteal",
        )
    except discord.HTTPException as exc:
        return await interaction.followup.send(
            embed=error_notice(f"Could not add the emoji: {exc.text or 'the server may be full.'}"),
            ephemeral=True,
        )

    embed = base_embed("😎 Emoji added", f"{created}  ·  `:{created.name}:`", CHARCOAL)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- /addemojirole (admin)

async def _find_message(guild: discord.Guild, message_id: int, prefer: discord.abc.Messageable | None):
    if prefer is not None:
        try:
            return await prefer.fetch_message(message_id)
        except discord.HTTPException:
            pass
    for channel in guild.text_channels:
        try:
            return await channel.fetch_message(message_id)
        except discord.HTTPException:
            continue
    return None


async def _apply_reaction_role(guild: discord.Guild, emoji_text: str, role: discord.Role,
                               message: discord.Message | None, msg_id: int | None,
                               prefer: discord.abc.Messageable | None = None) -> str | None:
    """Saves the rule and, when a message is given, the bot reacts with the emoji so members can click it."""
    me = guild.me
    if role.is_default() or role.managed or role >= me.top_role:
        return "I can't manage that role. Make sure it's below my highest role and isn't managed by an integration."
    key = emoji_key_from_input(emoji_text)
    if key is None:
        return "Invalid emoji. Paste the emoji itself."

    rules = reaction_roles.setdefault(str(guild.id), [])
    rules[:] = [r for r in rules if not (r["emoji"] == key and r["message_id"] == msg_id)]
    rules.append({"emoji": key, "role_id": role.id, "message_id": msg_id})
    save_reaction_roles()

    if msg_id and message is None:
        message = await _find_message(guild, msg_id, prefer)
        if message is None:
            return "Rule saved, but I couldn't find that message to react to it."
    if message is not None:
        try:
            await message.add_reaction(emoji_text)
        except discord.HTTPException as exc:
            return f"Rule saved, but I couldn't add the reaction: {exc.text or exc}. Make sure I'm in the server that owns that emoji."
    return None


@bot.tree.command(name="addemojirole", description="Give a role when members react with an emoji.")
@app_commands.describe(
    emoji="The emoji the bot will put on the message and members will click",
    role="The role to give",
    message_id="Message ID to put the emoji on (right-click the message > Copy ID)",
)
@app_commands.default_permissions(manage_roles=True)
@app_commands.guild_only()
async def addemojirole(
    interaction: discord.Interaction,
    emoji: str,
    role: discord.Role,
    message_id: str | None = None,
):
    msg_id = None
    if message_id:
        try:
            msg_id = int(message_id.strip())
        except ValueError:
            return await interaction.response.send_message(embed=error_notice("Invalid message ID."), ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    error = await _apply_reaction_role(interaction.guild, emoji, role, None, msg_id, prefer=interaction.channel)
    if error:
        return await interaction.followup.send(embed=error_notice(error), ephemeral=True)

    scope = f"message `{msg_id}`" if msg_id else "any message"
    embed = base_embed("🏷️ Reaction role saved", color=CHARCOAL)
    embed.add_field(name="Emoji", value=emoji, inline=True)
    embed.add_field(name="Role", value=role.mention, inline=True)
    embed.add_field(name="Works on", value=scope, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.command(name="addemojirole")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def addemojirole_prefix(ctx: commands.Context, emoji: str, role: discord.Role):
    """Reply to a message, then type: !addemojirole <emoji> @role"""
    ref = ctx.message.reference
    target = ref.resolved if ref and isinstance(ref.resolved, discord.Message) else None
    if target is None:
        return await ctx.send(embed=error_notice("Reply to the message you want, then type `!addemojirole <emoji> @role`."), delete_after=10)

    error = await _apply_reaction_role(ctx.guild, emoji, role, target, target.id)
    if error:
        return await ctx.send(embed=error_notice(error), delete_after=12)
    await ctx.send(embed=notice(f"{E('true', '✅')} {emoji} now gives {role.mention} on that message."), delete_after=8)


# ---------------------------------------------------------------- /ping

@bot.tree.command(name="ping", description="Show the bot's current latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_ping_embed())


@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    await ctx.send(embed=build_ping_embed())


# ---------------------------------------------------------------- /serverinfo (prefix: !server)

@bot.tree.command(name="serverinfo", description="Show statistics and information about this server.")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_serverinfo_embed(interaction.guild))


@bot.command(name="server")
@commands.guild_only()
async def server_prefix(ctx: commands.Context):
    await ctx.send(embed=build_serverinfo_embed(ctx.guild))


# ---------------------------------------------------------------- /userinfo (prefix: !user)

@bot.tree.command(name="userinfo", description="Show details about a user.")
@app_commands.describe(member="The user to inspect (default: you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    await interaction.response.send_message(embed=build_userinfo_embed(member or interaction.user))


@bot.command(name="user")
@commands.guild_only()
async def user_prefix(ctx: commands.Context, member: Optional[discord.Member] = None):
    await ctx.send(embed=build_userinfo_embed(member or ctx.author))


# ---------------------------------------------------------------- /botinfo (prefix: !botinfo)

@bot.tree.command(name="botinfo", description="Show statistics about the bot.")
async def botinfo(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_botinfo_embed())


@bot.command(name="botinfo")
async def botinfo_prefix(ctx: commands.Context):
    await ctx.send(embed=build_botinfo_embed())


# ---------------------------------------------------------------- /avatar (prefix: !avatar)

@bot.tree.command(name="avatar", description="Show a user's avatar in full size.")
@app_commands.describe(member="The user whose avatar to show (default: you)")
async def avatar(interaction: discord.Interaction, member: discord.User | None = None):
    embed, view = build_avatar(member or interaction.user)
    await interaction.response.send_message(embed=embed, view=view)


@bot.command(name="avatar")
async def avatar_prefix(ctx: commands.Context, member: Optional[discord.User] = None):
    embed, view = build_avatar(member or ctx.author)
    await ctx.send(embed=embed, view=view)


# ---------------------------------------------------------------- help

# (name, description, usage)
PUBLIC_COMMANDS = [
    ("ping", "Show the bot's current latency.", "/ping  ·  !ping"),
    ("serverinfo", "Statistics and information about this server.", "/serverinfo  ·  !server"),
    ("userinfo", "Details about a member, including roles.", "/userinfo [member]  ·  !user [member]"),
    ("botinfo", "Uptime, servers and runtime information.", "/botinfo  ·  !botinfo"),
    ("avatar", "Full-size avatar with a download link.", "/avatar [member]  ·  !avatar [member]"),
    ("help", "This command list.", "/help  ·  !help"),
    ("timer", "Get a private reminder by DM after a set time.", "/timer time reminder  ·  !timer time reminder"),
    ("translate", "Translate text into another language.", "/translate language text"),
]

# (name, description, usage, required permission)
ADMIN_COMMANDS = [
    ("poll", "Public poll with live vote counts and up to five options.", "/poll question option1 option2 [option3] [option4] [option5]", "Manage Messages"),
    ("tickets-setup", "Post the ticket panel in this channel.", "/tickets-setup", "Manage Server"),
    ("bot-say", "Send a message without revealing who sent it.", "/bot-say message [channel]", "Manage Messages"),
    ("embed", "Send a custom embed with color, footer and image.", "/embed [title] [description] [color] [footer] [image] [image_url]", "Manage Messages"),
    ("emojisteal", "Copy a custom emoji from another server into this one.", "/emojisteal emoji [name]", "Manage Expressions"),
    ("addemojirole", "Give a role when members react with an emoji.", "/addemojirole emoji role [message_id]", "Manage Roles"),
    ("giveaway create", "Start a giveaway. Winners who don't claim in time are rerolled automatically.", "/giveaway create prize duration [winners] [timereclaim]  ·  !giveway prize duration [winners] [timereclaim]", "Manage Server"),
    ("giveaway end", "End a giveaway early and pick the winner(s).", "/giveaway end message_id", "Manage Server"),
    ("giveaway reroll", "Reroll winners who have not claimed their prize.", "/giveaway reroll message_id  ·  !reroll (reply to the giveaway)", "Manage Server"),
]

PREFIX_MAP = {
    "ping": "ping",
    "serverinfo": "server",
    "userinfo": "user",
    "botinfo": "botinfo",
    "avatar": "avatar",
    "help": "help",
    "timer": "timer",
}


class CommandSelect(discord.ui.Select):
    def __init__(self, owner_id: int, entries: list[tuple], admin: bool):
        self.owner_id = owner_id
        self.entries = {e[0]: e for e in entries}
        self.admin = admin
        options = [discord.SelectOption(label=f"/{e[0]}", description=e[1][:100], value=e[0]) for e in entries]
        super().__init__(placeholder="Choose a command to view its details…", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("This menu belongs to someone else.", ephemeral=True)

        entry = self.entries[self.values[0]]
        embed = base_embed(f"/{entry[0]}", entry[1], INK if self.admin else SLATE)
        embed.add_field(name="Usage", value=f"`{entry[2]}`", inline=False)
        if self.admin:
            embed.add_field(name="Required permission", value=entry[3], inline=True)
        await interaction.response.edit_message(embed=embed, view=self.view)


class CommandView(discord.ui.View):
    def __init__(self, owner_id: int, entries: list[tuple], admin: bool = False):
        super().__init__(timeout=180)
        self.add_item(CommandSelect(owner_id, entries, admin))


def build_help_embed() -> discord.Embed:
    lines = []
    for name, desc, _ in PUBLIC_COMMANDS:
        prefix = f"  ·  `!{PREFIX_MAP[name]}`" if name in PREFIX_MAP else ""
        lines.append(f"**`/{name}`**{prefix}\n{desc}")

    embed = base_embed("Commands", "Browse commands with the menu below.\n​", SLATE)
    embed.add_field(name="Available to everyone", value="\n\n".join(lines), inline=False)
    embed.set_footer(text=f"{BOT_NAME} · Prefix: ! · v{BOT_VERSION}")
    return embed


def build_helpadmin_embed() -> discord.Embed:
    lines = [f"**`/{name}`**  ·  *{perm}*\n{desc}" for name, desc, _, perm in ADMIN_COMMANDS]
    embed = base_embed("Administrator commands", "Restricted to members with the listed permission.\n​", INK)
    embed.add_field(name="Moderation & tools", value="\n\n".join(lines), inline=False)
    embed.set_footer(text=f"{BOT_NAME} · Admin panel · v{BOT_VERSION}")
    return embed


@bot.tree.command(name="help", description="Show the list of available commands.")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=build_help_embed(), view=CommandView(interaction.user.id, PUBLIC_COMMANDS), ephemeral=True
    )


@bot.command(name="help")
async def help_prefix(ctx: commands.Context):
    await ctx.send(embed=build_help_embed(), view=CommandView(ctx.author.id, PUBLIC_COMMANDS))


@bot.tree.command(name="helpadmin", description="Show the administrator command panel.")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def helpadmin(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=build_helpadmin_embed(),
        view=CommandView(interaction.user.id, ADMIN_COMMANDS, admin=True),
        ephemeral=True,
    )


@bot.command(name="helpadmin")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def helpadmin_prefix(ctx: commands.Context):
    await ctx.send(embed=build_helpadmin_embed(), view=CommandView(ctx.author.id, ADMIN_COMMANDS, admin=True))


# ---------------------------------------------------------------- /poll (admin, public votes)

class PollView(discord.ui.View):
    """Public poll: buttons show live vote counts. Only admins can create polls."""

    def __init__(self, question: str, options: list[str]):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.user_choice: dict[int, int] = {}

        for index, label in enumerate(options):
            button = discord.ui.Button(
                label=self._button_label(index),
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll:{uuid.uuid4().hex}:{index}",
                emoji=LETTERS[index],
            )
            button.callback = self._make_vote_callback(index)
            self.add_item(button)

    def counts(self) -> list[int]:
        counts = [0] * len(self.options)
        for choice in self.user_choice.values():
            counts[choice] += 1
        return counts

    def _button_label(self, index: int) -> str:
        return f"{self.options[index][:50]} · {self.counts()[index]}"

    def _refresh_buttons(self) -> None:
        for index, item in enumerate(self.children):
            item.label = self._button_label(index)

    def _make_vote_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if self.user_choice.get(user_id) == index:
                del self.user_choice[user_id]
            else:
                self.user_choice[user_id] = index
            self._refresh_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def build_embed(self) -> discord.Embed:
        counts = self.counts()
        total = sum(counts)
        rows = []
        for i, option in enumerate(self.options):
            percent = (counts[i] / total * 100) if total else 0
            rows.append(f"{LETTERS[i]}  **{option}**\n{progress_bar(percent)}  `{percent:.0f}%`")

        embed = discord.Embed(description=f"### 📊 {self.question}\n\n" + "\n\n".join(rows), color=SLATE)
        votes = f"{total} vote{'s' if total != 1 else ''}"
        embed.set_footer(text=f"{votes} · Click an option to vote · Click it again to remove your vote")
        return embed


@bot.tree.command(name="poll", description="Create a public poll with live results. Admins only.")
@app_commands.describe(
    question="The poll question",
    option1="First option",
    option2="Second option",
    option3="Third option (optional)",
    option4="Fourth option (optional)",
    option5="Fifth option (optional)",
)
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def poll(
    interaction: discord.Interaction,
    question: str,
    option1: str,
    option2: str,
    option3: str | None = None,
    option4: str | None = None,
    option5: str | None = None,
):
    options = [o.strip() for o in (option1, option2, option3, option4, option5) if o and o.strip()]
    view = PollView(question, options)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


# ---------------------------------------------------------------- /timer (private DM reminder)

async def _finish_timer(channel: discord.abc.Messageable, user: discord.abc.User, text: str, delay: int) -> None:
    await asyncio.sleep(delay)
    done = base_embed("⏰ Timer finished", text, STEEL)
    done.add_field(name="Set by", value=user.mention, inline=True)
    try:
        await channel.send(content=user.mention, embed=done, allowed_mentions=discord.AllowedMentions(users=True))
    except discord.HTTPException as exc:
        print(f"[timer] could not post in channel: {exc}")
    try:
        await user.send(embed=done)
    except discord.HTTPException as exc:
        print(f"[timer] could not send DM: {exc}")


async def _start_timer(channel: discord.abc.Messageable, user: discord.abc.User, seconds: int, text: str) -> bool:
    """Posts a public timer in the channel (live countdown) and DMs the user when it ends."""
    ends = now_ts() + seconds
    embed = base_embed("⏰ Timer started", text, STEEL)
    embed.add_field(name="Set by", value=user.mention, inline=True)
    embed.add_field(name="Ends", value=f"<t:{ends}:R> · <t:{ends}:f>", inline=True)
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[timer] could not post timer: {exc}")
        return False
    asyncio.create_task(_finish_timer(channel, user, text, seconds))
    return True


def _parse_timer_time(time: str) -> int | None:
    seconds = parse_duration(time)
    if seconds is None or seconds < 5 or seconds > 30 * 86400:
        return None
    return seconds


@bot.tree.command(name="timer", description="Start a timer everyone can see; you also get a DM when it ends.")
@app_commands.describe(
    time="How long to wait, e.g. 10m, 2h, 1d or 1h30m",
    reminder="What to remind you about",
)
@app_commands.guild_only()
async def timer_cmd(interaction: discord.Interaction, time: str, reminder: str):
    seconds = _parse_timer_time(time)
    if seconds is None:
        return await interaction.response.send_message(
            embed=error_notice("Use a time between 5 seconds and 30 days, e.g. `10m`, `2h`, `1d`."), ephemeral=True
        )
    if not await _start_timer(interaction.channel, interaction.user, seconds, reminder):
        return await interaction.response.send_message(embed=error_notice("I couldn't post the timer here."), ephemeral=True)
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} Timer set for **{fmt_seconds(seconds)}**. Everyone can see it here."), ephemeral=True
    )


@bot.command(name="timer")
@commands.guild_only()
async def timer_prefix(ctx: commands.Context, *, args: str = ""):
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        return await ctx.send(embed=error_notice("Usage: `!timer <time> <reminder>`, e.g. `!timer 10m Check the oven`"))

    seconds = _parse_timer_time(parts[0])
    if seconds is None:
        return await ctx.send(embed=error_notice("Use a time between 5 seconds and 30 days, e.g. `10m`, `2h`, `1d`."))

    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass

    if not await _start_timer(ctx.channel, ctx.author, seconds, parts[1]):
        await ctx.send(embed=error_notice("I couldn't post the timer here."), delete_after=8)


# ---------------------------------------------------------------- /translate

@bot.tree.command(name="translate", description="Translate a text into another language.")
@app_commands.describe(language="Target language code, e.g. en, es, fr, ja, de", text="The text to translate")
async def translate(interaction: discord.Interaction, language: str, text: str):
    await interaction.response.defer(ephemeral=True)
    try:
        translated = await asyncio.to_thread(
            GoogleTranslator(source="auto", target=language.strip().lower()).translate, text
        )
    except Exception:
        return await interaction.followup.send(
            embed=error_notice("Could not translate. Check the language code (e.g. `en`, `es`)."), ephemeral=True
        )

    embed = base_embed("🌐 Translation", color=CHARCOAL)
    embed.add_field(name="Original", value=text[:1024], inline=False)
    embed.add_field(name=f"Translated · `{language.lower()}`", value=(translated or "—")[:1024], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- giveaways (admin)
# Built with Components V2 (discord.py 2.6+): one container with text, a divider and buttons.

GIVEAWAY_LOCK = asyncio.Lock()
JOIN_BUTTON_ID = "giveaway:join"
ENTRIES_BUTTON_ID = "giveaway:entries"
TADA_EMOJI = "<a:tada:1567977830346924092>"
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"
DEFAULT_RECLAIM = "1h"
LINK_EMOJI = "<:link:1567987020503195842>"
WON_EMOJI = "<a:emoji_25:1567977812617469990>"


def _is_duration(token: str) -> bool:
    return bool(DURATION_TOKEN_RE.fullmatch(token))


def _valid_seconds(text: str, low: int, high: int) -> int | None:
    seconds = parse_duration(text)
    if seconds is None or seconds < low or seconds > high:
        return None
    return seconds


def _giveaway_top_and_body(data: dict) -> tuple[str, str]:
    if data["ended"]:
        footer = f"-# Ended <t:{data['ends_at']}:R> • <t:{data['ends_at']}:f>"
        winners_value = " ".join(f"<@{w}>" for w in data["winners_list"]) or "No valid entries"
    else:
        footer = f"-# Ends <t:{data['ends_at']}:R> • <t:{data['ends_at']}:f>"
        winners_value = str(data["winners"])

    top = f"### {GIFT_EMOJI} `|` {data['prize']}\n{footer}"
    body = (
        f"Hosted by: <@{data['host_id']}>\n"
        f"Entries: {len(data['entries']):,}\n"
        f"Winners: {winners_value}"
    )
    return top, body


def build_giveaway_layout(data: dict) -> discord.ui.LayoutView:
    top, body = _giveaway_top_and_body(data)

    join = discord.ui.Button(
        label="Giveaway ended" if data["ended"] else "Enter Giveaway",
        emoji=None if data["ended"] else "<:gift:1568013015570321418>",
        style=discord.ButtonStyle.secondary if data["ended"] else discord.ButtonStyle.primary,
        custom_id=JOIN_BUTTON_ID,
        disabled=data["ended"],
    )
    join.callback = _join_callback

    entries = discord.ui.Button(
        label=f"Entries: {len(data['entries']):,}",
        style=discord.ButtonStyle.secondary,
        custom_id=ENTRIES_BUTTON_ID,
    )
    entries.callback = _entries_callback

    row = discord.ui.ActionRow()
    row.add_item(join)
    row.add_item(entries)

    container = discord.ui.Container(
        discord.ui.TextDisplay(top),
        discord.ui.Separator(visible=True),
        discord.ui.TextDisplay(body),
        row,
        accent_colour=INK,
    )
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    return layout


async def _join_callback(interaction: discord.Interaction):
    data = giveaways.get(interaction.message.id)
    if not data or data["ended"]:
        return await interaction.response.send_message(embed=notice("This giveaway has ended."), ephemeral=True)

    uid = interaction.user.id
    if uid in data["entries"]:
        data["entries"].discard(uid)
        msg = "You left the giveaway."
    else:
        data["entries"].add(uid)
        msg = f"{E('true', '✅')} You're entered! Press the button again to leave."

    await interaction.response.edit_message(view=build_giveaway_layout(data))
    await interaction.followup.send(embed=notice(msg), ephemeral=True)


async def _entries_callback(interaction: discord.Interaction):
    data = giveaways.get(interaction.message.id)
    if not data:
        return await interaction.response.send_message(embed=notice("This giveaway no longer exists."), ephemeral=True)

    entrants = list(data["entries"])
    count = len(entrants)
    shown = " ".join(f"<@{uid}>" for uid in entrants[:50])
    if count > 50:
        shown += f"\n… and {count - 50:,} more"
    body = shown if shown else "Nobody has entered yet."

    embed = discord.Embed(
        title="👥  Giveaway entries",
        description=f"**{count:,}** member{'s' if count != 1 else ''} entered **{data['prize']}**.\n\n{body}",
        color=SLATE,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


def _new_giveaway_data(host_id: int, channel_id: int, prize: str, seconds: int, winners: int, reclaim: int) -> dict:
    return {
        "prize": prize,
        "winners": winners,
        "entries": set(),
        "ended": False,
        "host_id": host_id,
        "channel_id": channel_id,
        "message_id": 0,
        "ends_at": now_ts() + seconds,
        "seconds": seconds,
        "reclaim_seconds": reclaim,
        "winners_list": [],     # current winners (after rerolls)
        "past_winners": set(),  # everyone ever picked, never picked again
        "claimed": set(),
        "announce": {},         # uid -> info about the winner announcement
    }


async def _refresh_giveaway_message(gid: int) -> None:
    data = giveaways.get(gid)
    if not data:
        return
    channel = bot.get_channel(data["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(data["message_id"])
        await message.edit(view=build_giveaway_layout(data))
    except discord.HTTPException:
        pass


async def _ticker(gid: int) -> None:
    """Refreshes the countdown every minute until the giveaway ends."""
    while True:
        data = giveaways.get(gid)
        if not data or data["ended"]:
            return
        remaining = data["ends_at"] - now_ts()
        if remaining <= 0:
            return
        await asyncio.sleep(min(60, remaining))
        await _refresh_giveaway_message(gid)


async def _auto_end(gid: int, delay: int):
    await asyncio.sleep(delay)
    await _finish_giveaway(gid)


def _register_giveaway(message: discord.Message, data: dict) -> None:
    data["message_id"] = message.id
    giveaways[message.id] = data
    asyncio.create_task(_auto_end(message.id, data["seconds"]))


async def _resolve_user(uid: int) -> discord.User | None:
    user = bot.get_user(uid)
    if user is None:
        try:
            user = await bot.fetch_user(uid)
        except discord.HTTPException:
            return None
    return user


def emoji_from_bot(name: str, fallback: str) -> str:
    """Discord only renders an emoji for the bot if the bot is in the server that owns it."""
    found = next((e for e in bot.emojis if e.name == name), None)
    return str(found) if found else fallback


def build_dm_layout(uid: int, info: dict, state: str) -> discord.ui.LayoutView:
    """Private DM to the winner. state: 'pending', 'claimed' or 'rerolled'."""
    if state == "claimed":
        footer = f"{E('true', '✅')} Prize claimed. Enjoy!"
    elif state == "rerolled":
        footer = "⏭️ Time ran out, so a new winner was picked."
    else:
        footer = (
            f"<@{uid}> You have until <t:{info['deadline']}:T> "
            f"(<t:{info['deadline']}:R>) before the reroll is done"
        )

    link = discord.ui.Button(
        label="Go to the giveaway",
        emoji=LINK_EMOJI,
        style=discord.ButtonStyle.link,
        url=info["jump_url"],
    )
    row = discord.ui.ActionRow()
    row.add_item(link)

    container = discord.ui.Container(
        discord.ui.TextDisplay("### 🎉 You won a Giveaway!"),
        discord.ui.Separator(visible=True),
        discord.ui.TextDisplay("Claim your reward by pressing the button below"),
        discord.ui.TextDisplay(footer),
        discord.ui.Separator(visible=True),
        row,
        accent_colour=STEEL,
    )
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    return layout


async def _edit_dm(uid: int, info: dict, state: str) -> None:
    dm_id = info.get("dm_id")
    if not dm_id:
        return
    user = await _resolve_user(uid)
    if user is None:
        return
    try:
        dm = await user.create_dm()
        await dm.get_partial_message(dm_id).edit(view=build_dm_layout(uid, info, state))
    except discord.HTTPException:
        pass


def build_winner_layout(gid: int, uid: int, info: dict, state: str) -> discord.ui.LayoutView:
    """state: 'pending' (claim button shown), 'claimed' or 'rerolled'."""
    data = giveaways.get(gid)
    prize = data["prize"] if data else "the prize"

    if state == "claimed":
        status = f"{E('true', '✅')} Prize claimed."
    elif state == "rerolled":
        status = "⏭️ Not claimed in time, so a new winner was picked."
    else:
        status = f"-# Claim before <t:{info['deadline']}:R> or the prize will be rerolled."

    section = discord.ui.Section(
        discord.ui.TextDisplay(
            f"**Mention:** <@{uid}>\n**Username:** {info['name']}\n**User ID:** `{uid}`"
        ),
        accessory=discord.ui.Thumbnail(media=info["avatar"]),
    )

    children: list = [
        discord.ui.TextDisplay(f"{TADA_EMOJI} Congratulations <@{uid}>! You won **{prize}**!"),
        discord.ui.Separator(visible=True),
        discord.ui.TextDisplay("### Winner"),
        section,
        discord.ui.Separator(visible=True),
        discord.ui.TextDisplay(status),
    ]

    if state == "pending":
        claim = discord.ui.Button(
            label="Claim prize",
            emoji="🎁",
            style=discord.ButtonStyle.secondary,
            custom_id=f"giveaway:claim:{gid}:{uid}",
        )
        claim.callback = _make_claim_callback(gid, uid)
        row = discord.ui.ActionRow()
        row.add_item(claim)
        children.append(row)

    container = discord.ui.Container(*children, accent_colour=SLATE)
    layout = discord.ui.LayoutView(timeout=None)
    layout.add_item(container)
    return layout


def _make_claim_callback(gid: int, uid: int):
    async def claim(interaction: discord.Interaction):
        if interaction.user.id != uid:
            return await interaction.response.send_message(
                embed=error_notice("Only the winner can claim this prize."), ephemeral=True
            )
        data = giveaways.get(gid)
        info = data["announce"].get(uid) if data else None
        if info is None or info["status"] != "pending" or uid not in data["winners_list"]:
            return await interaction.response.send_message(
                embed=error_notice("This prize can no longer be claimed."), ephemeral=True
            )
        if now_ts() > info["deadline"]:
            return await interaction.response.send_message(
                embed=error_notice("The claim time has expired."), ephemeral=True
            )

        data["claimed"].add(uid)
        info["status"] = "claimed"
        await interaction.response.edit_message(view=build_winner_layout(gid, uid, info, "claimed"))
        await _edit_dm(uid, info, "claimed")

    return claim


async def _edit_announce(gid: int, uid: int, state: str) -> None:
    data = giveaways.get(gid)
    info = data["announce"].get(uid) if data else None
    if not info:
        return
    channel = bot.get_channel(info["channel_id"])
    if channel is None:
        return
    try:
        message = await channel.fetch_message(info["message_id"])
        await message.edit(view=build_winner_layout(gid, uid, info, state))
    except discord.HTTPException:
        pass
    await _edit_dm(uid, info, state)


async def _announce_winner(gid: int, uid: int) -> None:
    data = giveaways[gid]
    channel = bot.get_channel(data["channel_id"])
    if channel is None:
        return

    user = await _resolve_user(uid)
    info = {
        "name": user.name if user else "unknown",
        "avatar": user.display_avatar.url if user else DEFAULT_AVATAR,
        "deadline": now_ts() + data["reclaim_seconds"],
        "channel_id": channel.id,
        "message_id": 0,
        "jump_url": "",
        "dm_id": None,
        "status": "pending",
    }
    data["announce"][uid] = info

    message = await channel.send(view=build_winner_layout(gid, uid, info, "pending"))
    info["message_id"] = message.id
    info["jump_url"] = message.jump_url

    if user is not None:
        try:
            dm = await user.send(view=build_dm_layout(uid, info, "pending"))
            info["dm_id"] = dm.id
        except discord.HTTPException:
            pass

    asyncio.create_task(_reclaim_watch(gid, uid, info["deadline"]))


def _select_winners(gid: int, count: int) -> list[int]:
    """Picks new winners from entries that were never picked before."""
    data = giveaways[gid]
    pool = [u for u in data["entries"] if u not in data["past_winners"]]
    chosen = random.sample(pool, min(count, len(pool))) if pool else []
    data["past_winners"].update(chosen)
    return chosen


async def _replace_winner(gid: int, old_uid: int) -> bool:
    """Caller must hold GIVEAWAY_LOCK."""
    data = giveaways[gid]
    data["winners_list"] = [w for w in data["winners_list"] if w != old_uid]
    if old_uid in data["announce"]:
        data["announce"][old_uid]["status"] = "rerolled"
    await _edit_announce(gid, old_uid, "rerolled")

    chosen = _select_winners(gid, 1)
    if chosen:
        data["winners_list"].extend(chosen)
        await _announce_winner(gid, chosen[0])
    await _refresh_giveaway_message(gid)
    return bool(chosen)


async def _reclaim_watch(gid: int, uid: int, deadline: int) -> None:
    """If the winner doesn't claim before the deadline, reroll automatically."""
    await asyncio.sleep(max(0, deadline - now_ts()))
    async with GIVEAWAY_LOCK:
        data = giveaways.get(gid)
        if not data or uid in data["claimed"] or uid not in data["winners_list"]:
            return
        await _replace_winner(gid, uid)


async def _finish_giveaway(gid: int, count: int | None = None) -> list[int]:
    async with GIVEAWAY_LOCK:
        data = giveaways.get(gid)
        if not data or data["ended"]:
            return []

        data["ended"] = True
        data["ends_at"] = min(data["ends_at"], now_ts())
        chosen = _select_winners(gid, count or data["winners"])
        data["winners_list"] = list(chosen)

        await _refresh_giveaway_message(gid)

        channel = bot.get_channel(data["channel_id"])
        if channel is None:
            return chosen
        if not chosen:
            await channel.send(embed=discord.Embed(
                title="🎉  Giveaway ended", description="No valid entries were found.", color=STEEL
            ))
            return chosen
        for uid in chosen:
            await _announce_winner(gid, uid)
        return chosen


async def _reroll(gid: int) -> str | None:
    """Rerolls every winner who has not claimed yet. Returns an error message, or None on success."""
    async with GIVEAWAY_LOCK:
        data = giveaways.get(gid)
        if not data:
            return "No giveaway found for that message."
        if not data["ended"]:
            return "This giveaway is still running. End it first with `/giveaway end`."

        unclaimed = [w for w in data["winners_list"] if w not in data["claimed"]]
        if data["winners_list"] and not unclaimed:
            return "Every winner has already claimed the prize."

        if not unclaimed:
            chosen = _select_winners(gid, 1)
            if not chosen:
                return "No eligible entries left to reroll."
            data["winners_list"].extend(chosen)
            await _announce_winner(gid, chosen[0])
            await _refresh_giveaway_message(gid)
            return None

        results = [await _replace_winner(gid, uid) for uid in unclaimed]
        if not any(results):
            return "No eligible entries left to reroll."
        return None


def _parse_message_id(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


giveaway_group = app_commands.Group(
    name="giveaway",
    description="Manage giveaways",
    guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True),
)
bot.tree.add_command(giveaway_group)


@giveaway_group.command(name="create", description="Create a giveaway.")
@app_commands.describe(
    prize="What the winner receives",
    duration="How long the giveaway runs, e.g. 30m, 2h, 10h or 1d",
    winners="Number of winners (1-20, default 1)",
    timereclaim="Time the winner has to claim, e.g. 30m, 1h, 1d (default 1h)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_create(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    winners: app_commands.Range[int, 1, 20] = 1,
    timereclaim: str = DEFAULT_RECLAIM,
):
    seconds = _valid_seconds(duration, 10, 30 * 86400)
    reclaim = _valid_seconds(timereclaim, 60, 7 * 86400)
    if seconds is None:
        return await interaction.response.send_message(
            embed=error_notice("Use a duration between 10 seconds and 30 days, e.g. `10h` or `1d`."), ephemeral=True
        )
    if reclaim is None:
        return await interaction.response.send_message(
            embed=error_notice("Use a claim time between 1 minute and 7 days, e.g. `30m` or `1h`."), ephemeral=True
        )

    data = _new_giveaway_data(interaction.user.id, interaction.channel_id, prize, seconds, winners, reclaim)
    await interaction.response.send_message(view=build_giveaway_layout(data))
    message = await interaction.original_response()
    _register_giveaway(message, data)


@giveaway_group.command(name="end", description="End a giveaway early and pick the winner(s).")
@app_commands.describe(message_id="ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    data = giveaways.get(gid) if gid else None
    if not data:
        return await interaction.response.send_message(embed=error_notice("No giveaway found with that ID."), ephemeral=True)
    if data["ended"]:
        return await interaction.response.send_message(
            embed=error_notice("This giveaway has already ended. Use `/giveaway reroll` instead."), ephemeral=True
        )

    await interaction.response.send_message(embed=notice("Ending giveaway…"), ephemeral=True)
    await _finish_giveaway(gid)


@giveaway_group.command(name="reroll", description="Reroll the winners who have not claimed their prize.")
@app_commands.describe(message_id="ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    if gid is None:
        return await interaction.response.send_message(embed=error_notice("Invalid message ID."), ephemeral=True)

    error = await _reroll(gid)
    if error:
        return await interaction.response.send_message(embed=error_notice(error), ephemeral=True)
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} New winner selected."), ephemeral=True)


def parse_giveaway_args(args: str) -> tuple[str, str, int, str] | None:
    """
    Parses '<prize> <duration> [winners] [timereclaim]' from the end of the text.
    Examples:  Nitro 10h 1 1h  ·  Nitro 10h 1  ·  Nitro 10h
    """
    t = args.split()
    winners, reclaim = 1, DEFAULT_RECLAIM
    if len(t) >= 4 and _is_duration(t[-1]) and t[-2].isdigit() and _is_duration(t[-3]):
        reclaim = t.pop()
        winners = int(t.pop())
        duration = t.pop()
    elif len(t) >= 3 and t[-1].isdigit() and _is_duration(t[-2]):
        winners = int(t.pop())
        duration = t.pop()
    elif len(t) >= 2 and _is_duration(t[-1]):
        duration = t.pop()
    else:
        return None

    prize = " ".join(t).strip()
    if not prize:
        return None
    return prize, duration, winners, reclaim


@bot.command(name="giveway", aliases=["giveaway"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def giveway_prefix(ctx: commands.Context, *, args: str = ""):
    usage = "Usage: `!giveway <prize> <duration> [winners] [timereclaim]`, e.g. `!giveway Nitro 10h 1 1h`"
    parsed = parse_giveaway_args(args)
    if parsed is None:
        return await ctx.send(embed=error_notice(usage))

    prize, duration, winners, reclaim_text = parsed
    seconds = _valid_seconds(duration, 10, 30 * 86400)
    reclaim = _valid_seconds(reclaim_text, 60, 7 * 86400)
    if seconds is None:
        return await ctx.send(embed=error_notice("Use a duration between 10 seconds and 30 days, e.g. `10h` or `1d`."))
    if reclaim is None:
        return await ctx.send(embed=error_notice("Use a claim time between 1 minute and 7 days, e.g. `30m` or `1h`."))
    if not 1 <= winners <= 20:
        return await ctx.send(embed=error_notice("Winners must be between 1 and 20."))

    data = _new_giveaway_data(ctx.author.id, ctx.channel.id, prize, seconds, winners, reclaim)
    message = await ctx.send(view=build_giveaway_layout(data))
    _register_giveaway(message, data)


@bot.command(name="reroll")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def reroll_prefix(ctx: commands.Context):
    ref = ctx.message.reference
    if ref is None or ref.message_id is None:
        return await ctx.send(embed=error_notice("Reply to a giveaway message with `!reroll`."))

    error = await _reroll(ref.message_id)
    if error:
        return await ctx.send(embed=error_notice(error))
    await ctx.send(embed=notice(f"{E('true', '✅')} New winner selected."))


# ---------------------------------------------------------------- tickets (preset)
# The ticket system is configured in this file. /tickets-setup posts the panel.

# ---- Fill these in with your server's IDs (Developer Mode on > right-click > Copy ID)
TICKET_CATEGORY_ID: int | None = None        # category where ticket channels are created
LOGS_CHANNEL_ID: int | None = None           # channel for opened / closed / claimed logs
TRANSCRIPT_CHANNEL_ID: int | None = None     # channel where transcripts are saved
SUPPORT_ROLE_IDS: list[int] = []             # staff roles that can see, claim and manage tickets
MAX_OPEN_PER_USER = 1
INACTIVITY_HOURS = 0                         # 0 = never auto-close idle tickets
SAVE_TRANSCRIPTS = True
DM_TRANSCRIPT_ON_CLOSE = True

# ---- Panel
PANEL_COLOR = STEEL
PANEL_TEXT = """# {member} Ticket Panel

Need help or experiencing an issue? Our support team is here to assist you.

Open a ticket by selecting the appropriate category and describing your situation in as much detail as possible. A staff member will review your request and assist you as soon as possible.

**Before opening a ticket:**
• Avoid opening multiple tickets for the same issue.
• Provide all necessary information.
• Treat our support team with respect.
• Do not abuse the ticket system.

Thank you for being part of our community! {star}"""

TICKET_TYPES = [
    {
        "key": "support",
        "label": "Support",
        "emoji": "<:GE_member:1567977768371888208>",
        "description": "Ticket support",
        "intro": "Tell us what's going on and what you've already tried, so we can help you faster.",
    },
    {
        "key": "buy",
        "label": "Buy",
        "emoji": "<:Money:1568023452542312528>",
        "description": "Ticket buy",
        "intro": "Let us know what you'd like to purchase and any questions you have before paying.",
    },
    {
        "key": "giveaways",
        "label": "Giveaways",
        "emoji": "<:gift:1568013015570321418>",
        "description": "Ticket giveaways",
        "intro": "Tell us which giveaway you're asking about and the details of your issue.",
    },
    {
        "key": "staff",
        "label": "Staff Apply",
        "emoji": "<:GE_Lock:1568022252220448789>",
        "description": "Tickets staff apply",
        "intro": "Please share your age, your experience, and why you want to join the staff team.",
    },
]

# ---- Welcome message posted inside each new ticket.
# Placeholders: {user} {username} {number} {option} {roles} {server} {intro} {opened}
WELCOME_COLOR = STEEL
WELCOME_TITLE = "{welcome} Welcome, {username}!"
WELCOME_BODY = (
    "Thanks for reaching out to **{server}**. A member of our team will be with you shortly.\n\n"
    "{intro}\n\n"
    "> **Category** · {option}\n"
    "> **Ticket** · #{number}\n"
    "> **Opened** · {opened}"
)
WELCOME_FOOTER = "Staff tools are above · Only staff can use them"
WELCOME_PING = "{user} {roles}"

TICKETS_FILE = DATA_DIR / "tickets_data.json"
ticket_data: dict = {"counter": 0, "open": {}, "panel": {"channel_id": None, "message_id": None}}
LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)


def load_tickets() -> None:
    global ticket_data
    try:
        loaded = json.loads(TICKETS_FILE.read_text(encoding="utf-8"))
        ticket_data = {**ticket_data, **loaded}
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def save_tickets() -> None:
    TICKETS_FILE.write_text(json.dumps(ticket_data, indent=2), encoding="utf-8")


def ticket_type(key: str) -> dict | None:
    return next((t for t in TICKET_TYPES if t["key"] == key), None)


def is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild:
        return True
    return any(role.id in SUPPORT_ROLE_IDS for role in member.roles)


def can_manage_ticket(member: discord.Member, ticket: dict) -> bool:
    return member.id == ticket["user_id"] or is_staff(member)


def fill(text: str, **values) -> str:
    out = text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-") or "ticket"


def panel_text() -> str:
    return fill(PANEL_TEXT, member=E("GE_member", "🎫"), star=E("Estrella", "⭐"))


async def _log(guild: discord.Guild, embed: discord.Embed) -> None:
    channel = guild.get_channel(LOGS_CHANNEL_ID) if LOGS_CHANNEL_ID else None
    if channel is not None:
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


# ---------------------------------------------------------------- panel

def build_panel_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Select(
        custom_id="tk:select",
        placeholder="Select a ticket category…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=t["label"], value=t["key"], description=t["description"], emoji=t["emoji"])
            for t in TICKET_TYPES
        ],
    ))
    return view


def build_panel_embed() -> discord.Embed:
    return discord.Embed(description=panel_text(), color=PANEL_COLOR)


async def post_panel(channel: discord.abc.Messageable, guild: discord.Guild) -> discord.Message:
    message = await channel.send(embed=build_panel_embed(), view=build_panel_view())

    old = ticket_data["panel"]
    if old["channel_id"] and old["message_id"]:
        old_channel = guild.get_channel(old["channel_id"])
        if old_channel is not None:
            try:
                await (await old_channel.fetch_message(old["message_id"])).delete()
            except discord.HTTPException:
                pass

    ticket_data["panel"] = {"channel_id": channel.id, "message_id": message.id}
    save_tickets()
    return message


# ---------------------------------------------------------------- ticket controls

TICKET_TOPIC_RE = re.compile(r"^ticket\|owner:(\d+)\|n:(\d+)\|type:(\S+)")


def build_ticket_controls(ticket: dict, head: str = "", body: str = "", avatar_url: str | None = None) -> discord.ui.LayoutView:
    """Ticket welcome card: header, divider, details, staff menu on top, then the buttons, all in one gray container."""
    links_on = ticket.get("links_allowed", True)
    head = head or f"### Ticket #{ticket['number']:04d}"
    body = body or f"Ticket **{ticket['type']}**"
    head_text = discord.ui.TextDisplay(head)
    head_block = (discord.ui.Section(head_text, accessory=discord.ui.Thumbnail(avatar_url))
                  if avatar_url else head_text)
    staff_menu = discord.ui.Select(
        custom_id="tk:staff",
        placeholder="Staff tools…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="Transfer to other staff", value="transfer",
                                 emoji=E("transfer", "🔁"), description="Hand this ticket to another staff member"),
            discord.SelectOption(label=f"Accept links: {'On' if links_on else 'Off'}", value="links",
                                 emoji=E(["link~2", "link_2", "link2", "link"], "🔗"),
                                 description="Turn link filtering on or off for this ticket"),
            discord.SelectOption(label="Rename channel", value="rename",
                                 emoji=E("support", "✏️"), description="Change the ticket channel name"),
            discord.SelectOption(label="Add user", value="adduser",
                                 emoji=E("true", "➕"), description="Give a member access to this ticket"),
            discord.SelectOption(label="Take out user", value="removeuser",
                                 emoji=E("false", "➖"), description="Remove a member from this ticket"),
        ],
    )
    row_buttons = discord.ui.ActionRow(
        discord.ui.Button(label="Close Ticket", emoji=E("Error", "🔒"),
                          style=discord.ButtonStyle.danger, custom_id="tk:close"),
        discord.ui.Button(label="Reclaim Ticket", emoji=E("community", "🙋"),
                          style=discord.ButtonStyle.primary, custom_id="tk:claim"),
    )
    container = discord.ui.Container(
        head_block,
        discord.ui.TextDisplay(body),
        discord.ui.TextDisplay("-# Staff tools are above · Only staff can use them"),
        discord.ui.Separator(),
        discord.ui.ActionRow(staff_menu),
        row_buttons,
        accent_colour=STEEL,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


def ticket_layout(ticket: dict) -> discord.ui.LayoutView:
    return build_ticket_controls(ticket, ticket.get("welcome_head", ""), ticket.get("welcome_body", ""), ticket.get("avatar"))


async def _sync_tickets_from_discord() -> None:
    """Rebuild open tickets from their channels, so limits and buttons survive redeploys."""
    found: set[str] = set()
    for guild in bot.guilds:
        for channel in guild.text_channels:
            m = TICKET_TOPIC_RE.match(channel.topic or "")
            if not m:
                continue
            owner, number, key = int(m[1]), int(m[2]), m[3]
            cid = str(channel.id)
            found.add(cid)
            prev = ticket_data["open"].get(cid, {})
            ttype = ticket_type(key)
            ticket = {
                "user_id": owner,
                "type": ttype["label"] if ttype else key,
                "type_key": key,
                "number": number,
                "claimed_by": prev.get("claimed_by"),
                "opened_at": prev.get("opened_at", now_ts()),
                "last_activity": prev.get("last_activity", now_ts()),
                "links_allowed": prev.get("links_allowed", True),
                "welcome_head": prev.get("welcome_head", ""),
                "welcome_body": prev.get("welcome_body", ""),
                "avatar": prev.get("avatar"),
                "message_id": prev.get("message_id"),
            }
            if not ticket["message_id"]:
                try:
                    async for msg in channel.history(limit=20, oldest_first=True):
                        if msg.author.id == bot.user.id:
                            ticket["message_id"] = msg.id
                            break
                except discord.HTTPException:
                    pass
            ticket_data["open"][cid] = ticket
            ticket_data["counter"] = max(ticket_data["counter"], number)
    for cid in list(ticket_data["open"]):
        if cid not in found:
            ticket_data["open"].pop(cid)
    save_tickets()


# ---------------------------------------------------------------- opening

async def _open_ticket(interaction: discord.Interaction, key: str) -> None:
    guild = interaction.guild
    ttype = ticket_type(key)
    if ttype is None:
        return await interaction.response.send_message(embed=error_notice("That ticket type no longer exists."), ephemeral=True)

    mine = [cid for cid, t in ticket_data["open"].items() if t["user_id"] == interaction.user.id]
    if len(mine) >= MAX_OPEN_PER_USER:
        links = " ".join(f"<#{cid}>" for cid in mine)
        return await interaction.response.send_message(
            embed=error_notice(f"You already have an open ticket: {links}"), ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    ticket_data["counter"] += 1
    number = ticket_data["counter"]
    name = f"{ttype['key']}-{number:04d}"[:100]

    category_id = ticket_data.get("category_id") or TICKET_CATEGORY_ID
    category = guild.get_channel(category_id) if category_id else None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True,
            manage_messages=True, read_message_history=True,
        ),
    }
    roles = [r for r in (guild.get_role(rid) for rid in SUPPORT_ROLE_IDS) if r is not None]
    for role in roles:
        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    try:
        channel = await guild.create_text_channel(
            name, category=category, overwrites=overwrites, topic=f"ticket|owner:{interaction.user.id}|n:{number}|type:{ttype['key']}", reason=f"Ticket opened by {interaction.user}"
        )
    except discord.HTTPException as exc:
        ticket_data["counter"] -= 1
        return await interaction.followup.send(
            embed=error_notice(f"I couldn't create the ticket: {exc.text or 'missing permissions.'}"), ephemeral=True
        )

    ticket = {
        "user_id": interaction.user.id,
        "type": ttype["label"],
        "type_key": ttype["key"],
        "number": number,
        "claimed_by": None,
        "opened_at": now_ts(),
        "last_activity": now_ts(),
        "links_allowed": True,
    }
    ticket_data["open"][str(channel.id)] = ticket
    save_tickets()

    values = dict(
        welcome=E("community", "👋"),
        username=interaction.user.display_name,
        user=interaction.user.mention,
        number=f"{number:04d}",
        option=ttype["label"],
        roles=" ".join(r.mention for r in roles),
        server=guild.name,
        intro=ttype["intro"],
        opened=discord.utils.format_dt(discord.utils.utcnow(), "f"),
    )
    ticket["welcome_head"] = f"{fill(WELCOME_PING, **values).strip()}\n### {fill(WELCOME_TITLE, **values)}"
    ticket["welcome_body"] = fill(WELCOME_BODY, **values)
    ticket["avatar"] = interaction.user.display_avatar.url
    layout = ticket_layout(ticket)
    msg = await channel.send(
        view=layout,
        allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
    )
    ticket["message_id"] = msg.id
    save_tickets()

    log = base_embed(f"{E('community', '🎫')} Ticket opened", color=STEEL)
    log.add_field(name="Channel", value=channel.mention, inline=True)
    log.add_field(name="Opened by", value=interaction.user.mention, inline=True)
    log.add_field(name="Type", value=ttype["label"], inline=True)
    await _log(guild, log)

    await interaction.followup.send(
        embed=notice(f"{E('true', '✅')} Your ticket is ready: {channel.mention}"), ephemeral=True
    )


# ---------------------------------------------------------------- closing

async def _transcript_bytes(channel: discord.TextChannel) -> bytes:
    lines = []
    async for m in channel.history(limit=None, oldest_first=True):
        text = m.content or ""
        if m.embeds:
            text += " [embed]"
        if m.attachments:
            text += " " + " ".join(a.url for a in m.attachments)
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M:%S} UTC] {m.author} ({m.author.id}): {text}")
    return ("\n".join(lines) or "(no messages)").encode("utf-8")


async def _close_ticket(guild: discord.Guild, channel: discord.TextChannel, closed_by: str) -> None:
    ticket = ticket_data["open"].pop(str(channel.id), None)
    if ticket is None:
        return
    save_tickets()

    data = await _transcript_bytes(channel) if SAVE_TRANSCRIPTS else None
    duration = fmt_seconds(now_ts() - ticket["opened_at"])
    owner_mention = f"<@{ticket['user_id']}>"

    def transcript_file():
        return discord.File(io.BytesIO(data), filename=f"{channel.name}.txt") if data is not None else None

    if data is not None and TRANSCRIPT_CHANNEL_ID:
        tchannel = guild.get_channel(TRANSCRIPT_CHANNEL_ID)
        if tchannel is not None:
            try:
                await tchannel.send(
                    embed=base_embed("📄 Transcript", f"{channel.name} · opened by {owner_mention}", STEEL),
                    file=transcript_file(),
                )
            except discord.HTTPException:
                pass

    log = base_embed(f"{E('Error', '🔒')} Ticket closed", color=STEEL)
    log.add_field(name="Channel", value=channel.name, inline=True)
    log.add_field(name="Opened by", value=owner_mention, inline=True)
    log.add_field(name="Type", value=ticket["type"], inline=True)
    log.add_field(name="Closed by", value=closed_by, inline=True)
    log.add_field(name="Duration", value=duration, inline=True)
    await _log(guild, log)

    if DM_TRANSCRIPT_ON_CLOSE:
        owner = await _resolve_user(ticket["user_id"])
        if owner is not None:
            dm_embed = base_embed(f"{E('warn3', '🔒')} Your ticket was closed", f"**{ticket['type']}** · open for {duration}", STEEL)
            try:
                kwargs = {"file": transcript_file()} if data is not None else {}
                await owner.send(embed=dm_embed, **kwargs)
            except discord.HTTPException:
                pass

    try:
        await channel.send(embed=notice("🔒 Closing this ticket in 5 seconds…"))
    except discord.HTTPException:
        pass
    await asyncio.sleep(5)
    try:
        await channel.delete(reason=f"Ticket closed by {closed_by}")
    except discord.HTTPException:
        pass


class ConfirmView(discord.ui.View):
    def __init__(self, on_confirm, label: str = "Confirm", style: discord.ButtonStyle = discord.ButtonStyle.danger):
        super().__init__(timeout=60)
        self.on_confirm = on_confirm
        button = discord.ui.Button(label=label, style=style, emoji="✅")
        button.callback = self._confirm
        self.add_item(button)

    async def _confirm(self, interaction: discord.Interaction):
        await self.on_confirm(interaction)


async def _confirm_close(interaction: discord.Interaction) -> None:
    await interaction.response.defer()
    await _close_ticket(interaction.guild, interaction.channel, interaction.user.mention)


async def _request_close(interaction: discord.Interaction) -> None:
    ticket = ticket_data["open"].get(str(interaction.channel_id))
    if ticket is None:
        return await interaction.response.send_message(embed=error_notice("This isn't a ticket channel."), ephemeral=True)
    if not can_manage_ticket(interaction.user, ticket):
        return await interaction.response.send_message(
            embed=error_notice("Only the ticket owner or staff can close this ticket."), ephemeral=True
        )
    await interaction.response.send_message(
        embed=notice("Are you sure you want to close this ticket?"),
        view=ConfirmView(_confirm_close, "Close ticket"),
        ephemeral=True,
    )


# ---------------------------------------------------------------- staff tools

def _staff_only(interaction: discord.Interaction):
    ticket = ticket_data["open"].get(str(interaction.channel_id))
    if ticket is None:
        return None, error_notice("This isn't a ticket channel.")
    if not is_staff(interaction.user):
        return None, error_notice("Only staff can use this.")
    return ticket, None


async def _claim(interaction: discord.Interaction) -> None:
    ticket, err = _staff_only(interaction)
    if err:
        return await interaction.response.send_message(embed=err, ephemeral=True)
    if ticket["claimed_by"] == interaction.user.id:
        return await interaction.response.send_message(embed=error_notice("You already claimed this ticket."), ephemeral=True)

    ticket["claimed_by"] = interaction.user.id
    ticket["last_activity"] = now_ts()
    save_tickets()
    await interaction.response.send_message(
        content=f"{E('community', '🙋')} <@{ticket['user_id']}> **Attend your ticket**, {interaction.user.mention}.",
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    log = base_embed(f"{E('community', '🙋')} Ticket claimed", color=STEEL)
    log.add_field(name="Channel", value=interaction.channel.mention, inline=True)
    log.add_field(name="Claimed by", value=interaction.user.mention, inline=True)
    await _log(interaction.guild, log)


class UserPickView(discord.ui.View):
    """Ephemeral picker: runs on_pick with the chosen member."""

    def __init__(self, placeholder: str, on_pick):
        super().__init__(timeout=120)
        select = discord.ui.UserSelect(placeholder=placeholder, min_values=1, max_values=1)

        async def chosen(interaction: discord.Interaction):
            member = interaction.guild.get_member(select.values[0].id)
            if member is None:
                return await interaction.response.send_message(embed=error_notice("That member isn't in this server."), ephemeral=True)
            await on_pick(interaction, member)

        select.callback = chosen
        self.add_item(select)


async def _transfer(interaction: discord.Interaction) -> None:
    ticket, err = _staff_only(interaction)
    if err:
        return await interaction.response.send_message(embed=err, ephemeral=True)

    async def on_pick(inter: discord.Interaction, member: discord.Member):
        if not is_staff(member):
            return await inter.response.send_message(embed=error_notice("You can only transfer to a staff member."), ephemeral=True)
        ticket["claimed_by"] = member.id
        save_tickets()
        await inter.response.send_message(embed=notice(f"{E('transfer', '🔁')} Ticket transferred to {member.mention}."), ephemeral=True)
        await interaction.channel.send(
            content=f"{E('transfer', '🔁')} Ticket transferred to {member.mention}.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    await interaction.response.send_message(
        embed=notice("Pick the staff member who will take over this ticket."),
        view=UserPickView("Pick a staff member…", on_pick),
        ephemeral=True,
    )


async def _toggle_links(interaction: discord.Interaction) -> None:
    ticket, err = _staff_only(interaction)
    if err:
        return await interaction.response.send_message(embed=err, ephemeral=True)
    ticket["links_allowed"] = not ticket.get("links_allowed", True)
    save_tickets()
    await interaction.response.edit_message(view=ticket_layout(ticket))


class RenameModal(discord.ui.Modal, title="Rename channel"):
    new_name = discord.ui.TextInput(label="New channel name", max_length=90, placeholder="billing-issue")

    async def on_submit(self, interaction: discord.Interaction):
        name = slugify(self.new_name.value)
        await interaction.channel.edit(name=name, reason=f"Renamed by {interaction.user}")
        await interaction.response.send_message(embed=notice(f"{E('support', '✏️')} Channel renamed to `{name}`."), ephemeral=True)


async def _rename(interaction: discord.Interaction) -> None:
    _, err = _staff_only(interaction)
    if err:
        return await interaction.response.send_message(embed=err, ephemeral=True)
    await interaction.response.send_modal(RenameModal())


async def _add_or_remove_user(interaction: discord.Interaction, add: bool) -> None:
    ticket, err = _staff_only(interaction)
    if err:
        return await interaction.response.send_message(embed=err, ephemeral=True)

    async def on_pick(inter: discord.Interaction, member: discord.Member):
        channel = inter.channel
        if add:
            await channel.set_permissions(
                member, view_channel=True, send_messages=True, read_message_history=True,
                attach_files=True, embed_links=True, reason=f"Added by {inter.user}",
            )
            text = f"{E('true', '✅')} {member.mention} was added to this ticket."
        else:
            if member.id == ticket["user_id"]:
                return await inter.response.send_message(embed=error_notice("You can't remove the ticket owner."), ephemeral=True)
            await channel.set_permissions(member, overwrite=None, reason=f"Removed by {inter.user}")
            text = f"{E('false', '❌')} {member.mention} was removed from this ticket."
        await inter.response.send_message(embed=notice(text), ephemeral=True)
        await channel.send(content=text, allowed_mentions=discord.AllowedMentions.none())

    placeholder = "Pick a member to add…" if add else "Pick a member to remove…"
    await interaction.response.send_message(view=UserPickView(placeholder, on_pick), ephemeral=True)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component or interaction.guild_id is None:
        return
    custom_id = (interaction.data or {}).get("custom_id", "")
    try:
        if custom_id == "tk:select":
            await _open_ticket(interaction, interaction.data["values"][0])
        elif custom_id == "tk:close":
            await _request_close(interaction)
        elif custom_id == "tk:claim":
            await _claim(interaction)
        elif custom_id == "tk:staff":
            action = interaction.data["values"][0]
            if action == "transfer":
                await _transfer(interaction)
            elif action == "links":
                await _toggle_links(interaction)
            elif action == "rename":
                await _rename(interaction)
            elif action == "adduser":
                await _add_or_remove_user(interaction, add=True)
            elif action == "removeuser":
                await _add_or_remove_user(interaction, add=False)
    except discord.HTTPException as exc:
        print(f"[tickets] interaction error: {exc}")


@bot.event
async def on_message(message: discord.Message):
    if message.guild is not None and not message.author.bot:
        ticket = ticket_data["open"].get(str(message.channel.id))
        if ticket is not None:
            ticket["last_activity"] = now_ts()
            if not ticket.get("links_allowed", True) and LINK_RE.search(message.content or "") \
                    and not is_staff(message.author):
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=notice(f"{E(['link~2', 'link_2', 'link2', 'link'], '🔗')} Links are turned off in this ticket."),
                        delete_after=6,
                    )
                except discord.HTTPException:
                    pass
    await bot.process_commands(message)


async def _inactivity_loop() -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        if INACTIVITY_HOURS:
            limit = INACTIVITY_HOURS * 3600
            for cid, ticket in list(ticket_data["open"].items()):
                if now_ts() - ticket["last_activity"] < limit:
                    continue
                channel = None
                for guild in bot.guilds:
                    channel = guild.get_channel(int(cid))
                    if channel is not None:
                        break
                if channel is not None:
                    await _close_ticket(channel.guild, channel, "Auto-close (inactivity)")
                else:
                    ticket_data["open"].pop(cid, None)
                    save_tickets()
        await asyncio.sleep(600)


@bot.tree.command(name="categorytickets", description="Choose the category where ticket channels are created.")
@app_commands.describe(category="The category where new tickets will be opened")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.guild_only()
async def categorytickets(interaction: discord.Interaction, category: discord.CategoryChannel):
    ticket_data["category_id"] = category.id
    save_tickets()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} New tickets will be opened in **{category.name}**."), ephemeral=True
    )


@bot.tree.command(name="tickets-setup", description="Post the ticket panel in this channel.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def tickets_setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await post_panel(interaction.channel, interaction.guild)
    await interaction.followup.send(embed=notice(f"{E('true', '✅')} Panel posted in {interaction.channel.mention}."), ephemeral=True)


# ---------------------------------------------------------------- welcomes (new members)

WELCOMES_FILE = DATA_DIR / "welcomes.json"
WELCOME_SERVER_NAME = "Synex Protect"
welcome_config: dict[str, int] = {}  # guild_id -> channel_id


def load_welcomes() -> None:
    global welcome_config
    try:
        welcome_config = json.loads(WELCOMES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        welcome_config = {}


def save_welcomes() -> None:
    WELCOMES_FILE.write_text(json.dumps(welcome_config, indent=2), encoding="utf-8")


def build_welcome_layout(member: discord.Member) -> discord.ui.LayoutView:
    title = discord.ui.TextDisplay(
        f"# {E('GE_member', '👋')} Welcome to {WELCOME_SERVER_NAME}, {member.mention}"
    )
    head = discord.ui.Section(title, accessory=discord.ui.Thumbnail(member.display_avatar.url))
    container = discord.ui.Container(
        head,
        discord.ui.Separator(),
        discord.ui.TextDisplay(
            "«Thank you for joining Synex Protect. We're excited to have you as part of our community.»"
        ),
        discord.ui.TextDisplay(
            f"-# {E('GE_member', '👤')} Member: {member.mention}\n"
            f"-# {E('GE_rules', '📜')} Please read our rules and guidelines.\n"
            f"-# {E('transfer', '🔁')} Stay tuned for upcoming updates."
        ),
        discord.ui.Separator(),
        accent_colour=STEEL,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


AUTOROLES_FILE = DATA_DIR / "autoroles.json"
autoroles: dict[str, int] = {}  # guild_id -> role_id


def load_autoroles() -> None:
    global autoroles
    try:
        autoroles = json.loads(AUTOROLES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        autoroles = {}


def save_autoroles() -> None:
    AUTOROLES_FILE.write_text(json.dumps(autoroles, indent=2), encoding="utf-8")


@bot.event
async def on_member_join(member: discord.Member):
    role_id = autoroles.get(str(member.guild.id))
    if role_id:
        role = member.guild.get_role(role_id)
        if role is not None and role < member.guild.me.top_role:
            try:
                await member.add_roles(role, reason="Auto role on join")
            except discord.HTTPException as exc:
                print(f"[autorol] could not give role: {exc}")

    channel_id = welcome_config.get(str(member.guild.id))
    if not channel_id:
        return
    channel = member.guild.get_channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(
            view=build_welcome_layout(member),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.HTTPException as exc:
        print(f"[welcomes] could not send welcome: {exc}")


@bot.tree.command(name="welcomes-setup", description="Send new member welcomes to this channel.")
@app_commands.describe(channel="The channel where welcomes will be sent")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    welcome_config[str(interaction.guild_id)] = channel.id
    save_welcomes()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} Welcomes will be sent in {channel.mention}."), ephemeral=True
    )


@bot.tree.command(name="autorol", description="Give this role automatically to everyone who joins.")
@app_commands.describe(role="The role new members receive")
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def autorol(interaction: discord.Interaction, role: discord.Role):
    me = interaction.guild.me
    if role.is_default() or role.managed or role >= me.top_role:
        return await interaction.response.send_message(
            embed=error_notice("I can't give that role. Make sure it's below my highest role and isn't managed by an integration."),
            ephemeral=True,
        )
    autoroles[str(interaction.guild_id)] = role.id
    save_autoroles()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} New members will get {role.mention}."), ephemeral=True
    )


@bot.tree.command(name="autorol-off", description="Stop giving the auto role to new members.")
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def autorol_off(interaction: discord.Interaction):
    autoroles.pop(str(interaction.guild_id), None)
    save_autoroles()
    await interaction.response.send_message(embed=notice("Auto role is off."), ephemeral=True)


@bot.tree.command(name="welcomes-off", description="Stop sending new member welcomes.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_off(interaction: discord.Interaction):
    welcome_config.pop(str(interaction.guild_id), None)
    save_welcomes()
    await interaction.response.send_message(embed=notice("Welcomes are off."), ephemeral=True)


# ---------------------------------------------------------------- run

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to your .env file.")
    bot.run(TOKEN)
