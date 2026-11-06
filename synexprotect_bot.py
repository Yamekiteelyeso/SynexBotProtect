import asyncio
import copy
import time
from collections import deque
import io
import json
import os
import platform
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
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
BOT_VERSION = "1.24.0"

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

def base_embed(title: str | None = None, description: str | None = None, color: int = CHARCOAL) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    if bot.user:
        embed.set_author(name=BOT_NAME, icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=f"{BOT_NAME} · v{BOT_VERSION}")
    return embed

def notice(text: str, color: int = CHARCOAL) -> discord.Embed:
    return discord.Embed(description=text, color=color)

def E(names, fallback: str = "") -> str:
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

def build_ping_layout() -> discord.ui.LayoutView:
    ms = round(bot.latency * 1000)
    if ms < 100:
        status, color = f"{E(['true', 'check'], '✅')} Excellent", 0x22C55E
    elif ms < 200:
        status, color = f"{E(['warn3', 'warn'], '🟡')} Good", 0xFACC15
    else:
        status, color = f"{E(['Error', 'warn'], '🔴')} Degraded", 0xEF4444
    head = discord.ui.TextDisplay(f"### {E(['ping', 'latency'], '⚡')} Pong\n-# Connection to Discord")
    stats = discord.ui.TextDisplay(f"**Latency** · `{ms} ms`\n**Status** · {status}")
    container = discord.ui.Container(
        head,
        discord.ui.Separator(),
        stats,
        discord.ui.Separator(),
        discord.ui.TextDisplay(f"-# {BOT_NAME} · v{BOT_VERSION}"),
        accent_colour=color,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view

def fixed_emoji(name: str, emoji_id: int, animated: bool = False) -> str:
    return f"<{'a' if animated else ''}:{name}:{emoji_id}>"

SERVER_SECTIONS = [
    ("Server", "server", "Overview of the server"),
    ("Roles", "roles", "All roles in this server"),
    ("Emojis", "emojis", "All custom emojis in this server"),
]

def _cap(text: str, limit: int = 3000) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"

def server_overview_text(guild: discord.Guild) -> str:
    roles = [r for r in guild.roles if not r.is_default()]
    humans = sum(1 for m in guild.members if not m.bot)
    bots = sum(1 for m in guild.members if m.bot)
    text_count, voice_count = len(guild.text_channels), len(guild.voice_channels)
    crown = fixed_emoji("Crown", 1568198986622574734)
    boosts = fixed_emoji("Boosts", 1568198366763159602)
    community = E("community11", "👥")
    hashtag = E("white_hashtag2", "#️⃣")
    star = fixed_emoji("estrella_vacia", 1568200011660140544)
    logo = fixed_emoji("synexprotect", 1568001429258641661)
    lines = [
        f"{crown} **Owner**\n{guild.owner.mention if guild.owner else 'Unknown'}",
        f"{boosts} **Server Boosts**\nLevel {guild.premium_tier} • {guild.premium_subscription_count} Boosts",
        f"{community} **Members**\n{guild.member_count:,} Total • {humans:,} humans • {bots:,} bots",
        f"{hashtag} **Channels**\n{text_count} Text • {voice_count} Voice",
        f"{star} **Roles**\n{len(roles)} Total",
        f"🕓 **Created**\n{discord.utils.format_dt(guild.created_at, 'D')} • {discord.utils.format_dt(guild.created_at, 'R')}",
        f"{logo} **Server ID**\n`{guild.id}`",
    ]
    return "\n\n".join(lines)

SERVER_ROLES_PER_PAGE = 10

def server_roles_page(guild: discord.Guild, page: int) -> tuple[str, int, int]:
    roles = [r for r in reversed(guild.roles) if not r.is_default()]
    pages = max(1, -(-len(roles) // SERVER_ROLES_PER_PAGE))
    page = min(max(page, 0), pages - 1)
    chunk = roles[page * SERVER_ROLES_PER_PAGE:(page + 1) * SERVER_ROLES_PER_PAGE]
    body = "  ".join(r.mention for r in chunk) or "None"
    text = f"**Roles · {len(roles)}**\n{body}"
    if pages > 1:
        text += f"\n-# Page {page + 1} of {pages}"
    return text, page, pages

def server_emojis_text(guild: discord.Guild) -> str:
    body = " ".join(str(e) for e in guild.emojis) or "None"
    return f"**Emojis · {len(guild.emojis)}**\n{_cap(body)}"

def build_server_layout(guild: discord.Guild, section: str = "server", page: int = 0) -> discord.ui.LayoutView:
    logo = fixed_emoji("synexprotect", 1568001429258641661)
    roles_page, pages = 0, 1
    if section == "roles":
        body, roles_page, pages = server_roles_page(guild, page)
    else:
        body = {
            "server": server_overview_text,
            "emojis": server_emojis_text,
        }.get(section, server_overview_text)(guild)

    title = discord.ui.TextDisplay(
        f"### {logo} Server Information\n-# {guild.name} · {guild.member_count:,} members"
    )
    head = (discord.ui.Section(title, accessory=discord.ui.Thumbnail(guild.icon.url))
            if guild.icon else title)

    select = discord.ui.Select(
        placeholder="Choose a section…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=label, value=value, description=desc, default=(value == section))
            for label, value, desc in SERVER_SECTIONS
        ],
    )

    async def on_pick(interaction: discord.Interaction):
        await interaction.response.edit_message(view=build_server_layout(guild, select.values[0]))

    select.callback = on_pick

    children = [
        head,
        discord.ui.Separator(),
        discord.ui.TextDisplay(body),
        discord.ui.Separator(),
        discord.ui.ActionRow(select),
    ]

    if section == "roles" and pages > 1:
        prev_btn = discord.ui.Button(label="Previous", emoji="◀️", style=discord.ButtonStyle.secondary,
                                     disabled=roles_page == 0)
        next_btn = discord.ui.Button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary,
                                     disabled=roles_page >= pages - 1)

        async def go_prev(interaction: discord.Interaction):
            await interaction.response.edit_message(view=build_server_layout(guild, "roles", roles_page - 1))

        async def go_next(interaction: discord.Interaction):
            await interaction.response.edit_message(view=build_server_layout(guild, "roles", roles_page + 1))

        prev_btn.callback = go_prev
        next_btn.callback = go_next
        children.append(discord.ui.ActionRow(prev_btn, next_btn))

    children.append(discord.ui.TextDisplay("-# Synex Protect • Server Information"))
    view = discord.ui.LayoutView(timeout=600)
    view.add_item(discord.ui.Container(*children, accent_colour=CHARCOAL))
    return view

def build_userinfo_embed(member: discord.Member) -> discord.Embed:
    roles = [r for r in reversed(member.roles) if not r.is_default()]
    role_text = " ".join(r.mention for r in roles[:15]) + (f" +{len(roles) - 15} more" if len(roles) > 15 else "")

    embed = base_embed(f"{E(['community', 'members'], '👤')} Profile", f"{member.mention}  ·  `{member}`", STEEL)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
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

def build_botinfo_layout() -> discord.ui.LayoutView:
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    total_members = sum(g.member_count or 0 for g in bot.guilds)
    commands_count = len(bot.tree.get_commands())
    head = discord.ui.TextDisplay(
        f"### {E(['synexprotect', 'shield'], '🛡️')} {BOT_NAME}\n-# Utility and protection for your community."
    )
    if bot.user:
        head = discord.ui.Section(head, accessory=discord.ui.Thumbnail(bot.user.display_avatar.url))
    stats = discord.ui.TextDisplay(
        f"**Servers** · {len(bot.guilds):,}\n"
        f"**Members** · {total_members:,}\n"
        f"**Commands** · {commands_count}\n"
        f"**Uptime** · {fmt_seconds(uptime)}"
    )
    container = discord.ui.Container(
        head,
        discord.ui.Separator(),
        stats,
        discord.ui.Separator(),
        discord.ui.TextDisplay(f"-# {BOT_NAME} · v{BOT_VERSION}"),
        accent_colour=STEEL,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view

def build_avatar(user: discord.abc.User) -> tuple[discord.Embed, discord.ui.View]:
    url = user.display_avatar.with_size(4096).url
    embed = base_embed(f"{E(['community', 'members'], '🖼️')} {user.display_name}", f"Avatar of {user.mention}", STEEL)
    embed.set_thumbnail(url=user.display_avatar.replace(size=256).url)
    embed.set_image(url=url)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Download", url=url, style=discord.ButtonStyle.link, emoji="⬇️"))
    return embed, view

@bot.event
async def on_ready():
    load_reaction_roles()
    load_tickets()
    load_welcomes()
    load_autoroles()
    load_antiraid()
    load_modlog()
    for guild in bot.guilds:
        await _refresh_invites(guild)
    await _sync_tickets_from_discord()
    bot.add_view(build_panel_view())
    for ticket in ticket_data["open"].values():
        if ticket.get("message_id"):
            bot.add_view(ticket_layout(ticket), message_id=ticket["message_id"])
    if not getattr(bot, "_tickets_loop_started", False):
        bot._tickets_loop_started = True
        asyncio.create_task(_inactivity_loop())
    if not getattr(bot, "_global_cleared", False):
        bot._global_cleared = True
        try:
            await bot.http.bulk_upsert_global_commands(bot.application_id, payload=[])
            print("[sync] global commands cleared (commands live per server only)")
        except discord.HTTPException as exc:
            print(f"[sync] could not clear global commands: {exc}")
    for guild in bot.guilds:
        await _sync_guild_commands(guild)
    print(f"{BOT_NAME} online as {bot.user} ({len(bot.guilds)} servers)")

async def _sync_guild_commands(guild: discord.Guild) -> None:
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"[sync] {guild.name}: {len(synced)} commands")

@bot.event
async def on_guild_join(guild: discord.Guild):
    await _sync_guild_commands(guild)

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

@bot.tree.command(name="bot-say", description="Send a message through the bot without revealing who sent it.")
@app_commands.describe(message="The message to send", channel="Channel to send it in (default: this one)")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def bot_say(interaction: discord.Interaction, message: str, channel: discord.TextChannel | None = None):
    target = channel or interaction.channel
    await target.send(message, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Message sent to {target.mention}."), ephemeral=True)

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

    embed = base_embed(f"{E(['check', 'success'], '✅')} Emoji added", f"{created}  ·  `:{created.name}:`", STEEL)
    await interaction.followup.send(embed=embed, ephemeral=True)

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
    embed = base_embed(f"{E(['check', 'success'], '🏷️')} Reaction role saved", color=STEEL)
    embed.add_field(name="Emoji", value=emoji, inline=True)
    embed.add_field(name="Role", value=role.mention, inline=True)
    embed.add_field(name="Works on", value=scope, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.command(name="addemojirole")
@commands.has_permissions(manage_roles=True)
@commands.guild_only()
async def addemojirole_prefix(ctx: commands.Context, emoji: str, role: discord.Role):
    ref = ctx.message.reference
    target = ref.resolved if ref and isinstance(ref.resolved, discord.Message) else None
    if target is None:
        return await ctx.send(embed=error_notice("Reply to the message you want, then type `!addemojirole <emoji> @role`."), delete_after=10)

    error = await _apply_reaction_role(ctx.guild, emoji, role, target, target.id)
    if error:
        return await ctx.send(embed=error_notice(error), delete_after=12)
    await ctx.send(embed=notice(f"{E('true', '✅')} {emoji} now gives {role.mention} on that message."), delete_after=8)

@bot.tree.command(name="ping", description="Show the bot's current latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(view=build_ping_layout())

@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    await ctx.send(view=build_ping_layout())

@bot.tree.command(name="serverinfo", description="Show statistics and information about this server.")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    await interaction.response.send_message(view=build_server_layout(interaction.guild))

@bot.command(name="server")
@commands.guild_only()
async def server_prefix(ctx: commands.Context):
    await ctx.send(view=build_server_layout(ctx.guild))

@bot.tree.command(name="userinfo", description="Show details about a user.")
@app_commands.describe(member="The user to inspect (default: you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    await interaction.response.send_message(embed=build_userinfo_embed(member or interaction.user))

@bot.command(name="user")
@commands.guild_only()
async def user_prefix(ctx: commands.Context, member: Optional[discord.Member] = None):
    await ctx.send(embed=build_userinfo_embed(member or ctx.author))

@bot.tree.command(name="botinfo", description="Show statistics about the bot.")
async def botinfo(interaction: discord.Interaction):
    await interaction.response.send_message(view=build_botinfo_layout())

@bot.command(name="botinfo")
async def botinfo_prefix(ctx: commands.Context):
    await ctx.send(view=build_botinfo_layout())

@bot.tree.command(name="avatar", description="Show a user's avatar in full size.")
@app_commands.describe(member="The user whose avatar to show (default: you)")
async def avatar(interaction: discord.Interaction, member: discord.User | None = None):
    embed, view = build_avatar(member or interaction.user)
    await interaction.response.send_message(embed=embed, view=view)

@bot.command(name="avatar")
async def avatar_prefix(ctx: commands.Context, member: Optional[discord.User] = None):
    embed, view = build_avatar(member or ctx.author)
    await ctx.send(embed=embed, view=view)

PUBLIC_COMMANDS = [
    ("ping", "Check the bot's response time and status.", "/ping  ·  !ping"),
    ("serverinfo", "Owner, boosts, members, channels, roles and creation date. Browse roles and emojis from the menu.", "/serverinfo  ·  !server"),
    ("userinfo", "Account details for a member: join date, account age and roles.", "/userinfo [member]  ·  !user [member]"),
    ("botinfo", "Uptime, latency, server count and runtime information.", "/botinfo  ·  !botinfo"),
    ("avatar", "Show a member's avatar at full size, with a download button.", "/avatar [member]  ·  !avatar [member]"),
    ("translate", "Translate a text, a message ID, or reply to any message. Use eng, esp, por or a code like fr.", "/translate language [text] [message_id]  ·  !translate language (reply to a message)"),
    ("afk", "Mark yourself as away. Mentions are logged and you get a summary when you come back.", "/afk [reason]  ·  !afk [reason]"),
    ("timer", "Start a timer everyone in the channel can see. You get a DM when it ends.", "/timer time reminder  ·  !timer time reminder"),
    ("hug", "Hug someone with an anime GIF. The person can hug back with one click.", "!hug [member]"),
    ("kiss", "Kiss someone with an anime GIF. The person can kiss back with one click.", "!kiss [member]"),
    ("punch", "Punch someone with an anime GIF. The person can punch back with one click.", "!punch [member]"),
    ("cry", "Cry with an anime GIF, alone or because of someone.", "!cry [member]"),
    ("sleep", "Go to sleep with an anime GIF, alone or next to someone.", "!sleep [member]"),
    ("banana", "Give someone a banana with an anime GIF.", "!banana [member]"),
    ("help", "Show this command list.", "/help  ·  !help"),
]

ADMIN_COMMANDS = [
    ("giveaway create", "Start a giveaway with automatic rerolls for winners who don't claim in time.", "/giveaway create prize duration [winners] [timereclaim]  ·  !giveway prize duration [winners] [timereclaim]", "Manage Server"),
    ("giveaway end", "End a giveaway early and pick the winners.", "/giveaway end message_id", "Manage Server"),
    ("giveaway reroll", "Pick new winners for prizes that were not claimed.", "/giveaway reroll message_id  ·  !reroll (reply to the giveaway)", "Manage Server"),
    ("tickets-setup", "Post the ticket panel in this channel.", "/tickets-setup", "Manage Server"),
    ("categorytickets", "Choose the category where new tickets are created.", "/categorytickets category", "Manage Channels"),
    ("poll", "Public poll with live vote counts and up to five options.", "/poll question option1 option2 [option3] [option4] [option5]", "Manage Messages"),
    ("bot-say", "Send a message through the bot without showing who sent it.", "/bot-say message [channel]", "Manage Messages"),
    ("embed", "Send a custom embed with color, footer and image.", "/embed [title] [description] [color] [footer] [image] [image_url]", "Manage Messages"),
    ("emojisteal", "Copy a custom emoji from another server into this one.", "/emojisteal emoji [name]", "Manage Expressions"),
    ("addemojirole", "Give a role when members react with an emoji. Reply to a message and use the prefix version to target it.", "/addemojirole emoji role [message_id]  ·  !addemojirole emoji @role (reply)", "Manage Roles"),
    ("removeemojirole", "Remove a reaction role rule.", "/removeemojirole emoji [message_id]", "Manage Roles"),
    ("autorol", "Give a role automatically to every new member.", "/autorol role", "Manage Roles"),
    ("autorol-off", "Stop giving the auto role to new members.", "/autorol-off", "Manage Roles"),
    ("welcomes-setup", "Send new member welcomes to a channel.", "/welcomes-setup channel", "Manage Server"),
    ("welcomes-on", "Turn welcomes back on in the default channel.", "/welcomes-on", "Manage Server"),
    ("welcomes-off", "Turn new member welcomes off.", "/welcomes-off", "Manage Server"),
    ("welcomes-button", "Set a welcome button: position, text, https link and optional emoji.", "/welcomes-button slot label url [emoji]", "Manage Server"),
    ("welcomes-button-remove", "Remove a welcome button by its position.", "/welcomes-button-remove slot", "Manage Server"),
    ("welcomes-buttons-reset", "Restore the default welcome buttons.", "/welcomes-buttons-reset", "Manage Server"),
    ("tickets-log", "Ticket log: who opened it, who claimed it, duration, members and transcript.", "/tickets-log [number]", "Staff"),
    ("invites-setup", "Post a message whenever someone joins with an invite, with their invite count.", "/invites-setup channel", "Manage Server"),
    ("invites-off", "Stop posting invite messages.", "/invites-off", "Manage Server"),
    ("despedidas-setup", "Send a goodbye message to a channel when members leave.", "/despedidas-setup channel", "Manage Server"),
    ("despedidas-off", "Turn goodbye messages off.", "/despedidas-off", "Manage Server"),
    ("welcomes-settings", "Show the current welcome channel and buttons.", "/welcomes-settings", "Manage Server"),
    ("invites-settings", "Show the current invite channel and tracking.", "/invites-settings", "Manage Server"),
    ("despedidas-settings", "Show the current goodbye channel.", "/despedidas-settings", "Manage Server"),
    ("servername", "Set the name the bot uses for this server in its messages.", "/servername name", "Manage Server"),
    ("servername-reset", "Use the real Discord server name again.", "/servername-reset", "Manage Server"),
    ("ban", "Ban a member, or a user by ID, and optionally delete their recent messages.", "/ban member [reason] [delete_days]  ·  !ban user [reason]", "Ban Members"),
    ("unban", "Unban a user by their ID.", "/unban user_id [reason]  ·  !unban user_id [reason]", "Ban Members"),
    ("kick", "Kick a member from the server.", "/kick member [reason]  ·  !kick member [reason]", "Kick Members"),
    ("mute", "Mute (timeout) a member for a set time, up to 28 days.", "/mute member duration [reason]  ·  !mute member duration [reason]", "Moderate Members"),
    ("unmute", "Remove a member's mute.", "/unmute member [reason]  ·  !unmute member [reason]", "Moderate Members"),
    ("modlog-setup", "Send moderation, invite and voice logs to a channel.", "/modlog-setup channel", "Manage Server"),
    ("modlog-events", "Choose which events are logged.", "/modlog-events", "Manage Server"),
    ("modlog-off", "Stop sending logs.", "/modlog-off", "Manage Server"),
    ("tickets-settings", "Show the current ticket category, channels, roles and limits.", "/tickets-settings", "Manage Server"),
    ("autorol-settings", "Show the role given to new members.", "/autorol-settings", "Manage Roles"),
    ("modlog-settings", "Show the current log channel and logged events.", "/modlog-settings", "Manage Server"),
    ("servername-settings", "Show the name the bot uses for this server.", "/servername-settings", "Manage Server"),
    ("antiraid", "Owner-only panel for anti-nuke, anti-webhook, anti-raid, trusted users and alerts.", "/antiraid", "Server owner"),
]

HELP_CATEGORIES = {
    "public": [
        ("Utility", ["ping", "serverinfo", "userinfo", "botinfo", "avatar"]),
        ("Tools", ["translate", "afk", "timer", "help"]),
        ("Anime reactions", ["hug", "kiss", "punch", "cry", "sleep", "banana"]),
    ],
    "admin": [
        ("Giveaways", ["giveaway create", "giveaway end", "giveaway reroll"]),
        ("Tickets", ["tickets-setup", "categorytickets", "tickets-log", "tickets-settings"]),
        ("Welcome & roles", ["welcomes-setup", "welcomes-on", "welcomes-off", "welcomes-button", "welcomes-button-remove", "welcomes-buttons-reset", "welcomes-settings", "autorol", "autorol-off", "autorol-settings", "addemojirole", "removeemojirole"]),
        ("Invites & goodbyes", ["invites-setup", "invites-off", "invites-settings", "despedidas-setup", "despedidas-off", "despedidas-settings"]),
        ("Server name", ["servername", "servername-reset", "servername-settings"]),
        ("Moderation", ["ban", "unban", "kick", "mute", "unmute"]),
        ("Logs", ["modlog-setup", "modlog-events", "modlog-off", "modlog-settings"]),
        ("Protection", ["antiraid"]),
        ("Moderation & tools", ["poll", "bot-say", "embed", "emojisteal"]),
    ],
}

PREFIX_MAP = {
    "ping": "ping",
    "serverinfo": "server",
    "userinfo": "user",
    "botinfo": "botinfo",
    "avatar": "avatar",
    "help": "help",
    "timer": "timer",
    "giveaway create": "giveway",
    "reroll": "reroll",
    "addemojirole": "addemojirole",
    "ban": "ban",
    "unban": "unban",
    "kick": "kick",
    "mute": "mute",
    "unmute": "unmute",
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
        embed = base_embed(_command_label(entry[0]), entry[1], INK if self.admin else SLATE)
        embed.add_field(name="Usage", value=f"`{entry[2]}`", inline=False)
        if self.admin:
            embed.add_field(name="Required permission", value=entry[3], inline=True)
        await interaction.response.edit_message(embed=embed, view=self.view)

class CommandView(discord.ui.View):
    def __init__(self, owner_id: int, entries: list[tuple], admin: bool = False):
        super().__init__(timeout=180)
        for start in range(0, len(entries), 25):
            self.add_item(CommandSelect(owner_id, entries[start:start + 25], admin))

def _command_label(name: str) -> str:
    return f"!{name}" if name in ANIME_ACTIONS else f"/{name}"


def _help_fields(entries: list[tuple], groups: list[tuple[str, list[str]]], admin: bool) -> list[tuple[str, str]]:
    by_name = {e[0]: e for e in entries}
    fields = []
    for title, names in groups:
        lines = []
        for name in names:
            entry = by_name.get(name)
            if entry is None:
                continue
            prefix = f" · `!{PREFIX_MAP[name]}`" if name in PREFIX_MAP else ""
            perm = f" · *{entry[3]}*" if admin else ""
            lines.append(f"**`{_command_label(name)}`**{prefix}{perm}\n{entry[1]}")
        chunks, current = [], ""
        for line in lines:
            candidate = f"{current}\n\n{line}" if current else line
            if len(candidate) > 1000 and current:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)
        for index, chunk in enumerate(chunks):
            fields.append((title if index == 0 else f"{title} (cont.)", chunk))
    return fields


def build_help_embed() -> discord.Embed:
    intro = (
        f"Welcome to **{BOT_NAME}**, the protection and utility bot for your community.\n\n"
        "Every command works as a slash command (`/`), and most also work with the prefix `!`. "
        "Pick a command in the menu below to see its full usage."
    )
    embed = base_embed("Command center", intro, SLATE)
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    for name, value in _help_fields(PUBLIC_COMMANDS, HELP_CATEGORIES["public"], admin=False):
        embed.add_field(name=name, value=value, inline=False)
    embed.add_field(
        name="Need help?",
        value="Open a ticket from the support panel, or ask a staff member.",
        inline=False,
    )
    embed.set_footer(text=f"{BOT_NAME} · Prefix ! · v{BOT_VERSION}")
    return embed


def build_helpadmin_embed() -> discord.Embed:
    intro = (
        "Commands for staff. Each one requires the permission shown next to it.\n\n"
        "Pick a command in the menu below to see its usage."
    )
    embed = base_embed(f"{E('transfer', '🔁')} Administrator commands", intro, INK)
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    by_name = {e[0]: e for e in ADMIN_COMMANDS}
    for title, names in HELP_CATEGORIES["admin"]:
        present = [n for n in names if n in by_name]
        if not present:
            continue
        perms = " · ".join(sorted({by_name[n][3] for n in present}))
        value = " · ".join(f"`{_command_label(n)}`" for n in present)
        embed.add_field(name=f"{title} · {perms}", value=value[:1024], inline=False)
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

class PollView(discord.ui.View):

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

        embed = base_embed(f"{E(['poll', 'stats'], '📊')} {self.question}", "\n\n".join(rows), SLATE)
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

async def _finish_timer(channel: discord.abc.Messageable, user: discord.abc.User, text: str, delay: int) -> None:
    await asyncio.sleep(delay)
    done = base_embed(f"{E(['timer', 'clock'], '⏰')} Timer finished", text, STEEL)
    done.set_thumbnail(url=user.display_avatar.url)
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
    ends = now_ts() + seconds
    embed = base_embed(f"{E(['timer', 'clock'], '⏰')} Timer started", text, STEEL)
    embed.set_thumbnail(url=user.display_avatar.url)
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

import random

LANGUAGE_ALIASES = {
    "esp": "es", "spa": "es", "spanish": "es", "español": "es", "espanol": "es", "castellano": "es",
    "eng": "en", "english": "en", "ingles": "en", "inglés": "en",
    "por": "pt", "port": "pt", "portuguese": "pt", "portugues": "pt", "português": "pt",
    "fra": "fr", "french": "fr", "frances": "fr", "francés": "fr",
    "ita": "it", "italian": "it", "italiano": "it",
    "deu": "de", "ger": "de", "german": "de", "aleman": "de", "alemán": "de",
    "jap": "ja", "japanese": "ja", "japones": "ja", "japonés": "ja",
    "chi": "zh-CN", "chinese": "zh-CN", "chino": "zh-CN",
    "rus": "ru", "russian": "ru", "ruso": "ru",
}
LANGUAGE_NAMES = {
    "es": "Español", "en": "English", "pt": "Português", "fr": "Français", "it": "Italiano",
    "de": "Deutsch", "ja": "日本語", "ko": "한국어", "zh-CN": "中文", "ru": "Русский",
    "ar": "العربية", "hi": "हिन्दी", "tr": "Türkçe", "nl": "Nederlands", "pl": "Polski",
}


def _lang_code(value: str) -> str:
    cleaned = value.strip().lower()
    return LANGUAGE_ALIASES.get(cleaned, cleaned)


def _source_text(message: discord.Message) -> str:
    parts = []
    if message.content:
        parts.append(message.content)
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(f"{field.name}\n{field.value}")
    return "\n\n".join(p for p in parts if p and p.strip()).strip()


def _split_text(text: str, limit: int = 4500) -> list[str]:
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"


async def _google_translate_chunk(chunk: str, language: str) -> str:
    import aiohttp
    params = {"client": "gtx", "sl": "auto", "tl": language, "dt": "t"}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(TRANSLATE_ENDPOINT, params=params, data={"q": chunk}) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            data = await resp.json(content_type=None)
    return "".join(part[0] for part in (data[0] or []) if part and part[0])


def _fallback_translate_chunk(chunk: str, language: str) -> str:
    return GoogleTranslator(source="auto", target=language).translate(chunk) or ""


async def _translate_text(text: str, language: str) -> str | None:
    pieces = []
    for chunk in _split_text(text, limit=1500):
        result = None
        for _ in range(2):
            try:
                result = await _google_translate_chunk(chunk, language)
                break
            except Exception as exc:
                print(f"[translate] direct request failed: {exc}")
                await asyncio.sleep(0.5)
        if result is None:
            try:
                result = await asyncio.to_thread(_fallback_translate_chunk, chunk, language)
            except Exception as exc:
                print(f"[translate] could not translate to {language!r}: {exc}")
                return None
        pieces.append(result)
    final = "".join(pieces).strip()
    return final or None


def _translation_embed(original: str, translated: str, language: str) -> discord.Embed:
    embed = base_embed(f"{E(['transfer', 'community'], '🌐')} Translation", translated[:4000], STEEL)
    name = LANGUAGE_NAMES.get(language, language)
    short_original = original if len(original) <= 300 else original[:300] + "…"
    embed.add_field(name="Language", value=f"**{name}** · `{language}`", inline=True)
    embed.add_field(name="Original", value=short_original, inline=False)
    return embed


@bot.command(name="translate")
async def translate_prefix(ctx: commands.Context, language: str, *, text: str | None = None):
    gid = ctx.guild.id if ctx.guild else 0
    source = None
    reference = ctx.message.reference
    if reference is not None and reference.message_id is not None:
        source = reference.resolved if isinstance(reference.resolved, discord.Message) else None
        if source is None:
            try:
                source = await ctx.channel.fetch_message(reference.message_id)
            except discord.HTTPException:
                source = None
        if source is None:
            return await ctx.reply(embed=error_notice(tr(gid, "translate.not_found")), mention_author=False)
    source_text = text.strip() if text and text.strip() else (_source_text(source) if source else "")
    if not source_text:
        return await ctx.reply(embed=error_notice(tr(gid, "translate.need_text")), mention_author=False)
    code = _lang_code(language)
    translated = await _translate_text(source_text, code)
    if translated is None:
        return await ctx.reply(embed=error_notice(tr(gid, "translate.failed")), mention_author=False)
    if source is not None:
        for start in range(0, len(translated), 2000):
            if start == 0:
                await ctx.reply(translated[start:start + 2000], mention_author=False,
                                allowed_mentions=discord.AllowedMentions.none())
            else:
                await ctx.send(translated[start:start + 2000], allowed_mentions=discord.AllowedMentions.none())
        return
    await ctx.reply(embed=_translation_embed(source_text, translated, code), mention_author=False)


@bot.tree.command(name="translate", description="Translate a text, or a message by its ID, into another language.")
@app_commands.describe(language="Language: eng, esp, por, or a code like fr", text="The text to translate",
                       message_id="ID of a message in this channel to translate")
async def translate(interaction: discord.Interaction, language: str, text: str | None = None,
                    message_id: str | None = None):
    gid = interaction.guild_id or 0
    source = None
    if message_id:
        try:
            source = await interaction.channel.fetch_message(int(message_id.strip()))
        except (ValueError, discord.HTTPException):
            return await interaction.response.send_message(
                embed=error_notice(tr(gid, "translate.not_found")), ephemeral=True)
    if not text and source is None:
        return await interaction.response.send_message(
            embed=error_notice(tr(gid, "translate.need_input")), ephemeral=True)
    source_text = text.strip() if text and text.strip() else _source_text(source)
    if not source_text:
        return await interaction.response.send_message(
            embed=error_notice(tr(gid, "translate.need_text")), ephemeral=True)
    private = source is None
    await interaction.response.defer(ephemeral=private)
    code = _lang_code(language)
    translated = await _translate_text(source_text, code)
    if translated is None:
        return await interaction.followup.send(embed=error_notice(tr(gid, "translate.failed")), ephemeral=True)
    await interaction.followup.send(embed=_translation_embed(source_text, translated, code), ephemeral=private)


@translate.autocomplete("language")
async def translate_language_autocomplete(interaction: discord.Interaction, current: str):
    text = current.lower().strip()
    return [
        app_commands.Choice(name=f"{name}  ·  {code}", value=code)
        for code, name in LANGUAGE_NAMES.items()
        if not text or text in name.lower() or text in code.lower()
    ][:25]

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
        "winners_list": [],
        "past_winners": set(),
        "claimed": set(),
        "announce": {},
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
    found = next((e for e in bot.emojis if e.name == name), None)
    return str(found) if found else fallback

def build_dm_layout(uid: int, info: dict, state: str) -> discord.ui.LayoutView:
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

async def _open_giveaway_ticket(guild: discord.Guild, user: discord.Member, prize: str) -> discord.TextChannel | None:
    ttype = ticket_type("giveaways")
    category_id = ticket_data.get("category_id") or TICKET_CATEGORY_ID
    category = guild.get_channel(category_id) if category_id else None
    ticket_data["counter"] += 1
    number = ticket_data["counter"]
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
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
            f"giveaway-{number:04d}-{slugify(user.name)}"[:100],
            category=category,
            overwrites=overwrites,
            topic=f"ticket|owner:{user.id}|n:{number}|type:giveaways",
            reason=f"Giveaway prize claimed by {user}",
        )
    except discord.HTTPException as exc:
        print(f"[giveaway] could not open ticket: {exc}")
        ticket_data["counter"] -= 1
        return None

    ticket = {
        "user_id": user.id,
        "type": ttype["label"] if ttype else "Giveaways",
        "type_key": "giveaways",
        "number": number,
        "claimed_by": None,
        "opened_at": now_ts(),
        "last_activity": now_ts(),
        "links_allowed": True,
        "avatar": user.display_avatar.url,
        "welcome_head": f"{user.mention}\n### {E('gift', '🎁')} Giveaway prize · {prize}",
        "welcome_body": (
            f"Congratulations **{user.display_name}**! Your prize **{prize}** is being handled in this ticket.\n\n"
            "A staff member will be with you shortly.\n\n"
            f"> **Category** · Giveaways\n> **Ticket** · #{number:04d}\n"
            f"> **Opened** · {discord.utils.format_dt(discord.utils.utcnow(), 'f')}"
        ),
    }
    ticket_data["open"][str(channel.id)] = ticket
    layout = ticket_layout(ticket)
    msg = await channel.send(view=layout, allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False))
    ticket["message_id"] = msg.id
    save_tickets()
    return channel

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

        channel = await _open_giveaway_ticket(interaction.guild, interaction.user, data["prize"])
        if channel is not None:
            await interaction.followup.send(
                embed=notice(f"{E('true', '✅')} Your prize ticket is ready: {channel.mention}"), ephemeral=True
            )

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
    data = giveaways[gid]
    pool = [u for u in data["entries"] if u not in data["past_winners"]]
    chosen = random.sample(pool, min(count, len(pool))) if pool else []
    data["past_winners"].update(chosen)
    return chosen

async def _replace_winner(gid: int, old_uid: int) -> bool:
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

TICKET_CATEGORY_ID: int | None = None
LOGS_CHANNEL_ID: int | None = None
TRANSCRIPT_CHANNEL_ID: int | None = None
SUPPORT_ROLE_IDS: list[int] = []
MAX_OPEN_PER_USER = 1
INACTIVITY_HOURS = 0
SAVE_TRANSCRIPTS = True
DM_TRANSCRIPT_ON_CLOSE = True

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

TICKET_TOPIC_RE = re.compile(r"^ticket\|owner:(\d+)\|n:(\d+)\|type:(\S+)")

def build_ticket_controls(ticket: dict, head: str = "", body: str = "", avatar_url: str | None = None) -> discord.ui.LayoutView:
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

async def _collect_transcript(channel: discord.TextChannel) -> tuple[bytes, dict[str, str]]:
    lines = []
    people: dict[str, str] = {}
    async for m in channel.history(limit=None, oldest_first=True):
        if not m.author.bot:
            people[str(m.author.id)] = str(m.author)
        text = m.content or ""
        if m.embeds:
            text += " [embed]"
        if m.attachments:
            text += " " + " ".join(a.url for a in m.attachments)
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M:%S} UTC] {m.author} ({m.author.id}): {text}")
    return ("\n".join(lines) or "(no messages)").encode("utf-8"), people

from html import escape as html_escape


async def _build_html_transcript(channel: discord.TextChannel) -> bytes:
    rows = []
    async for m in channel.history(limit=None, oldest_first=True):
        when = m.created_at.strftime("%Y-%m-%d %H:%M UTC")
        body = html_escape(m.content or "").replace("\n", "<br>")
        extras = []
        for a in m.attachments:
            url = html_escape(a.url, quote=True)
            if (a.content_type or "").startswith("image/"):
                extras.append(f'<img class="attachment" src="{url}" alt="{html_escape(a.filename)}">')
            else:
                extras.append(f'<a href="{url}">{html_escape(a.filename)}</a>')
        avatar = html_escape(m.author.display_avatar.url, quote=True)
        rows.append(
            '<div class="msg">'
            f'<img class="avatar" src="{avatar}" alt="">'
            '<div class="body">'
            f'<div class="head"><span class="name">{html_escape(m.author.display_name)}</span>'
            f'<span class="time">{when}</span></div>'
            f'<div class="text">{body}</div>'
            + "".join(extras) +
            '</div></div>'
        )
    title = html_escape(channel.name)
    page = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{title}</title>'
        '<style>'
        'body{background:#1a1c20;color:#e6e8eb;font-family:system-ui,sans-serif;margin:0;padding:24px}'
        '.wrap{max-width:860px;margin:auto}'
        'h1{font-size:20px;color:#9aa1ac;font-weight:600;border-bottom:1px solid #2a2e35;padding-bottom:12px}'
        '.msg{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid #2a2e35}'
        '.avatar{width:40px;height:40px;border-radius:50%;flex:none}'
        '.head{display:flex;gap:10px;align-items:baseline}.name{font-weight:600}'
        '.time{font-size:12px;color:#9aa1ac}'
        '.text{margin-top:4px;word-break:break-word}'
        '.attachment{max-width:360px;border-radius:8px;margin-top:6px;display:block}'
        '</style></head><body><div class="wrap">'
        f'<h1>{title}</h1>'
        + ("".join(rows) or "<p>No messages.</p>") +
        '</div></body></html>'
    )
    return page.encode("utf-8")


async def _close_ticket(guild: discord.Guild, channel: discord.TextChannel, closed_by: str, reason: str | None = None) -> None:
    ticket = ticket_data["open"].pop(str(channel.id), None)
    if ticket is None:
        return
    save_tickets()

    data, people, html_data = None, {}, None
    if SAVE_TRANSCRIPTS:
        data, people = await _collect_transcript(channel)
        html_data = await _build_html_transcript(channel)
    _save_closed_ticket(channel, ticket, closed_by, data, people)
    duration = fmt_seconds(now_ts() - ticket["opened_at"])
    owner_mention = f"<@{ticket['user_id']}>"

    def transcript_file():
        return discord.File(io.BytesIO(html_data), filename=f"{channel.name}.html") if html_data is not None else None

    if html_data is not None and TRANSCRIPT_CHANNEL_ID:
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
    if reason:
        log.add_field(name="Reason", value=reason[:1024], inline=False)
    await _log(guild, log)

    if DM_TRANSCRIPT_ON_CLOSE or reason:
        owner = await _resolve_user(ticket["user_id"])
        if owner is not None:
            dm_embed = base_embed(f"{E('warn3', '🔒')} Your ticket was closed", f"**{ticket['type']}** · open for {duration}", STEEL)
            if reason:
                dm_embed.add_field(name="Reason", value=reason[:1024], inline=False)
            try:
                kwargs = {"file": transcript_file()} if html_data is not None else {}
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

TICKET_HISTORY_FILE = DATA_DIR / "tickets_history.json"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
ticket_history: dict[str, dict] = {}


def load_ticket_history() -> None:
    global ticket_history
    try:
        ticket_history = json.loads(TICKET_HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        ticket_history = {}


def save_ticket_history() -> None:
    TICKET_HISTORY_FILE.write_text(json.dumps(ticket_history, indent=2), encoding="utf-8")


def _save_closed_ticket(channel, ticket: dict, closed_by: str, data: bytes | None, people: dict[str, str]) -> None:
    transcript_path = None
    if data is not None:
        TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        path = TRANSCRIPTS_DIR / f"{channel.id}.txt"
        path.write_bytes(data)
        transcript_path = str(path)
    ticket_history[str(channel.id)] = {
        "number": ticket.get("number", 0),
        "type": ticket.get("type", "Ticket"),
        "owner_id": ticket["user_id"],
        "claimed_by": ticket.get("claimed_by"),
        "opened_at": ticket["opened_at"],
        "closed_at": now_ts(),
        "closed_by": closed_by,
        "participants": people,
        "transcript": transcript_path,
    }
    save_ticket_history()


def _member_line(uid: str, people: dict[str, str]) -> str:
    return f"• <@{uid}> · `{uid}` · {people.get(uid, 'unknown')}"


@bot.tree.command(name="tickets-log", description="Show a ticket's log: opener, staff, duration, members and transcript.")
@app_commands.describe(number="Ticket number, e.g. 12. Leave empty to use this channel.")
@app_commands.guild_only()
async def tickets_log(interaction: discord.Interaction, number: int | None = None):
    if not is_staff(interaction.user):
        return await interaction.response.send_message(embed=error_notice("Only staff can use this."), ephemeral=True)
    if number is None:
        key = str(interaction.channel_id)
    else:
        key = next((cid for cid, t in ticket_data["open"].items() if t.get("number") == number), None)
        if key is None:
            key = next((cid for cid, r in ticket_history.items() if r.get("number") == number), None)
    if key is None or (key not in ticket_data["open"] and key not in ticket_history):
        return await interaction.response.send_message(embed=error_notice("I couldn't find that ticket."), ephemeral=True)

    await interaction.response.defer()
    if key in ticket_data["open"]:
        live = ticket_data["open"][key]
        channel = interaction.guild.get_channel(int(key))
        data, people = None, {}
        if channel is not None:
            data, people = await _collect_transcript(channel)
        record = {
            "number": live.get("number", 0), "type": live.get("type", "Ticket"), "owner_id": live["user_id"],
            "claimed_by": live.get("claimed_by"), "opened_at": live["opened_at"], "closed_at": None,
            "closed_by": None, "participants": people,
        }
        transcript = discord.File(io.BytesIO(data), filename=f"ticket-{record['number']:04d}.txt") if data is not None else None
    else:
        record = ticket_history[key]
        path = record.get("transcript")
        transcript = discord.File(path, filename=f"ticket-{record['number']:04d}.txt") if path and Path(path).exists() else None

    owner = record["owner_id"]
    claimed = record.get("claimed_by")
    closed = record.get("closed_at")
    duration = fmt_seconds((closed or now_ts()) - record["opened_at"])
    people = dict(record.get("participants") or {})
    ordered = [str(owner)]
    if claimed:
        ordered.append(str(claimed))
    ordered += [uid for uid in people if uid not in ordered]
    member_lines = [_member_line(uid, people) for uid in ordered[:25]]
    if len(ordered) > 25:
        member_lines.append(f"-# +{len(ordered) - 25} more")
    claimed_text = f"<@{claimed}> · `{claimed}`" if claimed else "Not claimed"
    info = [
        f"**Opened by** <@{owner}> · `{owner}`",
        f"**Claimed by** {claimed_text}",
        f"**Opened** <t:{record['opened_at']}:f>",
    ]
    if closed:
        info.append(f"**Closed** <t:{closed}:f> by {record.get('closed_by') or 'Unknown'}")
    info.append(f"**Duration** {duration}")
    status = f"{E('Error', '🔒')} Closed" if closed else f"{E('true', '🟢')} Open"
    note = "Transcript attached" if transcript is not None else "No transcript saved"
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"### 🎫 Ticket #{record['number']:04d} · {record['type']}\n-# {status}"),
        discord.ui.Separator(),
        discord.ui.TextDisplay("\n".join(info)),
        discord.ui.Separator(),
        discord.ui.TextDisplay("**Members**\n" + "\n".join(member_lines)),
        discord.ui.Separator(),
        discord.ui.TextDisplay(f"-# {BOT_NAME} · Ticket log · {note}"),
        accent_colour=STEEL,
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    if transcript is not None:
        await interaction.followup.send(view=view, file=transcript)
    else:
        await interaction.followup.send(view=view)


load_ticket_history()


class ConfirmView(discord.ui.View):
    def __init__(self, on_confirm, label: str = "Confirm", style: discord.ButtonStyle = discord.ButtonStyle.danger):
        super().__init__(timeout=60)
        self.on_confirm = on_confirm
        button = discord.ui.Button(label=label, style=style, emoji="✅")
        button.callback = self._confirm
        self.add_item(button)

    async def _confirm(self, interaction: discord.Interaction):
        await self.on_confirm(interaction)

class CloseReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(
        label="Reason (sent to the ticket owner)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    def __init__(self, gid=0):
        super().__init__(title=tr(gid, "close.modal"), timeout=300)
        self.reason.label = tr(gid, "close.reason_label")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await _close_ticket(interaction.guild, interaction.channel, interaction.user.mention,
                            reason=str(self.reason.value).strip())


class CloseChoiceView(discord.ui.View):
    def __init__(self, gid=0):
        super().__init__(timeout=120)
        self.gid = gid
        self.children[0].label = tr(gid, "close.now")
        self.children[1].label = tr(gid, "close.with_reason")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await _close_ticket(interaction.guild, interaction.channel, interaction.user.mention)

    @discord.ui.button(label="Close with reason", style=discord.ButtonStyle.secondary, emoji="📝")
    async def close_with_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseReasonModal(self.gid))


class CloseConfirmView(discord.ui.View):
    def __init__(self, gid=0):
        super().__init__(timeout=60)
        self.gid = gid
        self.children[0].label = tr(gid, "close.yes")
        self.children[1].label = tr(gid, "close.no")

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=notice(tr(self.gid, "close.choose")), view=CloseChoiceView(self.gid)
        )

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=notice(tr(self.gid, "close.cancelled")), view=None)


async def _request_close(interaction: discord.Interaction) -> None:
    ticket = ticket_data["open"].get(str(interaction.channel_id))
    if ticket is None:
        return await interaction.response.send_message(embed=error_notice("This isn't a ticket channel."), ephemeral=True)
    if not can_manage_ticket(interaction.user, ticket):
        return await interaction.response.send_message(
            embed=error_notice("Only the ticket owner or staff can close this ticket."), ephemeral=True
        )
    await interaction.response.send_message(
        embed=notice(tr(interaction.guild_id, "close.confirm")),
        view=CloseConfirmView(interaction.guild_id),
        ephemeral=True,
    )

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

WELCOMES_FILE = DATA_DIR / "welcomes.json"
WELCOME_SERVER_NAME = "Synex Protect"
DEFAULT_WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID") or 1557387592192753747)
welcome_config: dict[str, int] = {}

def load_welcomes() -> None:
    global welcome_config
    try:
        welcome_config = json.loads(WELCOMES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        welcome_config = {}

def save_welcomes() -> None:
    WELCOMES_FILE.write_text(json.dumps(welcome_config, indent=2), encoding="utf-8")

WELCOME_LINKS = [
    ("See Rules", ["GE_rules"], "https://discord.com/channels/1557386505226420385/1557387851619106897"),
    ("Chat", ["community~1", "community_1", "community1", "community"], "https://discord.com/channels/1557386505226420385/1557389744957292555"),
    ("Tickets", ["NofiTicket"], "https://discord.com/channels/1557386505226420385/1557389744957292555"),
]

WELCOME_BUTTONS_FILE = DATA_DIR / "welcome_buttons.json"
welcome_buttons_config: dict[str, list[dict]] = {}
WELCOME_BUTTON_LIMIT = 5


def load_welcome_buttons() -> None:
    global welcome_buttons_config
    try:
        welcome_buttons_config = json.loads(WELCOME_BUTTONS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        welcome_buttons_config = {}


def save_welcome_buttons() -> None:
    WELCOME_BUTTONS_FILE.write_text(json.dumps(welcome_buttons_config, indent=2), encoding="utf-8")


def welcome_buttons_for(guild_id: int) -> list[dict]:
    custom = welcome_buttons_config.get(str(guild_id))
    if custom is not None:
        return [dict(btn) for btn in custom]
    return [{"label": label, "url": url, "names": names} for label, names, url in WELCOME_LINKS]


def _welcome_button(btn: dict) -> discord.ui.Button:
    emoji = btn.get("emoji") or E(btn.get("names", []), "🔗")
    return discord.ui.Button(label=btn["label"], emoji=emoji, style=discord.ButtonStyle.link, url=btn["url"])


load_welcome_buttons()


@bot.tree.command(name="welcomes-button", description="Set one welcome button: text, link and optional emoji.")
@app_commands.describe(slot="Button position, 1 to 5", label="Button text", url="Link, starting with https://", emoji="Optional emoji")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_button(
    interaction: discord.Interaction,
    slot: app_commands.Range[int, 1, WELCOME_BUTTON_LIMIT],
    label: app_commands.Range[str, 1, 80],
    url: str,
    emoji: str | None = None,
):
    url = url.strip()
    if not url.startswith("https://"):
        return await interaction.response.send_message(embed=error_notice("The link must start with https://"), ephemeral=True)
    emoji_value = None
    if emoji and emoji.strip():
        try:
            discord.PartialEmoji.from_str(emoji.strip())
        except (ValueError, TypeError):
            return await interaction.response.send_message(embed=error_notice("That emoji is not valid."), ephemeral=True)
        emoji_value = emoji.strip()
    buttons = welcome_buttons_for(interaction.guild_id)
    if slot > len(buttons) + 1:
        return await interaction.response.send_message(
            embed=error_notice(f"Fill slot {len(buttons) + 1} first."), ephemeral=True
        )
    entry = {"label": label.strip(), "url": url, "emoji": emoji_value}
    if slot > len(buttons):
        buttons.append(entry)
    else:
        buttons[slot - 1] = entry
    welcome_buttons_config[str(interaction.guild_id)] = buttons
    save_welcome_buttons()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} Welcome button {slot} saved: **{entry['label']}**."), ephemeral=True
    )


@bot.tree.command(name="welcomes-button-remove", description="Remove one welcome button by its position.")
@app_commands.describe(slot="Button position, 1 to 5")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_button_remove(interaction: discord.Interaction, slot: app_commands.Range[int, 1, WELCOME_BUTTON_LIMIT]):
    buttons = welcome_buttons_for(interaction.guild_id)
    if slot > len(buttons):
        return await interaction.response.send_message(embed=error_notice("There is no button in that slot."), ephemeral=True)
    if len(buttons) == 1:
        return await interaction.response.send_message(
            embed=error_notice("A welcome message needs at least one button."), ephemeral=True
        )
    buttons.pop(slot - 1)
    welcome_buttons_config[str(interaction.guild_id)] = buttons
    save_welcome_buttons()
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Welcome button {slot} removed."), ephemeral=True)


@bot.tree.command(name="welcomes-buttons-reset", description="Restore the default welcome buttons.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_buttons_reset(interaction: discord.Interaction):
    welcome_buttons_config.pop(str(interaction.guild_id), None)
    save_welcome_buttons()
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Default welcome buttons restored."), ephemeral=True)


GOODBYES_FILE = DATA_DIR / "goodbyes.json"
goodbye_config: dict[str, int] = {}


def load_goodbyes() -> None:
    global goodbye_config
    try:
        goodbye_config = json.loads(GOODBYES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        goodbye_config = {}


def save_goodbyes() -> None:
    GOODBYES_FILE.write_text(json.dumps(goodbye_config, indent=2), encoding="utf-8")


async def _send_goodbye(member: discord.Member) -> None:
    channel_id = goodbye_config.get(str(member.guild.id))
    channel = member.guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return
    try:
        await channel.send(view=build_goodbye_layout(member), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[goodbye] could not post: {exc}")


@bot.tree.command(name="despedidas-setup", description="Send a goodbye message to a channel when members leave.")
@app_commands.describe(channel="The channel for goodbye messages")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def despedidas_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    goodbye_config[str(interaction.guild_id)] = channel.id
    save_goodbyes()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} {tr(interaction.guild_id, 'goodbye.set', channel=channel.mention)}"), ephemeral=True
    )


@bot.tree.command(name="despedidas-off", description="Turn goodbye messages off.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def despedidas_off(interaction: discord.Interaction):
    goodbye_config.pop(str(interaction.guild_id), None)
    save_goodbyes()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} {tr(interaction.guild_id, 'goodbye.off')}"), ephemeral=True
    )


bot.add_listener(_send_goodbye, "on_member_remove")
load_goodbyes()

LANGUAGES_FILE = DATA_DIR / "languages.json"
guild_langs: dict[str, str] = {}


def load_languages() -> None:
    global guild_langs
    try:
        guild_langs = json.loads(LANGUAGES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        guild_langs = {}


def save_languages() -> None:
    LANGUAGES_FILE.write_text(json.dumps(guild_langs, indent=2), encoding="utf-8")


STRINGS = {
    "en": {
        "anime.hug.text": "{a} hugs {b}",
        "anime.hug.solo": "{a} hugs themselves",
        "anime.hug.back": "{a} hugs {b} back",
        "anime.hug.noun": "hugs",
        "anime.kiss.text": "{a} kisses {b}",
        "anime.kiss.solo": "{a} blows a kiss",
        "anime.kiss.back": "{a} kisses {b} back",
        "anime.kiss.noun": "kisses",
        "anime.punch.text": "{a} punches {b}",
        "anime.punch.solo": "{a} punches themselves",
        "anime.punch.back": "{a} punches {b} back",
        "anime.punch.noun": "punches",
        "anime.cry.text": "{a} is crying because of {b}",
        "anime.cry.solo": "{a} is crying",
        "anime.sleep.text": "{a} is sleeping next to {b}",
        "anime.sleep.solo": "{a} went to sleep",
        "anime.banana.text": "{a} gives {b} a banana",
        "anime.banana.solo": "{a} enjoys their banana",
        "anime.banana.measure": "{a} banana: {cm}cm",
        "anime.banana.measure_for": "{b} banana: {cm}cm",
        "anime.note": "{a} and {b} have **{n}** {noun}",
        "anime.return": "Return",
        "anime.footer": "{bot} · Anime reactions",
        "anime.only_receiver": "Only the person who received it can give it back.",
        "afk.now": "You are now AFK",
        "afk.reason_default": "AFK",
        "afk.welcome_title": "Welcome back",
        "afk.welcome": "Welcome back {a}! You were AFK for **{time}**.",
        "afk.mentions": "You were mentioned **{n}** time(s).",
        "afk.jump": "Jump to message",
        "afk.is_afk": "**{name}** is AFK",
        "afk.mention_title": "{name} has been AFK for {time}",
        "afk.since": "Since",
        "afk.ago": "for {time}",
        "bot.hi": "Hi {name}!",
        "bot.intro": "I'm the protection bot for **{server}**.\nMy prefix is `!`. Use `/help` or `!help` to see my commands.",
        "invites.new": "New invite",
        "invites.message": "{who} invited {member} and has **{total}** invites",
        "invites.unknown": "**Unknown**",
        "invites.set": "Invite messages will be sent to {channel}.",
        "invites.off": "Invite messages are off.",
        "goodbye.title": "Goodbye, {name}",
        "goodbye.body": "{name} left **{server}**.\n«We hope to see you again soon.»",
        "goodbye.members": "Members now: {n}",
        "goodbye.set": "Goodbye messages will be sent to {channel}.",
        "goodbye.off": "Goodbye messages are off.",
        "translate.need_text": "Reply to a message, or write the text after the language.",
        "translate.failed": "Could not translate. Try `eng`, `esp`, `por` or a code like `fr`.",
        "translate.not_found": "I couldn't find that message in this channel.",
        "translate.need_input": "Write a text or give a message ID.",
        "translate.footer": "Translated to {lang}",
        "close.confirm": "Are you sure you want to close this ticket?",
        "close.choose": "Choose how to close this ticket.",
        "close.cancelled": "Cancelled. This ticket stays open.",
        "close.yes": "Yes",
        "close.no": "No",
        "close.now": "Close",
        "close.with_reason": "Close with reason",
        "close.modal": "Close ticket",
        "close.reason_label": "Reason (sent to the ticket owner)",
        "idioma.set": "Language set to **{lang}**.",
    },
    "es": {
        "anime.hug.text": "{a} abraza a {b}",
        "anime.hug.solo": "{a} se abraza a sí mismo",
        "anime.hug.back": "{a} devuelve el abrazo a {b}",
        "anime.hug.noun": "abrazos",
        "anime.kiss.text": "{a} le da un beso a {b}",
        "anime.kiss.solo": "{a} se manda un beso",
        "anime.kiss.back": "{a} le devuelve el beso a {b}",
        "anime.kiss.noun": "besos",
        "anime.punch.text": "{a} le pega a {b}",
        "anime.punch.solo": "{a} se pega solo",
        "anime.punch.back": "{a} le devuelve el golpe a {b}",
        "anime.punch.noun": "golpes",
        "anime.cry.text": "{a} está llorando por culpa de {b}",
        "anime.cry.solo": "{a} está llorando",
        "anime.sleep.text": "{a} duerme junto a {b}",
        "anime.sleep.solo": "{a} se fue a dormir",
        "anime.banana.text": "{a} le regala una banana a {b}",
        "anime.banana.solo": "{a} disfruta su banana",
        "anime.banana.measure": "{a} banana: {cm}cm",
        "anime.banana.measure_for": "{b} banana: {cm}cm",
        "anime.note": "{a} y {b} tienen **{n}** {noun}",
        "anime.return": "Devolver",
        "anime.footer": "{bot} · Reacciones anime",
        "anime.only_receiver": "Solo la persona que lo recibió puede devolverlo.",
        "afk.now": "Ahora estás AFK",
        "afk.reason_default": "AFK",
        "afk.welcome_title": "Bienvenido de vuelta",
        "afk.welcome": "¡Bienvenido de vuelta {a}! Estuviste AFK por **{time}**.",
        "afk.mentions": "Te mencionaron **{n}** vez(ces).",
        "afk.jump": "Ir al mensaje",
        "afk.is_afk": "**{name}** está AFK",
        "afk.mention_title": "{name} lleva AFK {time}",
        "afk.since": "Desde",
        "afk.ago": "desde hace {time}",
        "bot.hi": "¡Hola {name}!",
        "bot.intro": "Soy el bot de protección de **{server}**.\nMi prefijo es `!`. Usa `/help` o `!help` para ver mis comandos.",
        "invites.new": "Nueva invitación",
        "invites.message": "{who} invitó a {member} y tiene **{total}** invitaciones",
        "invites.unknown": "**Desconocido**",
        "invites.set": "Los mensajes de invitación se enviarán a {channel}.",
        "invites.off": "Los mensajes de invitación están apagados.",
        "goodbye.title": "Adiós, {name}",
        "goodbye.body": "{name} salió de **{server}**.\n«Esperamos verte pronto.»",
        "goodbye.members": "Miembros ahora: {n}",
        "goodbye.set": "Los mensajes de despedida se enviarán a {channel}.",
        "goodbye.off": "Los mensajes de despedida están apagados.",
        "translate.need_text": "Responde a un mensaje o escribe el texto después del idioma.",
        "translate.failed": "No pude traducir. Prueba `eng`, `esp`, `por` o un código como `fr`.",
        "translate.not_found": "No encontré ese mensaje en este canal.",
        "translate.need_input": "Escribe un texto o da el ID de un mensaje.",
        "translate.footer": "Traducido a {lang}",
        "close.confirm": "¿Seguro que quieres cerrar este ticket?",
        "close.choose": "Elige cómo cerrar este ticket.",
        "close.cancelled": "Cancelado. Este ticket sigue abierto.",
        "close.yes": "Sí",
        "close.no": "No",
        "close.now": "Cerrar",
        "close.with_reason": "Cerrar con razón",
        "close.modal": "Cerrar ticket",
        "close.reason_label": "Razón (se envía al dueño del ticket)",
        "idioma.set": "Idioma cambiado a **{lang}**.",
    },
}


def tr(gid, key: str, **kwargs) -> str:
    lang = guild_langs.get(str(gid), "en")
    text = STRINGS.get(lang, {}).get(key) or STRINGS["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text


@bot.tree.command(name="idioma", description="Change the language the bot uses on this server.")
@app_commands.describe(language="Language for all bot messages")
@app_commands.choices(language=[
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Español", value="es"),
])
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def idioma(interaction: discord.Interaction, language: app_commands.Choice[str]):
    guild_langs[str(interaction.guild_id)] = language.value
    save_languages()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} {tr(interaction.guild_id, 'idioma.set', lang=language.name)}"), ephemeral=True
    )


load_languages()

SERVER_NAMES_FILE = DATA_DIR / "server_names.json"
server_names: dict[str, str] = {}


def load_server_names() -> None:
    global server_names
    try:
        server_names = json.loads(SERVER_NAMES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        server_names = {}


def save_server_names() -> None:
    SERVER_NAMES_FILE.write_text(json.dumps(server_names, indent=2), encoding="utf-8")


def server_name(guild: discord.Guild) -> str:
    return server_names.get(str(guild.id)) or guild.name


@bot.tree.command(name="servername", description="Set the name the bot uses for this server in its messages.")
@app_commands.describe(name="Name to show, up to 60 characters")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def servername(interaction: discord.Interaction, name: app_commands.Range[str, 1, 60]):
    server_names[str(interaction.guild_id)] = name.strip()
    save_server_names()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} The bot will call this server **{name.strip()}**."), ephemeral=True
    )


@bot.tree.command(name="servername-reset", description="Use the real Discord server name again.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def servername_reset(interaction: discord.Interaction):
    server_names.pop(str(interaction.guild_id), None)
    save_server_names()
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Server name reset."), ephemeral=True)


@bot.tree.command(name="servername-settings", description="Show the name the bot uses for this server.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def servername_settings(interaction: discord.Interaction):
    custom = str(interaction.guild_id) in server_names
    rows = [
        ("Name in messages", server_name(interaction.guild)),
        ("Real Discord name", interaction.guild.name),
        ("Custom name", "Yes" if custom else "No, using the real name"),
    ]
    await interaction.response.send_message(embed=_settings_embed("Server name settings", rows), ephemeral=True)


def _settings_embed(title: str, rows: list[tuple[str, str]]) -> discord.Embed:
    embed = base_embed(title, "Current settings for this server.", STEEL)
    for name, value in rows:
        embed.add_field(name=name, value=value[:1024], inline=False)
    return embed


def _channel_text(guild: discord.Guild, channel_id) -> str:
    if not channel_id:
        return "Off"
    channel = guild.get_channel(int(channel_id))
    return channel.mention if channel is not None else f"Missing channel (`{channel_id}`)"


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


@bot.tree.command(name="autorol-settings", description="Show the role given to new members.")
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.guild_only()
async def autorol_settings(interaction: discord.Interaction):
    role_id = autoroles.get(str(interaction.guild_id))
    role = interaction.guild.get_role(role_id) if role_id else None
    if role_id is None:
        value = "Off"
    elif role is None:
        value = f"Missing role (`{role_id}`)"
    else:
        value = role.mention
    await interaction.response.send_message(embed=_settings_embed("Auto role settings", [("Role", value)]), ephemeral=True)

@bot.tree.command(name="welcomes-on", description="Turn welcomes back on in the default welcome channel.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_on(interaction: discord.Interaction):
    welcome_config.pop(str(interaction.guild_id), None)
    save_welcomes()
    channel = interaction.guild.get_channel(DEFAULT_WELCOME_CHANNEL_ID)
    where = channel.mention if channel else f"`{DEFAULT_WELCOME_CHANNEL_ID}`"
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} Welcomes are on in {where}."), ephemeral=True
    )

@bot.tree.command(name="welcomes-off", description="Stop sending new member welcomes.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_off(interaction: discord.Interaction):
    welcome_config[str(interaction.guild_id)] = 0
    save_welcomes()
    await interaction.response.send_message(embed=notice("Welcomes are off."), ephemeral=True)

ANTIRAID_FILE = DATA_DIR / "antiraid.json"
PUNISH_ORDER = ["ban", "kick", "strip"]
PUNISH_LABELS = {"ban": "Ban", "kick": "Kick", "strip": "Remove roles"}

NUKE_RULES = {
    "channel_delete": ("Channel delete", discord.AuditLogAction.channel_delete),
    "channel_create": ("Channel create", discord.AuditLogAction.channel_create),
    "role_delete": ("Role delete", discord.AuditLogAction.role_delete),
    "role_create": ("Role create", discord.AuditLogAction.role_create),
    "ban": ("Member ban", discord.AuditLogAction.ban),
    "kick": ("Member kick", discord.AuditLogAction.kick),
    "emoji_delete": ("Emoji delete", discord.AuditLogAction.emoji_delete),
}
NUKE_DEFAULTS = {
    "channel_delete": (3, 10),
    "channel_create": (5, 10),
    "role_delete": (3, 10),
    "role_create": (5, 10),
    "ban": (3, 15),
    "kick": (3, 15),
    "emoji_delete": (3, 10),
}
PROTECTION_SECTIONS = [
    ("Overview", "overview", "Status and master switch"),
    ("Anti-nuke", "nuke", "Mass deletes, bans and kicks"),
    ("Anti-webhook", "webhook", "Block unauthorized webhooks"),
    ("Anti-raid", "raid", "Join floods and new accounts"),
    ("Trusted", "trusted", "Users and roles that skip checks"),
    ("Logs", "logs", "Where alerts are sent"),
]

DEFAULT_ANTIRAID = {
    "enabled": True,
    "log_channel": None,
    "trusted_users": [],
    "trusted_roles": [],
    "nuke": {
        key: {"enabled": True, "limit": limit, "seconds": seconds, "punish": "ban"}
        for key, (limit, seconds) in NUKE_DEFAULTS.items()
    },
    "webhook": {"enabled": True, "limit": 1, "seconds": 60, "punish": "ban"},
    "raid": {
        "join_enabled": True,
        "joins": 8,
        "seconds": 10,
        "lockdown_minutes": 10,
        "age_enabled": False,
        "min_age_days": 7,
    },
}

antiraid_config: dict[str, dict] = {}
_seen_entries: set[int] = set()
_hits: dict[tuple, deque] = {}
_joins: dict[int, deque] = {}
_raid_until: dict[int, float] = {}
_prev_verification: dict[int, discord.VerificationLevel] = {}


def _merge(defaults: dict, data: dict) -> dict:
    out = copy.deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_antiraid() -> None:
    global antiraid_config
    try:
        data = json.loads(ANTIRAID_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    antiraid_config = {gid: _merge(DEFAULT_ANTIRAID, cfg) for gid, cfg in data.items()}


def save_antiraid() -> None:
    ANTIRAID_FILE.write_text(json.dumps(antiraid_config, indent=2), encoding="utf-8")


def guild_cfg(gid: int) -> dict:
    key = str(gid)
    if key not in antiraid_config:
        antiraid_config[key] = copy.deepcopy(DEFAULT_ANTIRAID)
    return antiraid_config[key]


def _get(cfg: dict, path: tuple):
    for part in path:
        cfg = cfg[part]
    return cfg


def _set(cfg: dict, path: tuple, value) -> None:
    *head, last = path
    _get(cfg, tuple(head))[last] = value


def _trusted(guild: discord.Guild, who) -> bool:
    uid = getattr(who, "id", who)
    if uid == guild.owner_id or (bot.user and uid == bot.user.id):
        return True
    cfg = guild_cfg(guild.id)
    if uid in cfg["trusted_users"]:
        return True
    member = who if isinstance(who, discord.Member) else guild.get_member(uid)
    return member is not None and any(role.id in cfg["trusted_roles"] for role in member.roles)


async def _audit_entry(guild: discord.Guild, action, target_id: int | None = None, max_age: int = 20):
    try:
        async for entry in guild.audit_logs(limit=25, action=action):
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > max_age:
                break
            if target_id is not None and getattr(entry.target, "id", None) != target_id:
                continue
            if entry.id in _seen_entries:
                continue
            if len(_seen_entries) > 5000:
                _seen_entries.clear()
            _seen_entries.add(entry.id)
            return entry
    except discord.Forbidden:
        print("[antiraid] missing View Audit Log permission")
    except discord.HTTPException as exc:
        print(f"[antiraid] audit log error: {exc}")
    return None


async def _alarm(guild: discord.Guild, title: str, lines: list[str], color: int = ERROR) -> None:
    channel_id = guild_cfg(guild.id)["log_channel"]
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return
    try:
        await channel.send(embed=base_embed(title, "\n".join(lines), color), allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[antiraid] could not post alert: {exc}")


async def _punish(guild: discord.Guild, user_id: int, how: str, reason: str) -> str:
    if user_id == guild.owner_id or (bot.user and user_id == bot.user.id):
        return "skipped"
    member = guild.get_member(user_id)
    if member is None and how != "ban":
        return "not in the server"
    if member is not None and member.top_role >= guild.me.top_role:
        return "role is too high for me"
    try:
        if how == "ban":
            await guild.ban(member or discord.Object(id=user_id), reason=reason, delete_message_days=0)
        elif how == "kick":
            await member.kick(reason=reason)
        else:
            roles = [r for r in member.roles if not r.is_default() and not r.managed and r < guild.me.top_role]
            if not roles:
                return "no roles to remove"
            await member.remove_roles(*roles, reason=reason)
    except discord.HTTPException as exc:
        return f"failed: {exc.text or exc}"
    return "done"


async def _record_hit(guild: discord.Guild, label: str, rule: dict, executor) -> None:
    if executor is None or _trusted(guild, executor):
        return
    key = (guild.id, executor.id, label)
    times = _hits.setdefault(key, deque())
    now = time.monotonic()
    times.append(now)
    while times and now - times[0] > rule["seconds"]:
        times.popleft()
    if len(times) < rule["limit"]:
        return
    times.clear()
    result = await _punish(guild, executor.id, rule["punish"], f"Anti-nuke: {label}")
    await _alarm(
        guild,
        f"{E('Error', '⚠️')} Anti-nuke triggered",
        [
            f"**Action:** {label}",
            f"**User:** {executor.mention} (`{executor.id}`)",
            f"**Limit:** {rule['limit']} in {rule['seconds']}s",
            f"**Punishment:** {PUNISH_LABELS[rule['punish']]} · {result}",
        ],
    )


async def _nuke_event(guild: discord.Guild, key: str, target_id: int | None = None) -> None:
    cfg = guild_cfg(guild.id)
    rule = cfg["nuke"][key]
    if not cfg["enabled"] or not rule["enabled"]:
        return
    label, action = NUKE_RULES[key]
    entry = await _audit_entry(guild, action, target_id)
    if entry is not None:
        await _record_hit(guild, label, rule, entry.user)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await _nuke_event(channel.guild, "channel_delete", channel.id)


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    await _nuke_event(channel.guild, "channel_create", channel.id)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    await _nuke_event(role.guild, "role_delete", role.id)


@bot.event
async def on_guild_role_create(role: discord.Role):
    await _nuke_event(role.guild, "role_create", role.id)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await _log_ban(guild, user)
    await _nuke_event(guild, "ban", user.id)


@bot.event
async def on_member_remove(member: discord.Member):
    await _log_kick(member)
    await _nuke_event(member.guild, "kick", member.id)


@bot.event
async def on_guild_emojis_update(guild: discord.Guild, before, after):
    kept = {e.id for e in after}
    for emoji in before:
        if emoji.id not in kept:
            await _nuke_event(guild, "emoji_delete", emoji.id)


@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel):
    guild = channel.guild
    cfg = guild_cfg(guild.id)
    if not cfg["enabled"] or not cfg["webhook"]["enabled"]:
        return
    entry = await _audit_entry(guild, discord.AuditLogAction.webhook_create)
    if entry is None or entry.user is None or _trusted(guild, entry.user):
        return
    hook_id = getattr(entry.target, "id", None)
    if hook_id:
        try:
            hook = await bot.fetch_webhook(hook_id)
            await hook.delete(reason="Anti-webhook: unauthorized webhook")
        except discord.HTTPException:
            pass
    await _alarm(
        guild,
        f"{E('GE_Lock', '🔒')} Webhook blocked",
        [f"**Channel:** {channel.mention}", f"**Created by:** {entry.user.mention} (`{entry.user.id}`)"],
    )
    await _record_hit(guild, "Webhook created", cfg["webhook"], entry.user)


async def _kick_join(member: discord.Member, reason: str) -> None:
    try:
        await member.kick(reason=reason)
    except discord.HTTPException:
        pass


async def _end_lockdown(guild: discord.Guild, seconds: float) -> None:
    await asyncio.sleep(seconds)
    if _raid_until.get(guild.id, 0) > time.time():
        return
    _raid_until.pop(guild.id, None)
    previous = _prev_verification.pop(guild.id, None)
    if previous is not None:
        try:
            await guild.edit(verification_level=previous, reason="Anti-raid lockdown ended")
        except discord.HTTPException:
            pass
    await _alarm(guild, f"{E('true', '✅')} Lockdown ended", ["Verification level was restored."], STEEL)


async def _antiraid_join(member: discord.Member) -> bool:
    guild = member.guild
    cfg = guild_cfg(guild.id)
    if not cfg["enabled"]:
        return False
    raid = cfg["raid"]
    now = time.time()

    if raid["age_enabled"] and (discord.utils.utcnow() - member.created_at).days < raid["min_age_days"]:
        await _kick_join(member, "Anti-raid: account too new")
        return True

    if _raid_until.get(guild.id, 0) > now:
        await _kick_join(member, "Anti-raid lockdown")
        return True

    if not raid["join_enabled"]:
        return False
    times = _joins.setdefault(guild.id, deque())
    times.append(now)
    while times and now - times[0] > raid["seconds"]:
        times.popleft()
    if len(times) < raid["joins"]:
        return False

    times.clear()
    minutes = raid["lockdown_minutes"]
    _raid_until[guild.id] = now + minutes * 60
    if guild.id not in _prev_verification:
        _prev_verification[guild.id] = guild.verification_level
    try:
        await guild.edit(verification_level=discord.VerificationLevel.highest, reason="Anti-raid lockdown")
    except discord.HTTPException:
        pass
    asyncio.create_task(_end_lockdown(guild, minutes * 60))
    await _alarm(
        guild,
        f"{E('warn3', '⚠️')} Raid detected",
        [
            f"**Joins:** {raid['joins']} in {raid['seconds']}s",
            f"**Lockdown:** {minutes} min · verification set to highest",
            "New joins are kicked until the lockdown ends.",
        ],
    )
    await _kick_join(member, "Anti-raid lockdown")
    return True


def _guard(guild: discord.Guild, fn):
    async def callback(interaction: discord.Interaction):
        if interaction.user.id != guild.owner_id:
            return await interaction.response.send_message(
                embed=error_notice("Only the server owner can change protection settings."), ephemeral=True
            )
        await fn(interaction)
    return callback


def _button(guild: discord.Guild, label: str, emoji: str, style: discord.ButtonStyle, fn) -> discord.ui.Button:
    button = discord.ui.Button(label=label, emoji=emoji, style=style)
    button.callback = _guard(guild, fn)
    return button


def _toggle_action(guild: discord.Guild, path: tuple, section: str, rule_key: str = "channel_delete"):
    async def fn(interaction: discord.Interaction):
        cfg = guild_cfg(guild.id)
        _set(cfg, path, not _get(cfg, path))
        save_antiraid()
        await interaction.response.edit_message(view=build_protection_layout(guild, section, rule_key))
    return fn


def _cycle_action(guild: discord.Guild, path: tuple, section: str, rule_key: str = "channel_delete"):
    async def fn(interaction: discord.Interaction):
        cfg = guild_cfg(guild.id)
        current = _get(cfg, path)
        _set(cfg, path, PUNISH_ORDER[(PUNISH_ORDER.index(current) + 1) % len(PUNISH_ORDER)])
        save_antiraid()
        await interaction.response.edit_message(view=build_protection_layout(guild, section, rule_key))
    return fn


def _modal_action(guild: discord.Guild, title: str, fields: list, section: str, rule_key: str = "channel_delete"):
    async def fn(interaction: discord.Interaction):
        await interaction.response.send_modal(NumbersModal(guild, title, fields, section, rule_key))
    return fn


def _picker_action(guild: discord.Guild, kind: str, mode: str):
    async def fn(interaction: discord.Interaction):
        verb = "Pick the members" if kind == "user" else "Pick the roles"
        verb += " to trust." if mode == "add" else " to stop trusting."
        await interaction.response.send_message(
            embed=notice(verb), view=TrustPicker(guild, kind, mode), ephemeral=True
        )
    return fn


class NumbersModal(discord.ui.Modal):
    def __init__(self, guild: discord.Guild, title: str, fields: list, section: str, rule_key: str):
        super().__init__(title=title[:45], timeout=300)
        self.guild = guild
        self.fields = fields
        self.section = section
        self.rule_key = rule_key
        cfg = guild_cfg(guild.id)
        self.inputs: list[discord.ui.TextInput] = []
        for label, path, _lo, _hi in fields:
            text_input = discord.ui.TextInput(label=label[:45], default=str(_get(cfg, path)), max_length=6)
            self.add_item(text_input)
            self.inputs.append(text_input)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.guild.owner_id:
            return await interaction.response.send_message(
                embed=error_notice("Only the server owner can change protection settings."), ephemeral=True
            )
        values = []
        for (label, path, low, high), text_input in zip(self.fields, self.inputs):
            try:
                value = int(text_input.value.strip())
            except ValueError:
                return await interaction.response.send_message(
                    embed=error_notice(f"**{label}** must be a number."), ephemeral=True
                )
            if not low <= value <= high:
                return await interaction.response.send_message(
                    embed=error_notice(f"**{label}** must be between {low} and {high}."), ephemeral=True
                )
            values.append((path, value))
        cfg = guild_cfg(self.guild.id)
        for path, value in values:
            _set(cfg, path, value)
        save_antiraid()
        await interaction.response.send_message(
            view=build_protection_layout(self.guild, self.section, self.rule_key), ephemeral=True
        )


class TrustPicker(discord.ui.View):
    def __init__(self, guild: discord.Guild, kind: str, mode: str):
        super().__init__(timeout=180)
        self.guild = guild
        self.kind = kind
        self.mode = mode
        if kind == "user":
            self.picker = discord.ui.UserSelect(placeholder="Choose members…", min_values=1, max_values=10)
        else:
            self.picker = discord.ui.RoleSelect(placeholder="Choose roles…", min_values=1, max_values=10)
        self.picker.callback = _guard(guild, self._pick)
        self.add_item(self.picker)

    async def _pick(self, interaction: discord.Interaction):
        cfg = guild_cfg(self.guild.id)
        key = "trusted_users" if self.kind == "user" else "trusted_roles"
        ids = cfg[key]
        for item in self.picker.values:
            if self.mode == "add" and item.id not in ids:
                ids.append(item.id)
            elif self.mode == "remove" and item.id in ids:
                ids.remove(item.id)
        save_antiraid()
        await interaction.response.edit_message(
            embed=notice(f"{E('true', '✅')} Trusted list updated."), view=None
        )


def _status(flag: bool) -> str:
    return E("true", "✅") if flag else E("false", "❌")


def _overview_section(guild, cfg, rule_key):
    raid = cfg["raid"]
    nuke_on = sum(1 for r in cfg["nuke"].values() if r["enabled"])
    log = f"<#{cfg['log_channel']}>" if cfg["log_channel"] else "Not set"
    text = (
        f"{_status(cfg['enabled'])} **Protection** · {'Active' if cfg['enabled'] else 'Paused'}\n\n"
        f"{E('Error', '⚠️')} **Anti-nuke** · {nuke_on} of {len(NUKE_RULES)} rules on\n"
        f"{E('GE_Lock', '🔒')} **Anti-webhook** · {'On' if cfg['webhook']['enabled'] else 'Off'}\n"
        f"{E('warn3', '⚠️')} **Anti-raid** · joins {'on' if raid['join_enabled'] else 'off'} · "
        f"new accounts {'on' if raid['age_enabled'] else 'off'}\n"
        f"{E('Estrella', '⭐')} **Trusted** · {len(cfg['trusted_users'])} users · {len(cfg['trusted_roles'])} roles\n"
        f"{E('support', '📝')} **Logs** · {log}"
    )
    rows = [discord.ui.ActionRow(_button(
        guild, "Protection on" if cfg["enabled"] else "Protection off", E("synexprotect", "🛡️"),
        discord.ButtonStyle.success if cfg["enabled"] else discord.ButtonStyle.danger,
        _toggle_action(guild, ("enabled",), "overview"),
    ))]
    return text, rows


def _nuke_section(guild, cfg, rule_key):
    lines = [
        f"{_status(rule['enabled'])} **{label}** · {rule['limit']} in {rule['seconds']}s · {PUNISH_LABELS[rule['punish']]}"
        for key, (label, _action) in NUKE_RULES.items()
        for rule in [cfg["nuke"][key]]
    ]
    text = (
        "Each rule counts actions per person. When someone goes over the limit inside the time window, "
        "the punishment is applied.\n\n" + "\n".join(lines)
    )

    async def pick(interaction: discord.Interaction):
        await interaction.response.edit_message(view=build_protection_layout(guild, "nuke", select.values[0]))

    select = discord.ui.Select(
        placeholder="Choose a rule…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=label, value=key, default=key == rule_key)
            for key, (label, _action) in NUKE_RULES.items()
        ],
    )
    select.callback = _guard(guild, pick)

    rule = cfg["nuke"][rule_key]
    path = ("nuke", rule_key)
    rows = [
        discord.ui.ActionRow(select),
        discord.ui.ActionRow(
            _button(guild, "Rule on" if rule["enabled"] else "Rule off", E("synexprotect", "🛡️"),
                    discord.ButtonStyle.success if rule["enabled"] else discord.ButtonStyle.secondary,
                    _toggle_action(guild, path + ("enabled",), "nuke", rule_key)),
            _button(guild, "Edit limits", E("support", "✏️"), discord.ButtonStyle.secondary,
                    _modal_action(guild, f"{NUKE_RULES[rule_key][0]} limits", [
                        ("Actions allowed", path + ("limit",), 1, 50),
                        ("Within seconds", path + ("seconds",), 1, 3600),
                    ], "nuke", rule_key)),
            _button(guild, f"Punish: {PUNISH_LABELS[rule['punish']]}", E("Error", "⚠️"),
                    discord.ButtonStyle.secondary, _cycle_action(guild, path + ("punish",), "nuke", rule_key)),
        ),
    ]
    return text, rows


def _webhook_section(guild, cfg, rule_key):
    hook = cfg["webhook"]
    text = (
        f"{_status(hook['enabled'])} **Block webhook creation** · punishment: {PUNISH_LABELS[hook['punish']]}\n\n"
        "Any webhook created by someone who is not trusted is deleted right away, and the creator gets the "
        "punishment below. Trusted members and roles can still create webhooks."
    )
    rows = [discord.ui.ActionRow(
        _button(guild, "Webhook on" if hook["enabled"] else "Webhook off", E("GE_Lock", "🔒"),
                discord.ButtonStyle.success if hook["enabled"] else discord.ButtonStyle.secondary,
                _toggle_action(guild, ("webhook", "enabled"), "webhook")),
        _button(guild, f"Punish: {PUNISH_LABELS[hook['punish']]}", E("Error", "⚠️"),
                discord.ButtonStyle.secondary, _cycle_action(guild, ("webhook", "punish"), "webhook")),
    )]
    return text, rows


def _raid_section(guild, cfg, rule_key):
    raid = cfg["raid"]
    text = (
        f"{_status(raid['join_enabled'])} **Join flood** · {raid['joins']} joins in {raid['seconds']}s\n"
        f"-# When it happens: verification goes to highest for {raid['lockdown_minutes']} min and new joins are kicked.\n\n"
        f"{_status(raid['age_enabled'])} **New accounts** · kick accounts younger than {raid['min_age_days']} days"
    )
    rows = [
        discord.ui.ActionRow(
            _button(guild, "Join flood on" if raid["join_enabled"] else "Join flood off", E("warn3", "⚠️"),
                    discord.ButtonStyle.success if raid["join_enabled"] else discord.ButtonStyle.secondary,
                    _toggle_action(guild, ("raid", "join_enabled"), "raid")),
            _button(guild, "Edit flood limits", E("support", "✏️"), discord.ButtonStyle.secondary,
                    _modal_action(guild, "Join flood limits", [
                        ("Joins allowed", ("raid", "joins"), 2, 100),
                        ("Within seconds", ("raid", "seconds"), 1, 600),
                        ("Lockdown minutes", ("raid", "lockdown_minutes"), 1, 1440),
                    ], "raid")),
        ),
        discord.ui.ActionRow(
            _button(guild, "New accounts on" if raid["age_enabled"] else "New accounts off", E("GE_member", "👤"),
                    discord.ButtonStyle.success if raid["age_enabled"] else discord.ButtonStyle.secondary,
                    _toggle_action(guild, ("raid", "age_enabled"), "raid")),
            _button(guild, "Edit account age", E("support", "✏️"), discord.ButtonStyle.secondary,
                    _modal_action(guild, "New account filter", [
                        ("Minimum account age (days)", ("raid", "min_age_days"), 1, 365),
                    ], "raid")),
        ),
    ]
    return text, rows


def _trusted_section(guild, cfg, rule_key):
    users = cfg["trusted_users"]
    roles = cfg["trusted_roles"]
    user_text = " ".join(f"<@{u}>" for u in users[:20]) or "None"
    if len(users) > 20:
        user_text += f" +{len(users) - 20} more"
    role_text = " ".join(f"<@&{r}>" for r in roles[:20]) or "None"
    if len(roles) > 20:
        role_text += f" +{len(roles) - 20} more"
    text = (
        "Trusted members and roles skip every check. The server owner is always trusted.\n\n"
        f"**Members** · {user_text}\n**Roles** · {role_text}"
    )
    rows = [discord.ui.ActionRow(
        _button(guild, "Add member", E("true", "✅"), discord.ButtonStyle.success, _picker_action(guild, "user", "add")),
        _button(guild, "Remove member", E("false", "❌"), discord.ButtonStyle.danger, _picker_action(guild, "user", "remove")),
        _button(guild, "Add role", E("true", "✅"), discord.ButtonStyle.success, _picker_action(guild, "role", "add")),
        _button(guild, "Remove role", E("false", "❌"), discord.ButtonStyle.danger, _picker_action(guild, "role", "remove")),
    )]
    return text, rows


def _logs_section(guild, cfg, rule_key):
    channel = f"<#{cfg['log_channel']}>" if cfg["log_channel"] else "Not set"
    text = f"Anti-nuke, anti-webhook and anti-raid alerts are posted here.\n\n**Channel** · {channel}"

    async def pick(interaction: discord.Interaction):
        guild_cfg(guild.id)["log_channel"] = select.values[0].id
        save_antiraid()
        await interaction.response.edit_message(view=build_protection_layout(guild, "logs"))

    async def clear(interaction: discord.Interaction):
        guild_cfg(guild.id)["log_channel"] = None
        save_antiraid()
        await interaction.response.edit_message(view=build_protection_layout(guild, "logs"))

    select = discord.ui.ChannelSelect(
        channel_types=[discord.ChannelType.text],
        placeholder="Choose the alerts channel…",
        min_values=1,
        max_values=1,
    )
    select.callback = _guard(guild, pick)
    rows = [
        discord.ui.ActionRow(select),
        discord.ui.ActionRow(_button(guild, "Clear channel", E("false", "❌"), discord.ButtonStyle.danger, clear)),
    ]
    return text, rows


SECTION_BUILDERS = {
    "overview": _overview_section,
    "nuke": _nuke_section,
    "webhook": _webhook_section,
    "raid": _raid_section,
    "trusted": _trusted_section,
    "logs": _logs_section,
}


def build_protection_layout(guild: discord.Guild, section: str = "overview", rule_key: str = "channel_delete") -> discord.ui.LayoutView:
    cfg = guild_cfg(guild.id)

    nav = discord.ui.Select(
        placeholder="Choose a module…",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label=label, value=value, description=desc, default=value == section)
            for label, value, desc in PROTECTION_SECTIONS
        ],
    )

    async def go(interaction: discord.Interaction):
        await interaction.response.edit_message(view=build_protection_layout(guild, nav.values[0]))

    nav.callback = _guard(guild, go)

    body, rows = SECTION_BUILDERS.get(section, _overview_section)(guild, cfg, rule_key)
    children = [
        discord.ui.TextDisplay(f"### Protection Panel\n-# {guild.name} · Owner only"),
        discord.ui.Separator(),
        discord.ui.ActionRow(nav),
        discord.ui.Separator(),
        discord.ui.TextDisplay(body),
        *rows,
        discord.ui.TextDisplay("-# Changes apply right away"),
    ]
    view = discord.ui.LayoutView(timeout=900)
    view.add_item(discord.ui.Container(*children, accent_colour=CHARCOAL))
    return view


@bot.tree.command(name="antiraid", description="Open the anti-raid and protection panel. Server owner only.")
@app_commands.guild_only()
async def antiraid_cmd(interaction: discord.Interaction):
    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message(
            embed=error_notice("Only the server owner can open the protection panel."), ephemeral=True
        )
    await interaction.response.send_message(view=build_protection_layout(interaction.guild), ephemeral=True)


MODLOG_FILE = DATA_DIR / "modlog.json"
MODLOG_EVENTS = {
    "ban": "Bans",
    "unban": "Unbans",
    "kick": "Kicks",
    "mute": "Mutes (timeouts)",
    "unmute": "Unmutes",
    "invite_create": "Invite created",
    "invite_delete": "Invite deleted",
    "invite_join": "Member joined by invite",
    "voice": "Voice join, leave and move",
    "message_delete": "Messages deleted",
    "message_edit": "Messages edited",
    "photo": "Photos deleted (with image)",
    "emoji": "Emojis created, deleted or renamed",
    "sticker": "Stickers created, deleted or renamed",
}
MAX_TIMEOUT_SECONDS = 28 * 86400

modlog_config: dict[str, dict] = {}
_invite_cache: dict[int, dict[str, int]] = {}


def load_modlog() -> None:
    global modlog_config
    try:
        modlog_config = json.loads(MODLOG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        modlog_config = {}


def save_modlog() -> None:
    MODLOG_FILE.write_text(json.dumps(modlog_config, indent=2), encoding="utf-8")


def modlog_cfg(gid: int) -> dict:
    cfg = modlog_config.setdefault(str(gid), {"channel": None, "events": {}})
    for event in MODLOG_EVENTS:
        cfg["events"].setdefault(event, True)
    return cfg


def _event_on(guild: discord.Guild, event: str) -> bool:
    cfg = modlog_cfg(guild.id)
    return bool(cfg["channel"]) and cfg["events"].get(event, True)


def _chan(channel) -> str:
    return f"<#{channel.id}>" if channel else "Unknown"


def _who(target) -> str:
    if isinstance(target, (discord.Member, discord.User)):
        return f"{target.mention} · `{target.id}`"
    return f"`{target.id}`"


def _avatar_url(target) -> str | None:
    if isinstance(target, (discord.Member, discord.User)):
        return target.display_avatar.url
    if target is not None and getattr(target, "id", None):
        user = bot.get_user(target.id)
        return user.display_avatar.url if user else None
    return None


MODLOG_ICONS = {
    "Member banned": ("Error", "⚠️"),
    "Member unbanned": ("true", "✅"),
    "Member kicked": ("warn3", "⚠️"),
    "Member muted": ("GE_Lock", "🔒"),
    "Member unmuted": ("true", "✅"),
    "Invite created": ("community", "🔗"),
    "Invite deleted": ("false", "❌"),
    "Member joined by invite": ("GE_member", "👤"),
    "Joined voice": ("community", "🔊"),
    "Left voice": ("false", "❌"),
    "Moved voice": ("transfer", "🔁"),
    "Message deleted": ("false", "🗑️"),
    "Message edited": ("transfer", "✏️"),
    "Photo deleted": ("false", "🗑️"),
    "Emoji created": ("true", "✅"),
    "Emoji deleted": ("false", "❌"),
    "Emoji renamed": ("transfer", "🔁"),
    "Sticker created": ("true", "✅"),
    "Sticker deleted": ("false", "❌"),
    "Sticker renamed": ("transfer", "🔁"),
}


def _action_card(title: str, color: int, target, fields: list[tuple[str, str]], media: list[str] | None = None) -> discord.ui.LayoutView:
    icon_name, icon_fallback = MODLOG_ICONS.get(title, ("synexprotect", "🛡️"))
    title = f"{E(icon_name, icon_fallback)} {title}"
    details = "\n\n".join(f"**{name}**\n{value or 'None'}" for name, value in fields)
    stamp = discord.utils.format_dt(discord.utils.utcnow(), "f")
    avatar = _avatar_url(target)
    head_text = discord.ui.TextDisplay(f"### {title}\n-# {_who(target) if target else 'SynexProtect'}")
    head = (discord.ui.Section(head_text, accessory=discord.ui.Thumbnail(avatar)) if avatar else head_text)
    children = [head, discord.ui.Separator(), discord.ui.TextDisplay(details)]
    if media:
        children += [discord.ui.Separator(), discord.ui.MediaGallery(*[discord.MediaGalleryItem(u) for u in media[:10]])]
    children += [discord.ui.Separator(), discord.ui.TextDisplay(f"-# {BOT_NAME} · Moderation · {stamp}")]
    container = discord.ui.Container(*children, accent_colour=color)
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(container)
    return view


async def _modlog(guild: discord.Guild, event: str, title: str, color: int, target, fields: list[tuple[str, str]]) -> None:
    if not _event_on(guild, event):
        return
    channel = guild.get_channel(modlog_cfg(guild.id)["channel"])
    if channel is None:
        return
    try:
        await channel.send(view=_action_card(title, color, target, fields),
                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[modlog] could not post: {exc}")


async def _audit_peek(guild: discord.Guild, action, target_id: int | None = None, max_age: int = 20):
    try:
        async for entry in guild.audit_logs(limit=25, action=action):
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > max_age:
                break
            if target_id is not None and getattr(entry.target, "id", None) != target_id:
                continue
            return entry
    except discord.HTTPException:
        pass
    return None


def _hierarchy_error(guild: discord.Guild, moderator: discord.Member, target: discord.Member) -> str | None:
    if target.id == moderator.id:
        return "You can't use this on yourself."
    if target.id == guild.owner_id:
        return "I can't moderate the server owner."
    if moderator.id != guild.owner_id and target.top_role >= moderator.top_role:
        return "Their highest role is equal to or above yours."
    if target.top_role >= guild.me.top_role:
        return "My highest role is below theirs. Move my role higher in Server Settings."
    return None


def _reason(moderator: discord.Member, reason: str) -> str:
    return f"{moderator} ({moderator.id}): {reason}"[:500]


async def mod_ban(guild, moderator, target, reason: str, delete_days: int = 0):
    if isinstance(target, discord.Member):
        error = _hierarchy_error(guild, moderator, target)
        if error:
            return False, error
    try:
        await guild.ban(target, reason=_reason(moderator, reason), delete_message_days=delete_days)
    except discord.HTTPException as exc:
        return False, f"I couldn't ban that user: {exc.text or exc}"
    fields = [("Member", _who(target)), ("Moderator", moderator.mention), ("Reason", reason),
              ("Messages deleted", f"{delete_days} day(s)")]
    await _modlog(guild, "ban", "Member banned", ERROR, target, fields)
    return True, ("Member banned", ERROR, target, fields)


async def mod_unban(guild, moderator, user_id: int, reason: str):
    try:
        user = await bot.fetch_user(user_id)
    except discord.HTTPException:
        return False, "That user ID doesn't exist."
    try:
        await guild.unban(discord.Object(id=user_id), reason=_reason(moderator, reason))
    except discord.NotFound:
        return False, "That user isn't banned."
    except discord.HTTPException as exc:
        return False, f"I couldn't unban them: {exc.text or exc}"
    fields = [("Member", _who(user)), ("Moderator", moderator.mention), ("Reason", reason)]
    await _modlog(guild, "unban", "Member unbanned", CHARCOAL, user, fields)
    return True, ("Member unbanned", CHARCOAL, user, fields)


async def mod_kick(guild, moderator, member: discord.Member, reason: str):
    error = _hierarchy_error(guild, moderator, member)
    if error:
        return False, error
    try:
        await member.kick(reason=_reason(moderator, reason))
    except discord.HTTPException as exc:
        return False, f"I couldn't kick them: {exc.text or exc}"
    fields = [("Member", _who(member)), ("Moderator", moderator.mention), ("Reason", reason)]
    await _modlog(guild, "kick", "Member kicked", ERROR, member, fields)
    return True, ("Member kicked", ERROR, member, fields)


async def mod_mute(guild, moderator, member: discord.Member, seconds: int, reason: str):
    error = _hierarchy_error(guild, moderator, member)
    if error:
        return False, error
    if not 5 <= seconds <= MAX_TIMEOUT_SECONDS:
        return False, "The mute must be between 5 seconds and 28 days."
    until = discord.utils.utcnow() + timedelta(seconds=seconds)
    try:
        await member.timeout(until, reason=_reason(moderator, reason))
    except discord.HTTPException as exc:
        return False, f"I couldn't mute them: {exc.text or exc}"
    fields = [("Member", _who(member)), ("Moderator", moderator.mention), ("Duration", fmt_seconds(seconds)),
              ("Until", discord.utils.format_dt(until, "f")), ("Reason", reason)]
    await _modlog(guild, "mute", "Member muted", STEEL, member, fields)
    return True, ("Member muted", STEEL, member, fields)


async def mod_unmute(guild, moderator, member: discord.Member, reason: str):
    if not member.is_timed_out():
        return False, f"{member.mention} isn't muted."
    try:
        await member.timeout(None, reason=_reason(moderator, reason))
    except discord.HTTPException as exc:
        return False, f"I couldn't unmute them: {exc.text or exc}"
    fields = [("Member", _who(member)), ("Moderator", moderator.mention), ("Reason", reason)]
    await _modlog(guild, "unmute", "Member unmuted", CHARCOAL, member, fields)
    return True, ("Member unmuted", CHARCOAL, member, fields)


async def _reply_slash(interaction: discord.Interaction, ok: bool, payload) -> None:
    if ok:
        await interaction.response.send_message(view=_action_card(*payload))
    else:
        await interaction.response.send_message(embed=error_notice(payload), ephemeral=True)


async def _reply_prefix(ctx: commands.Context, ok: bool, payload) -> None:
    if ok:
        await ctx.send(view=_action_card(*payload), allowed_mentions=discord.AllowedMentions.none())
    else:
        await ctx.send(embed=error_notice(payload), delete_after=12)


@bot.tree.command(name="ban", description="Ban a member from the server.")
@app_commands.describe(member="The member to ban", reason="Why", delete_days="Days of their messages to delete (0-7)")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.guild_only()
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given",
                  delete_days: app_commands.Range[int, 0, 7] = 0):
    ok, payload = await mod_ban(interaction.guild, interaction.user, member, reason, delete_days)
    await _reply_slash(interaction, ok, payload)


@bot.command(name="ban")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def ban_prefix(ctx: commands.Context, user: discord.User, *, reason: str = "No reason given"):
    member = ctx.guild.get_member(user.id)
    ok, payload = await mod_ban(ctx.guild, ctx.author, member or user, reason)
    await _reply_prefix(ctx, ok, payload)


@bot.tree.command(name="unban", description="Unban a user by their ID.")
@app_commands.describe(user_id="The user's ID", reason="Why")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.guild_only()
async def unban_cmd(interaction: discord.Interaction, user_id: str, reason: str = "No reason given"):
    try:
        uid = int(user_id.strip())
    except ValueError:
        return await interaction.response.send_message(embed=error_notice("Invalid user ID."), ephemeral=True)
    ok, payload = await mod_unban(interaction.guild, interaction.user, uid, reason)
    await _reply_slash(interaction, ok, payload)


@bot.command(name="unban")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def unban_prefix(ctx: commands.Context, user_id: int, *, reason: str = "No reason given"):
    ok, payload = await mod_unban(ctx.guild, ctx.author, user_id, reason)
    await _reply_prefix(ctx, ok, payload)


@bot.tree.command(name="kick", description="Kick a member from the server.")
@app_commands.describe(member="The member to kick", reason="Why")
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    ok, payload = await mod_kick(interaction.guild, interaction.user, member, reason)
    await _reply_slash(interaction, ok, payload)


@bot.command(name="kick")
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def kick_prefix(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason given"):
    ok, payload = await mod_kick(ctx.guild, ctx.author, member, reason)
    await _reply_prefix(ctx, ok, payload)


@bot.tree.command(name="mute", description="Mute (timeout) a member for a set time.")
@app_commands.describe(member="The member to mute", duration="e.g. 10m, 2h, 1d (max 28d)", reason="Why")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def mute_cmd(interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason given"):
    seconds = parse_duration(duration)
    if seconds is None:
        return await interaction.response.send_message(embed=error_notice("Use a time like `10m`, `2h` or `1d`."), ephemeral=True)
    ok, payload = await mod_mute(interaction.guild, interaction.user, member, seconds, reason)
    await _reply_slash(interaction, ok, payload)


@bot.command(name="mute")
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def mute_prefix(ctx: commands.Context, member: discord.Member, duration: str, *, reason: str = "No reason given"):
    seconds = parse_duration(duration)
    if seconds is None:
        return await ctx.send(embed=error_notice("Use a time like `10m`, `2h` or `1d`."), delete_after=12)
    ok, payload = await mod_mute(ctx.guild, ctx.author, member, seconds, reason)
    await _reply_prefix(ctx, ok, payload)


@bot.tree.command(name="unmute", description="Remove a member's mute (timeout).")
@app_commands.describe(member="The member to unmute", reason="Why")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def unmute_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason given"):
    ok, payload = await mod_unmute(interaction.guild, interaction.user, member, reason)
    await _reply_slash(interaction, ok, payload)


@bot.command(name="unmute")
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def unmute_prefix(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason given"):
    ok, payload = await mod_unmute(ctx.guild, ctx.author, member, reason)
    await _reply_prefix(ctx, ok, payload)


class ModlogEventsSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild):
        self.guild_id = guild.id
        cfg = modlog_cfg(guild.id)
        super().__init__(
            placeholder="Choose what gets logged…",
            min_values=0,
            max_values=len(MODLOG_EVENTS),
            options=[
                discord.SelectOption(label=label, value=key, default=cfg["events"].get(key, True))
                for key, label in MODLOG_EVENTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(embed=error_notice("You need Manage Server for this."), ephemeral=True)
        cfg = modlog_cfg(self.guild_id)
        for key in MODLOG_EVENTS:
            cfg["events"][key] = key in self.values
        save_modlog()
        await interaction.response.edit_message(embed=notice(f"{E('true', '✅')} Log events updated."), view=None)


@bot.tree.command(name="modlog-setup", description="Send moderation, invite and voice logs to this channel.")
@app_commands.describe(channel="The channel for the logs")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def modlog_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    modlog_cfg(interaction.guild_id)["channel"] = channel.id
    save_modlog()
    await _refresh_invites(interaction.guild)
    await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Logs will be sent in {channel.mention}."), ephemeral=True)


@bot.tree.command(name="modlog-off", description="Stop sending logs.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def modlog_off(interaction: discord.Interaction):
    modlog_cfg(interaction.guild_id)["channel"] = None
    save_modlog()
    await interaction.response.send_message(embed=notice("Logs are off."), ephemeral=True)


@bot.tree.command(name="modlog-events", description="Choose which events are logged.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def modlog_events(interaction: discord.Interaction):
    view = discord.ui.View(timeout=300)
    view.add_item(ModlogEventsSelect(interaction.guild))
    await interaction.response.send_message(
        embed=notice("Pick the events to log. Unselected events are turned off."), view=view, ephemeral=True
    )


@bot.tree.command(name="modlog-settings", description="Show the current log channel and logged events.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def modlog_settings(interaction: discord.Interaction):
    cfg = modlog_cfg(interaction.guild_id)
    active = [e for e in MODLOG_EVENTS if cfg["events"].get(e, True)]
    rows = [
        ("Channel", _channel_text(interaction.guild, cfg["channel"])),
        ("Events on", f"{len(active)}/{len(MODLOG_EVENTS)}"),
        ("Events", ", ".join(f"`{e}`" for e in active) or "None"),
    ]
    await interaction.response.send_message(embed=_settings_embed("Log settings", rows), ephemeral=True)


async def _log_ban(guild: discord.Guild, user: discord.User) -> None:
    if not _event_on(guild, "ban"):
        return
    entry = await _audit_peek(guild, discord.AuditLogAction.ban, user.id)
    if entry is not None and entry.user is not None and entry.user.id == bot.user.id:
        return
    fields = [("Member", _who(user)), ("Moderator", entry.user.mention if entry and entry.user else "Unknown"),
              ("Reason", entry.reason if entry and entry.reason else "None")]
    await _modlog(guild, "ban", "Member banned", ERROR, user, fields)


async def _log_unban(guild: discord.Guild, user: discord.User) -> None:
    if not _event_on(guild, "unban"):
        return
    entry = await _audit_peek(guild, discord.AuditLogAction.unban, user.id)
    if entry is not None and entry.user is not None and entry.user.id == bot.user.id:
        return
    fields = [("Member", _who(user)), ("Moderator", entry.user.mention if entry and entry.user else "Unknown")]
    await _modlog(guild, "unban", "Member unbanned", CHARCOAL, user, fields)


async def _log_kick(member: discord.Member) -> None:
    if not _event_on(member.guild, "kick"):
        return
    entry = await _audit_peek(member.guild, discord.AuditLogAction.kick, member.id)
    if entry is None or (entry.user is not None and entry.user.id == bot.user.id):
        return
    fields = [("Member", _who(member)), ("Moderator", entry.user.mention if entry.user else "Unknown"),
              ("Reason", entry.reason or "None")]
    await _modlog(member.guild, "kick", "Member kicked", ERROR, member, fields)


async def _log_timeout(before: discord.Member, after: discord.Member) -> None:
    if not (_event_on(after.guild, "mute") or _event_on(after.guild, "unmute")):
        return
    entry = await _audit_peek(after.guild, discord.AuditLogAction.member_update, after.id)
    if entry is None or entry.user is None or entry.user.id == bot.user.id:
        return
    if after.is_timed_out():
        fields = [("Member", _who(after)), ("Moderator", entry.user.mention),
                  ("Until", discord.utils.format_dt(after.timed_out_until, "f")), ("Reason", entry.reason or "None")]
        await _modlog(after.guild, "mute", "Member muted", STEEL, after, fields)
    else:
        fields = [("Member", _who(after)), ("Moderator", entry.user.mention), ("Reason", entry.reason or "None")]
        await _modlog(after.guild, "unmute", "Member unmuted", CHARCOAL, after, fields)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.timed_out_until != after.timed_out_until:
        await _log_timeout(before, after)


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    await _log_unban(guild, user)


async def _refresh_invites(guild: discord.Guild) -> None:
    try:
        invites = await guild.invites()
    except discord.HTTPException:
        return
    _invite_cache[guild.id] = {invite.code: (invite.uses or 0) for invite in invites}


@bot.event
async def on_invite_create(invite: discord.Invite):
    guild = invite.guild
    _invite_cache.setdefault(guild.id, {})[invite.code] = invite.uses or 0
    expires = "Never" if not invite.max_age else discord.utils.format_dt(
        discord.utils.utcnow() + timedelta(seconds=invite.max_age), "R")
    fields = [("Code", f"`discord.gg/{invite.code}`"), ("Channel", _chan(invite.channel)),
              ("Created by", invite.inviter.mention if invite.inviter else "Unknown"),
              ("Max uses", str(invite.max_uses) if invite.max_uses else "Unlimited"), ("Expires", expires)]
    await _modlog(guild, "invite_create", "Invite created", CHARCOAL, invite.inviter, fields)


@bot.event
async def on_invite_delete(invite: discord.Invite):
    guild = invite.guild
    _invite_cache.get(guild.id, {}).pop(invite.code, None)
    fields = [("Code", f"`discord.gg/{invite.code}`"), ("Channel", _chan(invite.channel))]
    await _modlog(guild, "invite_delete", "Invite deleted", STEEL, None, fields)


INVITES_FILE = DATA_DIR / "invites.json"
invites_store: dict = {"channels": {}, "counts": {}, "joins": {}}


def load_invites() -> None:
    global invites_store
    try:
        invites_store = json.loads(INVITES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        invites_store = {}
    for key in ("channels", "counts", "joins"):
        invites_store.setdefault(key, {})


def save_invites() -> None:
    INVITES_FILE.write_text(json.dumps(invites_store, indent=2), encoding="utf-8")


async def _record_invite(member: discord.Member, inviter) -> None:
    guild = member.guild
    gid = str(guild.id)
    total = 0
    if inviter is not None and not inviter.bot and inviter.id != member.id:
        counts = invites_store["counts"].setdefault(gid, {})
        counts[str(inviter.id)] = counts.get(str(inviter.id), 0) + 1
        invites_store["joins"].setdefault(gid, {})[str(member.id)] = inviter.id
        save_invites()
        total = counts[str(inviter.id)]
    channel_id = invites_store["channels"].get(gid)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return
    who = inviter.mention if inviter is not None else tr(guild.id, "invites.unknown")
    message = tr(guild.id, "invites.message", who=who, member=member.mention, total=total)
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(
        discord.ui.TextDisplay(f"### {E(['GE_member', 'community'], '🔗')} {tr(guild.id, 'invites.new')}"),
        discord.ui.Separator(),
        discord.ui.TextDisplay(message),
        discord.ui.Separator(),
        discord.ui.TextDisplay(f"-# {BOT_NAME} · Invites"),
        accent_colour=STEEL,
    ))
    try:
        await channel.send(view=view, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[invites] could not post: {exc}")


DANGEROUS_PERMS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "ban_members", "kick_members", "manage_webhooks", "mention_everyone",
)


async def _log_bot_join(member: discord.Member) -> None:
    entry = await _audit_peek(member.guild, discord.AuditLogAction.bot_add, member.id, max_age=60)
    adder = entry.user if entry is not None else None
    fields = [
        ("Bot", _who(member)),
        ("Added by", _who(adder) if adder is not None else "Unknown"),
    ]
    await _send_log(member.guild, "invite_join", "Bot added", STEEL, member, fields)


async def _on_invite_member_leave(member: discord.Member) -> None:
    gid = str(member.guild.id)
    inviter_id = invites_store["joins"].get(gid, {}).pop(str(member.id), None)
    if inviter_id is None:
        return
    counts = invites_store["counts"].get(gid, {})
    key = str(inviter_id)
    if counts.get(key, 0) > 0:
        counts[key] -= 1
    save_invites()


@bot.tree.command(name="invites-setup", description="Post a message whenever someone joins with an invite.")
@app_commands.describe(channel="The channel for invite messages")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def invites_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    invites_store["channels"][str(interaction.guild_id)] = channel.id
    save_invites()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} {tr(interaction.guild_id, 'invites.set', channel=channel.mention)}"), ephemeral=True
    )


@bot.tree.command(name="invites-off", description="Stop posting invite messages.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def invites_off(interaction: discord.Interaction):
    invites_store["channels"].pop(str(interaction.guild_id), None)
    save_invites()
    await interaction.response.send_message(
        embed=notice(f"{E('true', '✅')} {tr(interaction.guild_id, 'invites.off')}"), ephemeral=True
    )


bot.add_listener(_on_invite_member_leave, "on_member_remove")
load_invites()


async def _log_invite_join(member: discord.Member) -> None:
    guild = member.guild
    try:
        invites = await guild.invites()
    except discord.HTTPException:
        return
    previous = _invite_cache.get(guild.id, {})
    current = {invite.code: invite for invite in invites}
    used = next((inv for code, inv in current.items() if (inv.uses or 0) > previous.get(code, 0)), None)
    gone = [code for code in previous if code not in current]
    _invite_cache[guild.id] = {code: (inv.uses or 0) for code, inv in current.items()}
    await _record_invite(member, used.inviter if used is not None else None)
    if not _event_on(guild, "invite_join"):
        return
    if used is not None:
        code_text = f"`discord.gg/{used.code}`"
        inviter_text = used.inviter.mention if used.inviter else "Unknown"
        channel_text = _chan(used.channel)
    elif len(gone) == 1:
        code_text, inviter_text, channel_text = f"`discord.gg/{gone[0]}`", "Unknown", "Unknown"
    else:
        code_text, inviter_text, channel_text = "Unknown (vanity or unknown link)", "Unknown", "Unknown"
    fields = [("Member", _who(member)), ("Invite", code_text), ("Invited by", inviter_text), ("Channel", channel_text)]
    await _modlog(guild, "invite_join", "Member joined by invite", CHARCOAL, member, fields)


import aiohttp

ANIME_ACTIONS = {
    "hug": {"category": "hug", "emoji": "🤗", "color": STEEL, "back": True},
    "kiss": {"category": "kiss", "emoji": "💋", "color": STEEL, "back": True},
    "punch": {"category": "punch", "emoji": "👊", "color": STEEL, "back": True},
    "cry": {"category": "cry", "emoji": "😭", "color": STEEL, "back": False},
    "sleep": {"category": "sleep", "emoji": "😴", "color": STEEL, "back": False},
    "banana": {"category": "happy", "emoji": "🍌", "color": STEEL, "back": False},
}
ANIME_COUNTED = ("hug", "kiss", "punch")

ANIME_STATS_FILE = DATA_DIR / "anime_stats.json"
anime_stats: dict[str, int] = {}


def load_anime_stats() -> None:
    global anime_stats
    try:
        anime_stats = json.loads(ANIME_STATS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        anime_stats = {}


def _pair_note(gid: int, action: str, a, b) -> str | None:
    if action not in ANIME_COUNTED:
        return None
    low, high = sorted((a.id, b.id))
    key = f"{gid}:{action}:{low}:{high}"
    anime_stats[key] = anime_stats.get(key, 0) + 1
    ANIME_STATS_FILE.write_text(json.dumps(anime_stats, indent=2), encoding="utf-8")
    return tr(gid, "anime.note", a=a.mention, b=b.mention, n=anime_stats[key], noun=tr(gid, f"anime.{action}.noun"))


load_anime_stats()


async def _anime_gif(category: str) -> str | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(f"https://nekos.best/api/v2/{category}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        results = data.get("results") or []
        return results[0].get("url") if results else None
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        print(f"[anime] could not fetch {category}: {exc}")
        return None


class AnimeView(discord.ui.LayoutView):
    def __init__(self, text, gif, color, *, gid=0, author=None, target=None, back_text=None, category=None,
                 action=None, note=None):
        super().__init__(timeout=300)
        self.gid = gid
        self.author = author
        self.target = target
        self.back_text = back_text
        self.category = category
        self.action = action
        self.color = color
        children = [discord.ui.TextDisplay(f"### {text}")]
        if note:
            children.append(discord.ui.TextDisplay(note))
        if gif:
            children += [discord.ui.Separator(), discord.ui.MediaGallery(discord.MediaGalleryItem(gif))]
        if target is not None and back_text:
            button = discord.ui.Button(label=tr(gid, "anime.return"), emoji="↩️", style=discord.ButtonStyle.secondary)
            button.callback = self._give_back
            children += [discord.ui.Separator(), discord.ui.ActionRow(button)]
        children += [discord.ui.Separator(), discord.ui.TextDisplay(tr(gid, "anime.footer", bot=BOT_NAME))]
        self.add_item(discord.ui.Container(*children, accent_colour=color))

    async def _give_back(self, interaction: discord.Interaction):
        if interaction.user.id != self.target.id:
            return await interaction.response.send_message(
                embed=error_notice(tr(self.gid, "anime.only_receiver")), ephemeral=True
            )
        await interaction.response.defer()
        gif = await _anime_gif(self.category)
        text = tr(self.gid, f"anime.{self.action}.back", a=self.target.mention, b=self.author.mention)
        note = _pair_note(self.gid, self.action, self.target, self.author)
        await interaction.followup.send(view=AnimeView(f"{ANIME_ACTIONS[self.action]['emoji']} {text}", gif, self.color,
                                                       gid=self.gid, action=self.action, note=note))


BANANA_IMAGE = Path(__file__).parent / "assets" / "banana.png"
BANANA_IMAGE_URL = "https://static.vecteezy.com/system/resources/previews/024/734/340/large_2x/cartoon-illustration-of-two-bananas-vector.jpg"


async def _send_anime(author, guild, name: str, member, send) -> None:
    cfg = ANIME_ACTIONS[name]
    target = member if member is not None and member.id != author.id else None
    gid = guild.id if guild is not None else 0
    file = None
    if name == "banana":
        centimeters = random.randint(5, 30)
        if target is None:
            text = tr(gid, "anime.banana.measure", a=author.mention, cm=centimeters)
        else:
            text = tr(gid, "anime.banana.measure_for", a=author.mention, b=target.mention, cm=centimeters)
        gif = BANANA_IMAGE_URL
        if BANANA_IMAGE.exists():
            file = discord.File(BANANA_IMAGE, filename="banana.png")
            gif = "attachment://banana.png"
        view = AnimeView(f"{cfg['emoji']} {text}", gif, cfg["color"], gid=gid)
    else:
        if target is None:
            text = tr(gid, f"anime.{name}.solo", a=author.mention)
        else:
            text = tr(gid, f"anime.{name}.text", a=author.mention, b=target.mention)
        note = _pair_note(gid, name, author, target) if target is not None else None
        gif = await _anime_gif(cfg["category"])
        back_text = tr(gid, f"anime.{name}.back") if cfg["back"] and target is not None else None
        view = AnimeView(f"{cfg['emoji']} {text}", gif, cfg["color"], gid=gid, author=author, target=target,
                         back_text=back_text, category=cfg["category"], action=name, note=note)
    if file is not None:
        await send(view=view, file=file)
    else:
        await send(view=view)


def _register_anime_command(name: str) -> None:
    @bot.command(name=name)
    async def anime_prefix(ctx: commands.Context, member: Optional[discord.User] = None):
        await _send_anime(ctx.author, ctx.guild, name, member, ctx.send)

    @bot.tree.command(name=name, description=f"Send an anime {name} reaction.")
    @app_commands.describe(member="Who to send it to (optional)")
    async def anime_slash(interaction: discord.Interaction, member: Optional[discord.User] = None):
        await interaction.response.defer()
        await _send_anime(interaction.user, interaction.guild, name, member, interaction.followup.send)


for _anime_name in ANIME_ACTIONS:
    _register_anime_command(_anime_name)


AFK_STATE: dict[tuple[int, int], dict] = {}


async def _set_afk_nick(member: discord.Member) -> bool:
    if member.id == member.guild.owner_id:
        return True  # Discord no permite cambiar el apodo del dueño; solo se avisa en menciones
    if member.display_name.startswith("[AFK] "):
        return True
    try:
        await member.edit(nick=f"[AFK] {member.display_name}"[:32], reason="AFK")
        return True
    except discord.HTTPException as exc:
        print(f"[afk] could not rename {member} to AFK: {exc}")
        return False


async def _clear_afk_nick(member: discord.Member, record: dict) -> None:
    try:
        await member.edit(nick=record.get("nick"), reason="Back from AFK")
    except discord.HTTPException:
        pass


async def _start_afk(member: discord.Member, reason: str) -> bool:
    AFK_STATE[(member.guild.id, member.id)] = {
        "since": now_ts(), "reason": reason, "nick": member.nick, "mentions": [],
    }
    return await _set_afk_nick(member)


@bot.command(name="afk")
async def afk_prefix(ctx: commands.Context, *, reason: str = "AFK"):
    if ctx.guild is None:
        return
    renamed = await _start_afk(ctx.author, reason[:120])
    note = "" if renamed else "\n-# No pude poner [AFK] en tu apodo: revisa que mi rol esté por encima del tuyo y que tenga Gestionar apodos."
    await ctx.reply(embed=base_embed(f"{E('warn3', '😴')} {tr(ctx.guild.id, 'afk.now')}", reason[:120] + note, STEEL),
                    mention_author=False)


@bot.tree.command(name="afk", description="Set yourself as AFK. Mentions are logged for when you return.")
@app_commands.describe(reason="Why you are away")
@app_commands.guild_only()
async def afk_slash(interaction: discord.Interaction, reason: app_commands.Range[str, 1, 120] = "AFK"):
    renamed = await _start_afk(interaction.user, reason)
    note = "" if renamed else "\n-# No pude poner [AFK] en tu apodo: revisa que mi rol esté por encima del tuyo y que tenga Gestionar apodos."
    await interaction.response.send_message(
        embed=base_embed(f"{E('warn3', '😴')} {tr(interaction.guild_id, 'afk.now')}", reason + note, STEEL), ephemeral=True)


async def _afk_on_message(message: discord.Message) -> None:
    if message.guild is None or message.author.bot:
        return
    gid = message.guild.id
    is_afk_command = message.content.strip().lower().startswith(("!afk", "/afk"))
    record = None if is_afk_command else AFK_STATE.pop((gid, message.author.id), None)
    if record is not None:
        await _clear_afk_nick(message.author, record)
        away = fmt_seconds(now_ts() - record["since"])
        lines = [tr(gid, "afk.welcome", a=message.author.mention, time=away),
                 tr(gid, "afk.mentions", n=len(record["mentions"]))]
        for item in record["mentions"][:10]:
            lines.append(f"• {item['author']}: [{tr(gid, 'afk.jump')}]({item['url']})")
        try:
            await message.channel.send(embed=base_embed(f"😴 {tr(gid, 'afk.welcome_title')}", "\n".join(lines), STEEL),
                                       allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
    mentioned_ids = {m.id for m in message.mentions}
    mentioned_ids.update(int(x) for x in re.findall(r"<@!?(\d+)>", message.content or ""))
    for target_id in mentioned_ids:
        if target_id == message.author.id:
            continue
        mentioned = AFK_STATE.get((gid, target_id))
        if mentioned is None:
            continue
        target = message.guild.get_member(target_id)
        if target is None or target.bot:
            continue
        mentioned["mentions"] = (mentioned["mentions"] + [{"author": str(message.author), "url": message.jump_url}])[-25:]
        try:
            away = fmt_seconds(max(0, now_ts() - mentioned["since"]))
            await message.channel.send(
                embed=base_embed(f"{E('warn3', '😴')} {tr(gid, 'afk.mention_title', name=target.display_name, time=away)}",
                                 mentioned["reason"], STEEL),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass
    if bot.user is not None and re.search(rf"<@!?{bot.user.id}>", message.content or ""):
        try:
            await message.channel.send(
                embed=base_embed(tr(gid, "bot.hi", name=message.author.display_name),
                                 tr(gid, "bot.intro", server=server_name(message.guild)), STEEL),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass


bot.add_listener(_afk_on_message, "on_message")


def _excerpt(text: str | None, limit: int = 900) -> str:
    if not text:
        return "*No text*"
    return text if len(text) <= limit else text[:limit] + "…"


def _skip_message_log(message: discord.Message) -> bool:
    if message.guild is None or message.author.bot:
        return True
    cfg = modlog_cfg(message.guild.id)
    return not cfg["channel"] or message.channel.id == cfg["channel"]


async def _on_message_delete(message: discord.Message) -> None:
    if _skip_message_log(message):
        return
    images = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
    if images:
        fields = [
            ("Author", _who(message.author)),
            ("Channel", _chan(message.channel)),
            ("Images", str(len(images))),
            ("Text", _excerpt(message.content)),
        ]
        await _send_log(message.guild, "photo", "Photo deleted", STEEL, message.author, fields,
                        [a.url for a in images])
        return
    attachments = ", ".join(a.filename for a in message.attachments) or "None"
    fields = [
        ("Author", _who(message.author)),
        ("Channel", _chan(message.channel)),
        ("Content", _excerpt(message.content)),
        ("Attachments", attachments),
    ]
    await _modlog(message.guild, "message_delete", "Message deleted", STEEL, message.author, fields)


async def _on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if _skip_message_log(after) or before.content == after.content:
        return
    fields = [
        ("Author", _who(after.author)),
        ("Channel", _chan(after.channel)),
        ("Before", _excerpt(before.content)),
        ("After", _excerpt(after.content)),
        ("Message", f"[Jump to message]({after.jump_url})"),
    ]
    await _modlog(after.guild, "message_edit", "Message edited", STEEL, after.author, fields)


async def _send_log(guild, event: str, title: str, color: int, target, fields, media=None) -> None:
    if not _event_on(guild, event):
        return
    channel = guild.get_channel(modlog_cfg(guild.id)["channel"])
    if channel is None:
        return
    try:
        await channel.send(view=_action_card(title, color, target, fields, media),
                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as exc:
        print(f"[modlog] could not post: {exc}")
        if media:
            links = "\n".join(f"[Image {i + 1}]({url})" for i, url in enumerate(media[:10]))
            await _send_log(guild, event, title, color, target, fields + [("Images", links)])


async def _actor_of(guild: discord.Guild, action, target_id: int):
    entry = await _audit_peek(guild, action, target_id, max_age=30)
    return entry.user if entry else None


async def _log_asset_changes(guild, event: str, kind: str, before, after, actions: tuple, label) -> None:
    old = {a.id: a for a in before}
    new = {a.id: a for a in after}
    create_action, delete_action, update_action = actions
    for asset_id, asset in new.items():
        if asset_id not in old:
            actor = await _actor_of(guild, create_action, asset_id)
            fields = [(kind, label(asset)), ("Created by", actor.mention if actor else "Unknown")]
            await _modlog(guild, event, f"{kind} created", STEEL, actor, fields)
        elif old[asset_id].name != asset.name:
            actor = await _actor_of(guild, update_action, asset_id)
            fields = [(kind, label(asset)), ("Before", f"`{old[asset_id].name}`"),
                      ("After", f"`{asset.name}`"), ("Renamed by", actor.mention if actor else "Unknown")]
            await _modlog(guild, event, f"{kind} renamed", STEEL, actor, fields)
    for asset_id, asset in old.items():
        if asset_id not in new:
            actor = await _actor_of(guild, delete_action, asset_id)
            fields = [(kind, label(asset)), ("Deleted by", actor.mention if actor else "Unknown")]
            await _modlog(guild, event, f"{kind} deleted", STEEL, actor, fields)


async def _on_emojis_changed(guild, before, after) -> None:
    await _log_asset_changes(
        guild, "emoji", "Emoji", before, after,
        (discord.AuditLogAction.emoji_create, discord.AuditLogAction.emoji_delete, discord.AuditLogAction.emoji_update),
        lambda e: f"{e} `:{e.name}:`",
    )


async def _on_stickers_changed(guild, before, after) -> None:
    await _log_asset_changes(
        guild, "sticker", "Sticker", before, after,
        (discord.AuditLogAction.sticker_create, discord.AuditLogAction.sticker_delete, discord.AuditLogAction.sticker_update),
        lambda s: f"`{s.name}`",
    )


bot.add_listener(_on_message_delete, "on_message_delete")
bot.add_listener(_on_message_edit, "on_message_edit")
bot.add_listener(_on_emojis_changed, "on_guild_emojis_update")
bot.add_listener(_on_stickers_changed, "on_guild_stickers_update")


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot or before.channel == after.channel:
        return
    if before.channel is None:
        title, color, fields = "Joined voice", CHARCOAL, [("Member", _who(member)), ("Channel", after.channel.mention)]
    elif after.channel is None:
        title, color, fields = "Left voice", STEEL, [("Member", _who(member)), ("Channel", before.channel.mention)]
    else:
        title, color, fields = "Moved voice", CHARCOAL, [
            ("Member", _who(member)), ("From", before.channel.mention), ("To", after.channel.mention)]
    await _modlog(member.guild, "voice", title, color, member, fields)



# ============================================================
# Paneles de configuración: /welcomes-settings, /invites-settings, /despedidas-settings
# ============================================================
WELCOME_TEXTS_FILE = DATA_DIR / "welcome_texts.json"
GOODBYE_TEXTS_FILE = DATA_DIR / "goodbye_texts.json"
WELCOME_DEFAULT_BODY = "«Thank you for joining Synex Protect. We're excited to have you as part of our community.»"


def _load_json_dict(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


welcome_text_config: dict[str, str] = _load_json_dict(WELCOME_TEXTS_FILE)
goodbye_text_config: dict[str, str] = _load_json_dict(GOODBYE_TEXTS_FILE)


def save_welcome_texts() -> None:
    WELCOME_TEXTS_FILE.write_text(json.dumps(welcome_text_config, indent=2), encoding="utf-8")


def save_goodbye_texts() -> None:
    GOODBYE_TEXTS_FILE.write_text(json.dumps(goodbye_text_config, indent=2), encoding="utf-8")


def render_text(text: str, **values) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


class SettingsPanel(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error_notice("This panel belongs to someone else."), ephemeral=True)
            return False
        return True

    def render(self, guild: discord.Guild) -> discord.Embed:
        raise NotImplementedError

    async def show(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.render(interaction.guild), view=self)

    async def done(self, interaction: discord.Interaction, text: str) -> None:
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} {text}"), ephemeral=True)


class ChannelPick(discord.ui.ChannelSelect):
    def __init__(self, placeholder: str, on_pick):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.text],
                         min_values=1, max_values=1)
        self.on_pick = on_pick

    async def callback(self, interaction: discord.Interaction):
        await self.on_pick(interaction, self.values[0].id)


class TextModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, default: str | None, placeholder: str, save):
        super().__init__(title=title)
        self.save = save
        self.field = discord.ui.TextInput(
            label=label, style=discord.TextStyle.paragraph, default=default or None, required=False,
            placeholder=placeholder[:100], max_length=1000,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        await self.save(interaction, self.field.value.strip())


class WelcomeButtonModal(discord.ui.Modal, title="Welcome button"):
    slot = discord.ui.TextInput(label="Position (1 to 5)", max_length=1, placeholder="1")
    button_text = discord.ui.TextInput(label="Button text", max_length=80)
    url = discord.ui.TextInput(label="Link (starts with https://)", max_length=300)
    emoji = discord.ui.TextInput(label="Emoji (optional)", required=False, max_length=64)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            position = int(self.slot.value.strip())
        except ValueError:
            position = 0
        if not 1 <= position <= WELCOME_BUTTON_LIMIT:
            return await interaction.response.send_message(
                embed=error_notice(f"Position must be between 1 and {WELCOME_BUTTON_LIMIT}."), ephemeral=True)
        url = self.url.value.strip()
        if not url.startswith("https://"):
            return await interaction.response.send_message(
                embed=error_notice("The link must start with https://"), ephemeral=True)
        emoji_value = None
        raw_emoji = self.emoji.value.strip()
        if raw_emoji:
            try:
                discord.PartialEmoji.from_str(raw_emoji)
            except (ValueError, TypeError):
                return await interaction.response.send_message(
                    embed=error_notice("That emoji is not valid."), ephemeral=True)
            emoji_value = raw_emoji
        buttons = welcome_buttons_for(interaction.guild_id)
        if position > len(buttons) + 1:
            return await interaction.response.send_message(
                embed=error_notice(f"Fill slot {len(buttons) + 1} first."), ephemeral=True)
        entry = {"label": self.button_text.value.strip(), "url": url, "emoji": emoji_value}
        if position > len(buttons):
            buttons.append(entry)
        else:
            buttons[position - 1] = entry
        welcome_buttons_config[str(interaction.guild_id)] = buttons
        save_welcome_buttons()
        await interaction.response.send_message(
            embed=notice(f"{E('true', '✅')} Welcome button {position} saved: **{entry['label']}**."), ephemeral=True)


class WelcomeButtonRemoveModal(discord.ui.Modal, title="Remove welcome button"):
    slot = discord.ui.TextInput(label="Position (1 to 5)", max_length=1, placeholder="1")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            position = int(self.slot.value.strip())
        except ValueError:
            position = 0
        buttons = welcome_buttons_for(interaction.guild_id)
        if not 1 <= position <= len(buttons):
            return await interaction.response.send_message(
                embed=error_notice("There is no button in that slot."), ephemeral=True)
        if len(buttons) == 1:
            return await interaction.response.send_message(
                embed=error_notice("A welcome message needs at least one button."), ephemeral=True)
        buttons.pop(position - 1)
        welcome_buttons_config[str(interaction.guild_id)] = buttons
        save_welcome_buttons()
        await interaction.response.send_message(
            embed=notice(f"{E('true', '✅')} Welcome button {position} removed."), ephemeral=True)


# ---------- /invites-settings ----------
def invites_embed(guild: discord.Guild) -> discord.Embed:
    gid = str(guild.id)
    counts = invites_store["counts"].get(gid, {})
    top = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:3]
    top_text = "\n".join(f"{i}. <@{uid}> · **{n}**" for i, (uid, n) in enumerate(top, 1)) or "None yet"
    rows = [
        ("Channel", _channel_text(guild, invites_store["channels"].get(gid))),
        ("Inviters tracked", str(len(counts))),
        ("Top inviters", top_text),
    ]
    return _settings_embed("Invite settings", rows)


class InvitesPanel(SettingsPanel):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(ChannelPick("Pick the invite channel", self._set_channel))

    def render(self, guild):
        return invites_embed(guild)

    async def _set_channel(self, interaction, channel_id: int):
        invites_store["channels"][str(interaction.guild_id)] = channel_id
        save_invites()
        await self.show(interaction)

    @discord.ui.button(label="Turn off", style=discord.ButtonStyle.danger, row=1)
    async def turn_off(self, interaction, button):
        invites_store["channels"].pop(str(interaction.guild_id), None)
        save_invites()
        await self.show(interaction)

    @discord.ui.button(label="Reset counts", style=discord.ButtonStyle.danger, row=1)
    async def reset_counts(self, interaction, button):
        gid = str(interaction.guild_id)
        invites_store["counts"].pop(gid, None)
        invites_store["joins"].pop(gid, None)
        save_invites()
        await self.show(interaction)


@bot.tree.command(name="invites-settings", description="Configure invite tracking: channel and counts.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def invites_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=invites_embed(interaction.guild), view=InvitesPanel(interaction.user.id), ephemeral=True)


# Panel de configuración de tickets: /tickets-settings
# ============================================================
TICKET_SETTINGS_FILE = DATA_DIR / "tickets_settings.json"
DEFAULT_TICKET_TYPES = copy.deepcopy(TICKET_TYPES)
DEFAULT_PANEL_TEXT = PANEL_TEXT
DEFAULT_TICKET_WELCOME_TITLE = WELCOME_TITLE
DEFAULT_TICKET_WELCOME_BODY = WELCOME_BODY
DEFAULT_TICKET_WELCOME_COLOR = WELCOME_COLOR


def save_ticket_settings() -> None:
    data = {
        "logs": LOGS_CHANNEL_ID,
        "transcripts": TRANSCRIPT_CHANNEL_ID,
        "roles": SUPPORT_ROLE_IDS,
        "max_open": MAX_OPEN_PER_USER,
        "inactivity": INACTIVITY_HOURS,
        "save_transcripts": SAVE_TRANSCRIPTS,
        "dm_transcript": DM_TRANSCRIPT_ON_CLOSE,
        "panel_text": PANEL_TEXT,
        "panel_color": PANEL_COLOR,
        "types": TICKET_TYPES,
        "welcome_title": WELCOME_TITLE,
        "welcome_body": WELCOME_BODY,
        "welcome_color": WELCOME_COLOR,
    }
    TICKET_SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_ticket_setting(name: str, value) -> None:
    globals()[name] = value
    save_ticket_settings()


def tickets_embed(guild: discord.Guild) -> discord.Embed:
    category_id = ticket_data.get("category_id") or TICKET_CATEGORY_ID
    category = guild.get_channel(category_id) if category_id else None
    roles = [guild.get_role(rid) for rid in SUPPORT_ROLE_IDS]
    rows = [
        ("Category", f"**{category.name}**" if category else "Not set"),
        ("Panel channel", _channel_text(guild, ticket_data["panel"].get("channel_id"))),
        ("Logs channel", _channel_text(guild, LOGS_CHANNEL_ID)),
        ("Transcripts channel", _channel_text(guild, TRANSCRIPT_CHANNEL_ID)),
        ("Support roles", " ".join(r.mention for r in roles if r) or "None"),
        ("Max open per user", str(MAX_OPEN_PER_USER)),
        ("Inactivity close", f"{INACTIVITY_HOURS} h" if INACTIVITY_HOURS else "Off"),
        ("Save transcripts", "On" if SAVE_TRANSCRIPTS else "Off"),
        ("DM transcript on close", "On" if DM_TRANSCRIPT_ON_CLOSE else "Off"),
        ("Ticket types", ", ".join(f"{t['label']} (`{t['key']}`)" for t in TICKET_TYPES) or "None"),
        ("Open tickets", str(len(ticket_data["open"]))),
    ]
    return _settings_embed("Ticket settings", rows)


class TicketTextModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, default: str | None, placeholder: str, setting: str,
                 paragraph: bool = True, max_length: int = 1000):
        super().__init__(title=title)
        self.setting = setting
        self.field = discord.ui.TextInput(
            label=label, style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
            default=default or None, required=True, placeholder=placeholder[:100], max_length=max_length,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        text = self.field.value.strip()
        if not text:
            return await interaction.response.send_message(embed=error_notice("That can't be empty."), ephemeral=True)
        set_ticket_setting(self.setting, text)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Saved."), ephemeral=True)


class TicketIntModal(discord.ui.Modal):
    def __init__(self, title: str, label: str, default: int, low: int, high: int, setting: str):
        super().__init__(title=title)
        self.low, self.high, self.setting = low, high, setting
        self.field = discord.ui.TextInput(label=label, default=str(default), max_length=4)
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.field.value.strip())
        except ValueError:
            value = None
        if value is None or not self.low <= value <= self.high:
            return await interaction.response.send_message(
                embed=error_notice(f"Enter a number between {self.low} and {self.high}."), ephemeral=True)
        set_ticket_setting(self.setting, value)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Saved."), ephemeral=True)


class TicketColorModal(discord.ui.Modal):
    def __init__(self, title: str, default_name: str, setting: str):
        super().__init__(title=title)
        self.setting = setting
        self.field = discord.ui.TextInput(
            label="Color name or hex", default=default_name, max_length=20,
            placeholder="Blue, Red, Silver... or #3B82F6")
        self.add_item(self.field)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            code = parse_color(self.field.value)
        except ValueError:
            return await interaction.response.send_message(
                embed=error_notice("Use a color name from the list or a hex code like #3B82F6."), ephemeral=True)
        set_ticket_setting(self.setting, code)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Color saved."), ephemeral=True)


class TicketTypeModal(discord.ui.Modal):
    label_in = discord.ui.TextInput(label="Name", max_length=50)
    emoji_in = discord.ui.TextInput(label="Emoji", max_length=64, placeholder="🎫 or <:name:id>")
    description_in = discord.ui.TextInput(label="Short description (menu)", max_length=100)
    intro_in = discord.ui.TextInput(label="Intro text in the ticket", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, existing: dict | None):
        super().__init__(title="Edit ticket type" if existing else "New ticket type")
        self.existing = existing
        if existing:
            self.label_in.default = existing["label"]
            self.emoji_in.default = existing["emoji"]
            self.description_in.default = existing["description"]
            self.intro_in.default = existing["intro"]

    async def on_submit(self, interaction: discord.Interaction):
        label = self.label_in.value.strip()
        emoji = self.emoji_in.value.strip()
        try:
            discord.PartialEmoji.from_str(emoji)
        except (ValueError, TypeError):
            return await interaction.response.send_message(embed=error_notice("That emoji is not valid."), ephemeral=True)
        entry = {
            "label": label,
            "emoji": emoji,
            "description": self.description_in.value.strip(),
            "intro": self.intro_in.value.strip(),
        }
        if self.existing:
            self.existing.update(entry)
        else:
            used = {t["key"] for t in TICKET_TYPES}
            base = slugify(label)
            key, n = base, 2
            while key in used:
                key = f"{base}-{n}"
                n += 1
            TICKET_TYPES.append({"key": key, **entry})
        save_ticket_settings()
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Ticket type **{label}** saved."), ephemeral=True)


class TicketTypeRemoveModal(discord.ui.Modal, title="Remove ticket type"):
    key_in = discord.ui.TextInput(label="Type key to remove", max_length=50, placeholder="support, buy, giveaways...")

    async def on_submit(self, interaction: discord.Interaction):
        key = self.key_in.value.strip().lower()
        target = ticket_type(key)
        if target is None:
            return await interaction.response.send_message(embed=error_notice("There is no type with that key."), ephemeral=True)
        if len(TICKET_TYPES) <= 1:
            return await interaction.response.send_message(embed=error_notice("The panel needs at least one type."), ephemeral=True)
        TICKET_TYPES.remove(target)
        save_ticket_settings()
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Type **{target['label']}** removed."), ephemeral=True)


class TicketChannelPick(discord.ui.ChannelSelect):
    def __init__(self, placeholder: str, channel_types, setter, row: int):
        super().__init__(placeholder=placeholder, channel_types=channel_types, min_values=0, max_values=1, row=row)
        self.setter = setter

    async def callback(self, interaction: discord.Interaction):
        await self.setter(interaction, self.values[0].id if self.values else None)


class TicketRolePick(discord.ui.RoleSelect):
    def __init__(self, setter, row: int):
        super().__init__(placeholder="Pick the support roles (empty = none)", min_values=0, max_values=10, row=row)
        self.setter = setter

    async def callback(self, interaction: discord.Interaction):
        await self.setter(interaction, [r.id for r in self.values])


class TicketTypeSelect(discord.ui.Select):
    def __init__(self, row: int):
        options = [discord.SelectOption(label=t["label"], value=t["key"], description=t["description"][:100],
                                        emoji=t["emoji"]) for t in TICKET_TYPES][:25]
        super().__init__(placeholder="Pick a type to edit…", options=options, min_values=1, max_values=1, row=row)

    async def callback(self, interaction: discord.Interaction):
        target = ticket_type(self.values[0])
        if target is None:
            return await interaction.response.send_message(embed=error_notice("That type no longer exists."), ephemeral=True)
        await interaction.response.send_modal(TicketTypeModal(target))


class TicketsMainPanel(SettingsPanel):
    def render(self, guild):
        return tickets_embed(guild)

    @discord.ui.button(label="Channels", style=discord.ButtonStyle.primary, row=0)
    async def channels(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketChannelsPanel(self.owner_id))

    @discord.ui.button(label="Support roles", style=discord.ButtonStyle.primary, row=0)
    async def roles(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketRolesPanel(self.owner_id))

    @discord.ui.button(label="Limits & transcripts", style=discord.ButtonStyle.primary, row=0)
    async def limits(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketLimitsPanel(self.owner_id))

    @discord.ui.button(label="Panel", style=discord.ButtonStyle.primary, row=0)
    async def panel(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketPanelPanel(self.owner_id))

    @discord.ui.button(label="Ticket types", style=discord.ButtonStyle.primary, row=0)
    async def types(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketTypesPanel(self.owner_id))

    @discord.ui.button(label="Welcome message", style=discord.ButtonStyle.primary, row=1)
    async def welcome(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketWelcomePanel(self.owner_id))


class TicketSubPanel(SettingsPanel):
    title = "Ticket settings"

    def render(self, guild):
        embed = tickets_embed(guild)
        embed.title = self.title
        return embed

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=tickets_embed(interaction.guild), view=TicketsMainPanel(self.owner_id))


class TicketChannelsPanel(TicketSubPanel):
    title = "Ticket channels"

    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(TicketChannelPick("Ticket category (clear to use default)", [discord.ChannelType.category],
                                        self._set_category, row=0))
        self.add_item(TicketChannelPick("Logs channel (clear to turn off)", [discord.ChannelType.text],
                                        self._set_logs, row=1))
        self.add_item(TicketChannelPick("Transcripts channel (clear to turn off)", [discord.ChannelType.text],
                                        self._set_transcripts, row=2))

    async def _set_category(self, interaction, channel_id):
        ticket_data["category_id"] = channel_id
        save_tickets()
        await self.show(interaction)

    async def _set_logs(self, interaction, channel_id):
        set_ticket_setting("LOGS_CHANNEL_ID", channel_id)
        await self.show(interaction)

    async def _set_transcripts(self, interaction, channel_id):
        set_ticket_setting("TRANSCRIPT_CHANNEL_ID", channel_id)
        await self.show(interaction)


class TicketRolesPanel(TicketSubPanel):
    title = "Support roles"

    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(TicketRolePick(self._set_roles, row=0))

    async def _set_roles(self, interaction, role_ids):
        set_ticket_setting("SUPPORT_ROLE_IDS", role_ids)
        await self.show(interaction)


class TicketLimitsPanel(TicketSubPanel):
    title = "Limits & transcripts"

    @discord.ui.button(label="Max open per user", style=discord.ButtonStyle.primary, row=0)
    async def max_open(self, interaction, button):
        await interaction.response.send_modal(TicketIntModal(
            "Max open tickets", "Tickets per user (1 to 10)", MAX_OPEN_PER_USER, 1, 10, "MAX_OPEN_PER_USER"))

    @discord.ui.button(label="Inactivity close", style=discord.ButtonStyle.primary, row=0)
    async def inactivity(self, interaction, button):
        await interaction.response.send_modal(TicketIntModal(
            "Inactivity close", "Hours without messages (0 = off)", INACTIVITY_HOURS, 0, 720, "INACTIVITY_HOURS"))

    @discord.ui.button(label="Toggle transcripts", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_transcripts(self, interaction, button):
        set_ticket_setting("SAVE_TRANSCRIPTS", not SAVE_TRANSCRIPTS)
        await self.show(interaction)

    @discord.ui.button(label="Toggle DM transcript", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_dm(self, interaction, button):
        set_ticket_setting("DM_TRANSCRIPT_ON_CLOSE", not DM_TRANSCRIPT_ON_CLOSE)
        await self.show(interaction)


class TicketPanelPanel(TicketSubPanel):
    title = "Ticket panel"

    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(TicketChannelPick("Post the panel in… (posts right away)", [discord.ChannelType.text],
                                        self._post, row=1))

    async def _post(self, interaction, channel_id):
        if channel_id is None:
            return await interaction.response.send_message(embed=error_notice("Pick a channel."), ephemeral=True)
        channel = interaction.guild.get_channel(channel_id)
        await post_panel(channel, interaction.guild)
        await self.done(interaction, f"Panel posted in {channel.mention}.")

    @discord.ui.button(label="Edit panel text", style=discord.ButtonStyle.primary, row=0)
    async def edit_text(self, interaction, button):
        await interaction.response.send_modal(TicketTextModal(
            "Panel text", "Text shown on the panel", PANEL_TEXT, "Use {member} and {star}", "PANEL_TEXT"))

    @discord.ui.button(label="Panel color", style=discord.ButtonStyle.primary, row=0)
    async def color(self, interaction, button):
        await interaction.response.send_modal(TicketColorModal("Panel color", "Blue", "PANEL_COLOR"))

    @discord.ui.button(label="Reset panel text", style=discord.ButtonStyle.secondary, row=2)
    async def reset_text(self, interaction, button):
        set_ticket_setting("PANEL_TEXT", DEFAULT_PANEL_TEXT)
        await self.show(interaction)

    @discord.ui.button(label="Refresh panel", style=discord.ButtonStyle.secondary, row=2)
    async def refresh(self, interaction, button):
        channel_id = ticket_data["panel"].get("channel_id")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel is None:
            return await interaction.response.send_message(
                embed=error_notice("There is no panel yet. Post one with the option above."), ephemeral=True)
        await post_panel(channel, interaction.guild)
        await self.done(interaction, "Panel refreshed with the current types and text.")


class TicketTypesPanel(TicketSubPanel):
    title = "Ticket types"

    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(TicketTypeSelect(row=0))

    @discord.ui.button(label="Add type", style=discord.ButtonStyle.primary, row=1)
    async def add_type(self, interaction, button):
        await interaction.response.send_modal(TicketTypeModal(None))

    @discord.ui.button(label="Remove type", style=discord.ButtonStyle.danger, row=1)
    async def remove_type(self, interaction, button):
        await interaction.response.send_modal(TicketTypeRemoveModal())

    @discord.ui.button(label="Reset types", style=discord.ButtonStyle.secondary, row=1)
    async def reset_types(self, interaction, button):
        TICKET_TYPES[:] = copy.deepcopy(DEFAULT_TICKET_TYPES)
        save_ticket_settings()
        await self.show(interaction)


class TicketWelcomePanel(TicketSubPanel):
    title = "Ticket welcome message"

    @discord.ui.button(label="Edit title", style=discord.ButtonStyle.primary, row=0)
    async def edit_title(self, interaction, button):
        await interaction.response.send_modal(TicketTextModal(
            "Welcome title", "Title", WELCOME_TITLE, "Use {welcome} and {username}", "WELCOME_TITLE",
            paragraph=False, max_length=200))

    @discord.ui.button(label="Edit body", style=discord.ButtonStyle.primary, row=0)
    async def edit_body(self, interaction, button):
        await interaction.response.send_modal(TicketTextModal(
            "Welcome body", "Body text",
            WELCOME_BODY, "Use {server}, {intro}, {option}, {number} and {opened}", "WELCOME_BODY"))

    @discord.ui.button(label="Color", style=discord.ButtonStyle.secondary, row=0)
    async def color(self, interaction, button):
        await interaction.response.send_modal(TicketColorModal("Welcome color", "Gray", "WELCOME_COLOR"))

    @discord.ui.button(label="Reset", style=discord.ButtonStyle.secondary, row=1)
    async def reset(self, interaction, button):
        set_ticket_setting("WELCOME_TITLE", DEFAULT_TICKET_WELCOME_TITLE)
        set_ticket_setting("WELCOME_BODY", DEFAULT_TICKET_WELCOME_BODY)
        set_ticket_setting("WELCOME_COLOR", DEFAULT_TICKET_WELCOME_COLOR)
        await self.show(interaction)


# Cargar lo guardado desde el panel al iniciar el bot
_saved_tickets = _load_json_dict(TICKET_SETTINGS_FILE)
if _saved_tickets:
    LOGS_CHANNEL_ID = _saved_tickets.get("logs", LOGS_CHANNEL_ID)
    TRANSCRIPT_CHANNEL_ID = _saved_tickets.get("transcripts", TRANSCRIPT_CHANNEL_ID)
    SUPPORT_ROLE_IDS = list(_saved_tickets.get("roles", SUPPORT_ROLE_IDS))
    MAX_OPEN_PER_USER = _saved_tickets.get("max_open", MAX_OPEN_PER_USER)
    INACTIVITY_HOURS = _saved_tickets.get("inactivity", INACTIVITY_HOURS)
    SAVE_TRANSCRIPTS = _saved_tickets.get("save_transcripts", SAVE_TRANSCRIPTS)
    DM_TRANSCRIPT_ON_CLOSE = _saved_tickets.get("dm_transcript", DM_TRANSCRIPT_ON_CLOSE)
    PANEL_TEXT = _saved_tickets.get("panel_text", PANEL_TEXT)
    PANEL_COLOR = _saved_tickets.get("panel_color", PANEL_COLOR)
    if _saved_tickets.get("types"):
        TICKET_TYPES[:] = _saved_tickets["types"]
    WELCOME_TITLE = _saved_tickets.get("welcome_title", WELCOME_TITLE)
    WELCOME_BODY = _saved_tickets.get("welcome_body", WELCOME_BODY)
    WELCOME_COLOR = _saved_tickets.get("welcome_color", WELCOME_COLOR)


@bot.tree.command(name="tickets-settings", description="Configure everything about tickets from one panel.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def tickets_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=tickets_embed(interaction.guild), view=TicketsMainPanel(interaction.user.id), ephemeral=True)



# ============================================================
# Bienvenidas y despedidas: estilo completo desde /welcomes-settings y /despedidas-settings
# ============================================================
WELCOME_STYLE_FILE = DATA_DIR / "welcome_style.json"
GOODBYE_STYLE_FILE = DATA_DIR / "goodbye_style.json"
welcome_style: dict[str, dict] = _load_json_dict(WELCOME_STYLE_FILE)
goodbye_style: dict[str, dict] = _load_json_dict(GOODBYE_STYLE_FILE)

# Migrar los textos personalizados de la versión anterior
for _gid, _text in welcome_text_config.items():
    welcome_style.setdefault(_gid, {}).setdefault("body", _text)
for _gid, _text in goodbye_text_config.items():
    goodbye_style.setdefault(_gid, {}).setdefault("body", _text)


def save_welcome_style() -> None:
    WELCOME_STYLE_FILE.write_text(json.dumps(welcome_style, indent=2), encoding="utf-8")


def save_goodbye_style() -> None:
    GOODBYE_STYLE_FILE.write_text(json.dumps(goodbye_style, indent=2), encoding="utf-8")


def _style_store(kind: str) -> dict:
    return welcome_style if kind == "welcome" else goodbye_style


def _save_style(kind: str) -> None:
    save_welcome_style() if kind == "welcome" else save_goodbye_style()


def _footer_block(text: str) -> str:
    return "\n".join(f"-# {line}" for line in text.splitlines() if line.strip())


def _assemble(head_text: str, st: dict, body: str, footer: str, buttons=None, avatar_url: str | None = None) -> discord.ui.LayoutView:
    thumb = st.get("thumbnail", "avatar")
    children: list = []
    head = discord.ui.TextDisplay(head_text)
    if thumb == "none":
        children.append(head)
    else:
        url = avatar_url if thumb == "avatar" else thumb
        children.append(discord.ui.Section(head, accessory=discord.ui.Thumbnail(url)))
    if st.get("banner"):
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(st["banner"])))
    children += [discord.ui.Separator(), discord.ui.TextDisplay(body), discord.ui.Separator(),
                 discord.ui.TextDisplay(footer)]
    if buttons:
        children += [discord.ui.Separator(), discord.ui.ActionRow(*buttons)]
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_colour=st.get("color") or STEEL))
    return view


def build_welcome_layout(member: discord.Member) -> discord.ui.LayoutView:
    gid = str(member.guild.id)
    st = welcome_style.get(gid, {})
    values = dict(member=member.mention, name=member.display_name, server=WELCOME_SERVER_NAME,
                  count=member.guild.member_count)
    title = (render_text(st["title"], **values) if st.get("title")
             else f"# {E('GE_member', '👋')} Welcome to {WELCOME_SERVER_NAME},")
    body = (render_text(st["body"], **values) if st.get("body")
            else f"{member.mention}\n{WELCOME_DEFAULT_BODY}")
    if st.get("footer"):
        footer = _footer_block(render_text(st["footer"], **values))
    else:
        footer = _footer_block(
            f"{E('GE_member', '👤')} Member: {member.guild.member_count}\n"
            f"{E('GE_rules', '📜')} Please read our rules and guidelines.\n"
            f"{E('transfer', '🔁')} Stay tuned for upcoming updates."
        )
    buttons = [_welcome_button(btn) for btn in welcome_buttons_for(member.guild.id)]
    return _assemble(title, st, body, footer, buttons=buttons, avatar_url=member.display_avatar.url)


def build_goodbye_layout(member: discord.Member) -> discord.ui.LayoutView:
    guild = member.guild
    gid = str(guild.id)
    st = goodbye_style.get(gid, {})
    values = dict(member=member.mention, name=member.display_name, server=server_name(guild),
                  count=guild.member_count)
    title = (render_text(st["title"], **values) if st.get("title")
             else f"# {E('GE_member', '👋')} {tr(guild.id, 'goodbye.title', name=member.display_name)}")
    body = (render_text(st["body"], **values) if st.get("body")
            else tr(guild.id, "goodbye.body", name=member.display_name, server=server_name(guild)))
    footer = (_footer_block(render_text(st["footer"], **values)) if st.get("footer")
              else f"-# {E('GE_member', '👤')} {tr(guild.id, 'goodbye.members', n=guild.member_count)}")
    return _assemble(title, st, body, footer, avatar_url=member.display_avatar.url)


class StyleTextModal(discord.ui.Modal):
    def __init__(self, kind: str, gid: str):
        super().__init__(title=f"{'Welcome' if kind == 'welcome' else 'Goodbye'} text")
        self.kind, self.gid = kind, gid
        st = _style_store(kind).get(gid, {})
        self.title_in = discord.ui.TextInput(label="Title (markdown allowed)", required=False, max_length=200,
                                             default=st.get("title"), placeholder="{member} {server} {name} {count}")
        self.body_in = discord.ui.TextInput(label="Body", style=discord.TextStyle.paragraph, required=False,
                                            max_length=1000, default=st.get("body"),
                                            placeholder="Leave empty for the default text")
        self.footer_in = discord.ui.TextInput(label="Footer (one line each)", style=discord.TextStyle.paragraph,
                                              required=False, max_length=500, default=st.get("footer"),
                                              placeholder="Member: {count}")
        for item in (self.title_in, self.body_in, self.footer_in):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        st = _style_store(self.kind).setdefault(self.gid, {})
        for key, item in (("title", self.title_in), ("body", self.body_in), ("footer", self.footer_in)):
            value = item.value.strip()
            if value:
                st[key] = value
            else:
                st.pop(key, None)
        _save_style(self.kind)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Text saved."), ephemeral=True)


class StyleImagesModal(discord.ui.Modal, title="Images"):
    thumbnail_in = discord.ui.TextInput(label="Thumbnail: avatar, none, or https link", required=False, max_length=300,
                                        placeholder="avatar")
    banner_in = discord.ui.TextInput(label="Banner image: https link (empty = none)", required=False, max_length=300)

    def __init__(self, kind: str, gid: str):
        super().__init__()
        self.kind, self.gid = kind, gid
        st = _style_store(kind).get(gid, {})
        self.thumbnail_in.default = st.get("thumbnail") if st.get("thumbnail") not in (None, "avatar") else None
        self.banner_in.default = st.get("banner")

    async def on_submit(self, interaction: discord.Interaction):
        thumb = self.thumbnail_in.value.strip().lower() or "avatar"
        banner = self.banner_in.value.strip()
        if thumb not in ("avatar", "none") and not thumb.startswith("https://"):
            return await interaction.response.send_message(
                embed=error_notice("The thumbnail must be `avatar`, `none` or an https link."), ephemeral=True)
        if banner and not banner.startswith("https://"):
            return await interaction.response.send_message(
                embed=error_notice("The banner must be an https link."), ephemeral=True)
        st = _style_store(self.kind).setdefault(self.gid, {})
        st["thumbnail"] = thumb
        if banner:
            st["banner"] = banner
        else:
            st.pop("banner", None)
        _save_style(self.kind)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Images saved."), ephemeral=True)


class StyleColorModal(discord.ui.Modal, title="Color"):
    color_in = discord.ui.TextInput(label="Color name or hex (empty = default)", required=False, max_length=20,
                                    placeholder="Blue, Red, Silver... or #3B82F6")

    def __init__(self, kind: str, gid: str):
        super().__init__()
        self.kind, self.gid = kind, gid

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.color_in.value.strip()
        st = _style_store(self.kind).setdefault(self.gid, {})
        if raw:
            try:
                st["color"] = parse_color(raw)
            except ValueError:
                return await interaction.response.send_message(
                    embed=error_notice("Use a color name from the list or a hex code like #3B82F6."), ephemeral=True)
        else:
            st.pop("color", None)
        _save_style(self.kind)
        await interaction.response.send_message(embed=notice(f"{E('true', '✅')} Color saved."), ephemeral=True)


def welcomes_embed(guild: discord.Guild) -> discord.Embed:
    gid = str(guild.id)
    st = welcome_style.get(gid, {})
    buttons = welcome_buttons_for(guild.id)
    button_lines = "\n".join(f"{i}. **{b['label']}** · {b['url']}" for i, b in enumerate(buttons, 1)) or "None"
    rows = [
        ("Channel", _channel_text(guild, welcome_config.get(gid, DEFAULT_WELCOME_CHANNEL_ID))),
        ("Title", "Custom" if st.get("title") else "Default"),
        ("Body", "Custom" if st.get("body") else "Default"),
        ("Footer", "Custom" if st.get("footer") else "Default"),
        ("Thumbnail", st.get("thumbnail", "avatar")),
        ("Banner", st.get("banner", "None")),
        ("Color", f"#{st['color']:06X}" if st.get("color") else "Default"),
        ("Buttons", button_lines),
    ]
    return _settings_embed("Welcome settings", rows)


def goodbyes_embed(guild: discord.Guild) -> discord.Embed:
    gid = str(guild.id)
    st = goodbye_style.get(gid, {})
    rows = [
        ("Channel", _channel_text(guild, goodbye_config.get(gid))),
        ("Title", "Custom" if st.get("title") else "Default"),
        ("Body", "Custom" if st.get("body") else "Default"),
        ("Footer", "Custom" if st.get("footer") else "Default"),
        ("Thumbnail", st.get("thumbnail", "avatar")),
        ("Banner", st.get("banner", "None")),
        ("Color", f"#{st['color']:06X}" if st.get("color") else "Default"),
    ]
    return _settings_embed("Goodbye settings", rows)


class WelcomeButtonsPanel(SettingsPanel):
    def render(self, guild):
        embed = welcomes_embed(guild)
        embed.title = "Welcome buttons"
        return embed

    @discord.ui.button(label="Add / edit button", style=discord.ButtonStyle.primary, row=0)
    async def add_button(self, interaction, button):
        await interaction.response.send_modal(WelcomeButtonModal())

    @discord.ui.button(label="Remove button", style=discord.ButtonStyle.secondary, row=0)
    async def remove_button(self, interaction, button):
        await interaction.response.send_modal(WelcomeButtonRemoveModal())

    @discord.ui.button(label="Reset buttons", style=discord.ButtonStyle.secondary, row=0)
    async def reset_buttons(self, interaction, button):
        welcome_buttons_config.pop(str(interaction.guild_id), None)
        save_welcome_buttons()
        await self.show(interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        await interaction.response.edit_message(embed=welcomes_embed(interaction.guild),
                                                view=WelcomesPanel(self.owner_id))


class WelcomesPanel(SettingsPanel):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(ChannelPick("Pick the welcome channel", self._set_channel))

    def render(self, guild):
        return welcomes_embed(guild)

    async def _set_channel(self, interaction, channel_id: int):
        welcome_config[str(interaction.guild_id)] = channel_id
        save_welcomes()
        await self.show(interaction)

    @discord.ui.button(label="Turn off", style=discord.ButtonStyle.danger, row=1)
    async def turn_off(self, interaction, button):
        welcome_config[str(interaction.guild_id)] = None
        save_welcomes()
        await self.show(interaction)

    @discord.ui.button(label="Default channel", style=discord.ButtonStyle.secondary, row=1)
    async def default_channel(self, interaction, button):
        welcome_config.pop(str(interaction.guild_id), None)
        save_welcomes()
        await self.show(interaction)

    @discord.ui.button(label="Text", style=discord.ButtonStyle.primary, row=1)
    async def text(self, interaction, button):
        await interaction.response.send_modal(StyleTextModal("welcome", str(interaction.guild_id)))

    @discord.ui.button(label="Images", style=discord.ButtonStyle.primary, row=1)
    async def images(self, interaction, button):
        await interaction.response.send_modal(StyleImagesModal("welcome", str(interaction.guild_id)))

    @discord.ui.button(label="Color", style=discord.ButtonStyle.primary, row=1)
    async def color(self, interaction, button):
        await interaction.response.send_modal(StyleColorModal("welcome", str(interaction.guild_id)))

    @discord.ui.button(label="Buttons", style=discord.ButtonStyle.primary, row=2)
    async def buttons(self, interaction, button):
        await interaction.response.edit_message(embed=welcomes_embed(interaction.guild),
                                                view=WelcomeButtonsPanel(self.owner_id))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction, button):
        await interaction.response.send_message(view=build_welcome_layout(interaction.user), ephemeral=True)

    @discord.ui.button(label="Reset all", style=discord.ButtonStyle.danger, row=2)
    async def reset_all(self, interaction, button):
        gid = str(interaction.guild_id)
        welcome_style.pop(gid, None)
        save_welcome_style()
        welcome_buttons_config.pop(gid, None)
        save_welcome_buttons()
        await self.show(interaction)


class GoodbyesPanel(SettingsPanel):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        self.add_item(ChannelPick("Pick the goodbye channel", self._set_channel))

    def render(self, guild):
        return goodbyes_embed(guild)

    async def _set_channel(self, interaction, channel_id: int):
        goodbye_config[str(interaction.guild_id)] = channel_id
        save_goodbyes()
        await self.show(interaction)

    @discord.ui.button(label="Turn off", style=discord.ButtonStyle.danger, row=1)
    async def turn_off(self, interaction, button):
        goodbye_config.pop(str(interaction.guild_id), None)
        save_goodbyes()
        await self.show(interaction)

    @discord.ui.button(label="Text", style=discord.ButtonStyle.primary, row=1)
    async def text(self, interaction, button):
        await interaction.response.send_modal(StyleTextModal("goodbye", str(interaction.guild_id)))

    @discord.ui.button(label="Images", style=discord.ButtonStyle.primary, row=1)
    async def images(self, interaction, button):
        await interaction.response.send_modal(StyleImagesModal("goodbye", str(interaction.guild_id)))

    @discord.ui.button(label="Color", style=discord.ButtonStyle.primary, row=1)
    async def color(self, interaction, button):
        await interaction.response.send_modal(StyleColorModal("goodbye", str(interaction.guild_id)))

    @discord.ui.button(label="Preview", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction, button):
        await interaction.response.send_message(view=build_goodbye_layout(interaction.user), ephemeral=True)

    @discord.ui.button(label="Reset all", style=discord.ButtonStyle.danger, row=2)
    async def reset_all(self, interaction, button):
        goodbye_style.pop(str(interaction.guild_id), None)
        save_goodbye_style()
        await self.show(interaction)


@bot.tree.command(name="welcomes-settings", description="Configure welcomes: channel, text, images, color and buttons.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def welcomes_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=welcomes_embed(interaction.guild), view=WelcomesPanel(interaction.user.id), ephemeral=True)


@bot.tree.command(name="despedidas-settings", description="Configure goodbyes: channel, text, images and color.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def despedidas_settings(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=goodbyes_embed(interaction.guild), view=GoodbyesPanel(interaction.user.id), ephemeral=True)


@bot.command(name="resync")
@commands.is_owner()
async def resync_prefix(ctx: commands.Context):
    if ctx.guild is None:
        return
    bot.tree.clear_commands(guild=ctx.guild)
    await bot.tree.sync(guild=ctx.guild)
    bot.tree.copy_global_to(guild=ctx.guild)
    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.reply(
        embed=notice(f"{E('true', '✅')} {len(synced)} commands synced. If they still look old, close and reopen Discord."),
        mention_author=False,
    )




if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to your .env file.")
    bot.run(TOKEN)
