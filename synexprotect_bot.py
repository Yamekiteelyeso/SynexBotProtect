"""
SynexProtectBot - Discord utility & moderation helper bot.

Requirements:
    pip install -U discord.py python-dotenv deep-translator

Create a .env file next to this script:
    DISCORD_TOKEN=your_bot_token_here

Enable these in the Discord Developer Portal -> Bot:
    - SERVER MEMBERS INTENT
    - MESSAGE CONTENT INTENT  (required for prefix commands like !ping)
"""

import asyncio
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
BOT_VERSION = "1.3.0"

# Palette: black / charcoal / slate / steel / silver
INK = 0x0B0C0E          # near black
CHARCOAL = 0x1A1C20
SLATE = 0x2A2E35
STEEL = 0x4A505A
SILVER = 0x9AA1AC
ERROR = 0x4B1D1D        # muted dark red, only for errors

START_TIME = datetime.now(timezone.utc)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None, case_insensitive=True)

giveaways: dict[int, dict] = {}

# Reaction roles: {guild_id: [{"emoji": key, "role_id": int, "message_id": int | None}, ...]}
REACTION_ROLES_FILE = Path(__file__).with_name("reaction_roles.json")
reaction_roles: dict[str, list[dict]] = {}

EMOJI_MARKUP_RE = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")
EMOJI_NAME_RE = re.compile(r":?([A-Za-z0-9_]{2,32}):?")
DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
DURATION_TOKEN_RE = re.compile(r"(?:\d+[smhdw])+", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
LETTERS = ["🇦", "🇧", "🇨", "🇩", "🇪"]


# ---------------------------------------------------------------- helpers

def base_embed(title: str | None = None, description: str | None = None, color: int = CHARCOAL) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    if bot.user:
        embed.set_author(name=BOT_NAME, icon_url=bot.user.display_avatar.url)
    embed.set_footer(text=f"{BOT_NAME} · v{BOT_VERSION}")
    return embed


def notice(text: str, color: int = CHARCOAL) -> discord.Embed:
    """Short, untitled embed used for confirmations and small messages."""
    return discord.Embed(description=text, color=color)


def error_notice(text: str) -> discord.Embed:
    return discord.Embed(description=f"⚠️ {text}", color=ERROR)


def load_reaction_roles() -> None:
    global reaction_roles
    try:
        reaction_roles = json.loads(REACTION_ROLES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        reaction_roles = {}


def save_reaction_roles() -> None:
    REACTION_ROLES_FILE.write_text(json.dumps(reaction_roles, indent=2), encoding="utf-8")


def emoji_key_from_partial(emoji: discord.PartialEmoji) -> str:
    return f"c{emoji.id}" if emoji.id else str(emoji.name)


def emoji_key_from_input(text: str) -> str | None:
    """Turns '<:name:123>' into a custom key, or a unicode emoji into itself."""
    text = text.strip()
    match = EMOJI_MARKUP_RE.fullmatch(text)
    if match:
        return f"c{match.group(3)}"
    if text and not re.search(r"[A-Za-z0-9]", text):
        return text  # unicode emoji have no letters/digits
    return None


def parse_color(value: str | None) -> int:
    if not value:
        return CHARCOAL
    value = value.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return int(value, 16)
    raise ValueError("invalid color")


def parse_duration(text: str) -> int | None:
    """Accepts formats like 30s, 10m, 2h, 1d, 1h30m."""
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
    await bot.tree.sync()
    print(f"{BOT_NAME} online as {bot.user} ({len(bot.guilds)} servers)")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Silently ignore unknown commands and failed permission checks on prefix commands.
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure, commands.NoPrivateMessage)):
        return
    print(f"[prefix error] {error}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or payload.member is None or payload.member.bot:
        return

    rules = reaction_roles.get(str(payload.guild_id), [])
    key = emoji_key_from_partial(payload.emoji)
    rule = next(
        (r for r in rules if r["emoji"] == key and r["message_id"] in (None, payload.message_id)),
        None,
    )
    if rule is None:
        return

    guild = bot.get_guild(payload.guild_id)
    role = guild.get_role(rule["role_id"]) if guild else None
    if role is None:
        return

    member = payload.member
    if role in member.roles:
        return

    try:
        await member.add_roles(role, reason="Reaction role")
    except discord.HTTPException as exc:
        print(f"[reaction roles] could not add role: {exc}")
        return

    # Confirmation only the member sees: a DM, or a self-deleting notice if DMs are closed.
    text = f"✅ Role **{role.name}** granted."
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
    await interaction.response.send_message(notice(f"✅ Message sent to {target.mention}."), ephemeral=True)


# ---------------------------------------------------------------- /embed (admin)

@bot.tree.command(name="embed", description="Send a custom embed. Every field is optional.")
@app_commands.describe(
    title="Embed title",
    description="Embed body text",
    color="Hex color, e.g. 2B2D31",
    footer="Small text at the bottom",
    image="Upload a picture to show inside the embed",
    image_url="Or paste a direct image link",
)
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
            embed=error_notice("Invalid color. Use a 6-digit hex value such as `2B2D31`."), ephemeral=True
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
        embed.description = "​"  # Discord requires some content

    await interaction.channel.send(embed=embed)
    await interaction.response.send_message(notice("✅ Embed sent."), ephemeral=True)


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
        # Fall back to an emoji the bot can already see, by name.
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

@bot.tree.command(name="addemojirole", description="Give a role when members react with an emoji.")
@app_commands.describe(
    emoji="The emoji members will react with",
    role="The role to give",
    message_id="Optional: only work on this message ID (default: any message)",
)
@app_commands.default_permissions(manage_roles=True)
@app_commands.guild_only()
async def addemojirole(
    interaction: discord.Interaction,
    emoji: str,
    role: discord.Role,
    message_id: str | None = None,
):
    me = interaction.guild.me
    if role.is_default() or role.managed or role >= me.top_role:
        return await interaction.response.send_message(
            error_notice("I can't manage that role. Make sure it's below my highest role and isn't managed by an integration."),
            ephemeral=True,
        )

    key = emoji_key_from_input(emoji)
    if key is None:
        return await interaction.response.send_message(
            error_notice("Invalid emoji. Paste the emoji itself."), ephemeral=True
        )

    msg_id = None
    if message_id:
        try:
            msg_id = int(message_id.strip())
        except ValueError:
            return await interaction.response.send_message(error_notice("Invalid message ID."), ephemeral=True)

    guild_key = str(interaction.guild_id)
    rules = reaction_roles.setdefault(guild_key, [])
    rules[:] = [r for r in rules if not (r["emoji"] == key and r["message_id"] == msg_id)]
    rules.append({"emoji": key, "role_id": role.id, "message_id": msg_id})
    save_reaction_roles()

    scope = f"message `{msg_id}`" if msg_id else "any message"
    embed = base_embed("🏷️ Reaction role saved", color=CHARCOAL)
    embed.add_field(name="Emoji", value=emoji, inline=True)
    embed.add_field(name="Role", value=role.mention, inline=True)
    embed.add_field(name="Works on", value=scope, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- /ping

@bot.tree.command(name="ping", description="Show the bot's current latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_ping_embed())


@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    await ctx.send(embed=build_ping_embed())


# ---------------------------------------------------------------- /serverinfo  (prefix: !server)

@bot.tree.command(name="serverinfo", description="Show statistics and information about this server.")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_serverinfo_embed(interaction.guild))


@bot.command(name="server")
@commands.guild_only()
async def server_prefix(ctx: commands.Context):
    await ctx.send(embed=build_serverinfo_embed(ctx.guild))


# ---------------------------------------------------------------- /userinfo  (prefix: !user)

@bot.tree.command(name="userinfo", description="Show details about a user.")
@app_commands.describe(member="The user to inspect (default: you)")
@app_commands.guild_only()
async def userinfo(interaction: discord.Interaction, member: discord.Member | None = None):
    await interaction.response.send_message(embed=build_userinfo_embed(member or interaction.user))


@bot.command(name="user")
@commands.guild_only()
async def user_prefix(ctx: commands.Context, member: Optional[discord.Member] = None):
    await ctx.send(embed=build_userinfo_embed(member or ctx.author))


# ---------------------------------------------------------------- /botinfo  (prefix: !botinfo)

@bot.tree.command(name="botinfo", description="Show statistics about the bot.")
async def botinfo(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_botinfo_embed())


@bot.command(name="botinfo")
async def botinfo_prefix(ctx: commands.Context):
    await ctx.send(embed=build_botinfo_embed())


# ---------------------------------------------------------------- /avatar  (prefix: !avatar)

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
    ("remind", "Schedule a reminder for you or a channel.", "/remind time reminder [channel]"),
    ("translate", "Translate text into another language.", "/translate language text"),
]

# (name, description, usage, required permission)
ADMIN_COMMANDS = [
    ("poll", "Public poll with live results and up to five options.", "/poll question option1 option2 [option3] [option4] [option5]", "Manage Messages"),
    ("bot-say", "Send a message without revealing who sent it.", "/bot-say message [channel]", "Manage Messages"),
    ("embed", "Send a custom embed with color, footer and image.", "/embed [title] [description] [color] [footer] [image] [image_url]", "Manage Messages"),
    ("emojisteal", "Copy a custom emoji from another server into this one.", "/emojisteal emoji [name]", "Manage Expressions"),
    ("addemojirole", "Give a role when members react with an emoji.", "/addemojirole emoji role [message_id]", "Manage Roles"),
    ("giveaway create", "Start a giveaway with a join button and live entries.", "/giveaway create prize duration [winners]  ·  !giveway <prize> <duration> [winners]", "Manage Server"),
    ("giveaway end", "End a giveaway early and pick the winner(s).", "/giveaway end message_id", "Manage Server"),
    ("giveaway reroll", "Pick a new winner from an ended giveaway.", "/giveaway reroll message_id  ·  !reroll (reply to the giveaway)", "Manage Server"),
]

PREFIX_MAP = {
    "ping": "ping",
    "serverinfo": "server",
    "userinfo": "user",
    "botinfo": "botinfo",
    "avatar": "avatar",
    "help": "help",
}


class CommandSelect(discord.ui.Select):
    """Dropdown that shows the usage of a command from a given list."""

    def __init__(self, owner_id: int, entries: list[tuple], admin: bool):
        self.owner_id = owner_id
        self.entries = {e[0]: e for e in entries}
        self.admin = admin
        options = [
            discord.SelectOption(label=f"/{e[0]}", description=e[1][:100], value=e[0])
            for e in entries
        ]
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
        embed=build_help_embed(),
        view=CommandView(interaction.user.id, PUBLIC_COMMANDS),
        ephemeral=True,
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
    await ctx.send(
        embed=build_helpadmin_embed(),
        view=CommandView(ctx.author.id, ADMIN_COMMANDS, admin=True),
    )


# ---------------------------------------------------------------- /poll (admin, public votes)

class PollView(discord.ui.View):
    """Public poll: anyone can vote and results update live. Only admins can create polls."""

    def __init__(self, question: str, options: list[str]):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.user_choice: dict[int, int] = {}

        for index, label in enumerate(options):
            button = discord.ui.Button(
                label=label[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll:{uuid.uuid4().hex}:{index}",
                emoji=LETTERS[index],
            )
            button.callback = self._make_vote_callback(index)
            self.add_item(button)

    def _make_vote_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if self.user_choice.get(user_id) == index:
                del self.user_choice[user_id]          # click the same option again to remove the vote
            else:
                self.user_choice[user_id] = index
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def counts(self) -> list[int]:
        counts = [0] * len(self.options)
        for choice in self.user_choice.values():
            counts[choice] += 1
        return counts

    def build_embed(self) -> discord.Embed:
        counts = self.counts()
        total = sum(counts)
        lines = []
        for i, option in enumerate(self.options):
            percent = (counts[i] / total * 100) if total else 0
            lines.append(
                f"{LETTERS[i]}  **{option}**\n"
                f"`{progress_bar(percent)}`  **{percent:.0f}%**  ·  {counts[i]} vote{'s' if counts[i] != 1 else ''}"
            )

        embed = base_embed(f"📊  {self.question}", "\n\n".join(lines), SLATE)
        embed.set_footer(text=f"{total} total vote{'s' if total != 1 else ''} · Click an option to vote · Click again to remove")
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


# ---------------------------------------------------------------- /remind

async def _send_reminder(channel: discord.abc.Messageable, user: discord.abc.User, text: str, delay: int):
    await asyncio.sleep(delay)
    embed = base_embed("⏰ Reminder", text, STEEL)
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    try:
        await channel.send(content=user.mention, embed=embed)
    except discord.HTTPException as exc:
        print(f"[remind] could not send reminder: {exc}")


@bot.tree.command(name="remind", description="Schedule a reminder for you or a channel.")
@app_commands.describe(
    time="When to remind, e.g. 10m, 2h, 1d or 1h30m",
    reminder="What to remind about",
    channel="Channel to post the reminder in (default: this one)",
)
@app_commands.guild_only()
async def remind(
    interaction: discord.Interaction,
    time: str,
    reminder: str,
    channel: discord.TextChannel | None = None,
):
    seconds = parse_duration(time)
    if seconds is None or seconds < 5 or seconds > 30 * 86400:
        return await interaction.response.send_message(
            embed=error_notice("Use a time between 5 seconds and 30 days, e.g. `10m`, `2h`, `1d`."),
            ephemeral=True,
        )

    target = channel or interaction.channel
    asyncio.create_task(_send_reminder(target, interaction.user, reminder, seconds))
    embed = base_embed("⏰ Reminder scheduled", color=STEEL)
    embed.add_field(name="When", value=f"In {fmt_seconds(seconds)}", inline=True)
    embed.add_field(name="Where", value=target.mention, inline=True)
    embed.add_field(name="Message", value=reminder, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- /translate

@bot.tree.command(name="translate", description="Translate a text into another language.")
@app_commands.describe(
    language="Target language code, e.g. en, es, fr, ja, de",
    text="The text to translate",
)
async def translate(interaction: discord.Interaction, language: str, text: str):
    await interaction.response.defer(ephemeral=True)
    try:
        translated = await asyncio.to_thread(
            GoogleTranslator(source="auto", target=language.strip().lower()).translate, text
        )
    except Exception:
        return await interaction.followup.send(
            embed=error_notice("Could not translate. Check the language code (e.g. `en`, `es`)."),
            ephemeral=True,
        )

    embed = base_embed("🌐 Translation", color=CHARCOAL)
    embed.add_field(name="Original", value=text[:1024], inline=False)
    embed.add_field(name=f"Translated · `{language.lower()}`", value=(translated or "—")[:1024], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- /addemojirole is defined above

# ---------------------------------------------------------------- giveaways (admin)

def build_giveaway_embed(data: dict) -> discord.Embed:
    host = f"<@{data['host_id']}>"
    entries = f"{len(data['entries']):,}"

    if data["ended"]:
        winners = data["last_winners"]
        winner_text = "  ".join(f"<@{w}>" for w in winners) if winners else "No valid entries"
        embed = base_embed(f"🎉  {data['prize']}", "This giveaway has ended.", INK)
        embed.add_field(name="🏆  Winner" + ("s" if len(winners) > 1 else ""), value=winner_text, inline=False)
        embed.add_field(name="👥  Entries", value=entries, inline=True)
        embed.add_field(name="🎁  Hosted by", value=host, inline=True)
        return embed

    embed = base_embed(
        f"🎉  {data['prize']}",
        "Press **Enter giveaway** below to join.\n​",
        INK,
    )
    embed.add_field(name="⏳  Ends", value=f"<t:{data['ends_at']}:R>", inline=True)
    embed.add_field(name="👥  Entries", value=entries, inline=True)
    embed.add_field(name="🏅  Winners", value=str(data["winners"]), inline=True)
    embed.add_field(name="🎁  Hosted by", value=host, inline=False)
    return embed


class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.gid: int | None = None

    @discord.ui.button(label="Enter giveaway", emoji="🎟️", style=discord.ButtonStyle.secondary, custom_id="giveaway:enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = giveaways.get(self.gid)
        if not data or data["ended"]:
            return await interaction.response.send_message(notice("This giveaway has ended."), ephemeral=True)

        uid = interaction.user.id
        if uid in data["entries"]:
            data["entries"].discard(uid)
            msg = "You left the giveaway."
        else:
            data["entries"].add(uid)
            msg = "✅ You're entered!"

        await interaction.response.edit_message(embed=build_giveaway_embed(data), view=self)
        await interaction.followup.send(notice(msg), ephemeral=True)


def _disabled(view: discord.ui.View) -> discord.ui.View:
    for item in view.children:
        item.disabled = True
    return view


async def _finish_giveaway(gid: int, pick: int | None = None, exclude: set[int] | None = None) -> list[int] | None:
    data = giveaways.get(gid)
    if not data:
        return None

    pool = [u for u in data["entries"] if not exclude or u not in exclude]
    count = pick if pick is not None else data["winners"]
    winners = random.sample(pool, min(count, len(pool))) if pool else []

    data["ended"] = True
    data["last_winners"] = winners

    channel = bot.get_channel(data["channel_id"])
    if channel:
        try:
            message = await channel.fetch_message(gid)
            await message.edit(embed=build_giveaway_embed(data), view=_disabled(GiveawayView()))
        except discord.HTTPException:
            pass

        if winners:
            mentions = " ".join(f"<@{w}>" for w in winners)
            await channel.send(
                content=mentions,
                embed=base_embed(
                    "🏆  Winner" + ("s" if len(winners) > 1 else ""),
                    f"Congratulations {mentions}! You won **{data['prize']}**.",
                    SLATE,
                ),
            )
        else:
            await channel.send(embed=base_embed("🎉  Giveaway ended", "No valid entries were found.", STEEL))
    return winners


async def _auto_end(gid: int, delay: int):
    await asyncio.sleep(delay)
    data = giveaways.get(gid)
    if data and not data["ended"]:
        await _finish_giveaway(gid)


def _new_giveaway_data(host_id: int, channel_id: int, prize: str, seconds: int, winners: int) -> dict:
    return {
        "prize": prize,
        "winners": winners,
        "entries": set(),
        "ended": False,
        "last_winners": [],
        "host_id": host_id,
        "channel_id": channel_id,
        "ends_at": int(datetime.now(timezone.utc).timestamp()) + seconds,
        "seconds": seconds,
    }


def _register_giveaway(message: discord.Message, view: GiveawayView, data: dict) -> None:
    view.gid = message.id
    giveaways[message.id] = data
    asyncio.create_task(_auto_end(message.id, data["seconds"]))


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
    duration="How long it lasts, e.g. 30m, 2h, 1d or 1h30m",
    winners="Number of winners (1-20, default 1)",
)
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_create(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    winners: app_commands.Range[int, 1, 20] = 1,
):
    seconds = parse_duration(duration)
    if seconds is None or seconds < 10 or seconds > 30 * 86400:
        return await interaction.response.send_message(
            embed=error_notice("Use a duration between 10 seconds and 30 days, e.g. `1h` or `2d`."),
            ephemeral=True,
        )

    data = _new_giveaway_data(interaction.user.id, interaction.channel_id, prize, seconds, winners)
    view = GiveawayView()
    await interaction.response.send_message(embed=build_giveaway_embed(data), view=view)
    message = await interaction.original_response()
    _register_giveaway(message, view, data)


@giveaway_group.command(name="end", description="End a giveaway early and pick the winner(s).")
@app_commands.describe(message_id="ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    data = giveaways.get(gid) if gid else None
    if not data:
        return await interaction.response.send_message(error_notice("No giveaway found with that ID."), ephemeral=True)
    if data["ended"]:
        return await interaction.response.send_message(
            error_notice("This giveaway has already ended. Use `/giveaway reroll` instead."), ephemeral=True
        )

    await interaction.response.send_message(notice("Ending giveaway…"), ephemeral=True)
    await _finish_giveaway(gid)


async def _reroll(gid: int) -> tuple[str | None, list[int] | None]:
    data = giveaways.get(gid)
    if not data:
        return "No giveaway found for that message.", None
    if not data["ended"]:
        return "This giveaway is still running. End it first with `/giveaway end`.", None

    previous = set(data["last_winners"])
    new_winners = await _finish_giveaway(gid, pick=1, exclude=previous)
    if not new_winners:
        return "No eligible entries left to reroll.", None
    return None, new_winners


@giveaway_group.command(name="reroll", description="Pick a new winner for an ended giveaway.")
@app_commands.describe(message_id="ID of the giveaway message")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    if gid is None:
        return await interaction.response.send_message(error_notice("Invalid message ID."), ephemeral=True)

    error, _ = await _reroll(gid)
    if error:
        return await interaction.response.send_message(error_notice(error), ephemeral=True)
    await interaction.response.send_message(notice("✅ New winner selected."), ephemeral=True)


def parse_giveaway_args(args: str) -> tuple[str, str, int] | None:
    """Parses '<prize words> <duration> [winners]' from the end of the text."""
    tokens = args.split()
    winners = 1
    if tokens and tokens[-1].isdigit():
        winners = int(tokens.pop())
    if len(tokens) < 2 or not DURATION_TOKEN_RE.fullmatch(tokens[-1]):
        return None
    duration = tokens.pop()
    prize = " ".join(tokens).strip()
    if not prize:
        return None
    return prize, duration, winners


@bot.command(name="giveway", aliases=["giveaway"])
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def giveway_prefix(ctx: commands.Context, *, args: str = ""):
    parsed = parse_giveaway_args(args)
    if parsed is None:
        return await ctx.send(
            embed=error_notice("Usage: `!giveway <prize> <duration> [winners]`, e.g. `!giveway Nitro 1h 2`")
        )

    prize, duration, winners = parsed
    seconds = parse_duration(duration)
    if seconds is None or seconds < 10 or seconds > 30 * 86400:
        return await ctx.send(error_notice("Use a duration between 10 seconds and 30 days, e.g. `1h` or `2d`."))
    if not 1 <= winners <= 20:
        return await ctx.send(error_notice("Winners must be between 1 and 20."))

    data = _new_giveaway_data(ctx.author.id, ctx.channel.id, prize, seconds, winners)
    view = GiveawayView()
    message = await ctx.send(embed=build_giveaway_embed(data), view=view)
    _register_giveaway(message, view, data)


@bot.command(name="reroll")
@commands.guild_only()
@commands.has_permissions(manage_guild=True)
async def reroll_prefix(ctx: commands.Context):
    ref = ctx.message.reference
    if ref is None or ref.message_id is None:
        return await ctx.send(error_notice("Reply to a giveaway message with `!reroll`."))

    error, _ = await _reroll(ref.message_id)
    if error:
        return await ctx.send(error_notice(error))
    await ctx.send(notice("✅ New winner selected."))


# ---------------------------------------------------------------- run

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to your .env file.")
    bot.run(TOKEN)
