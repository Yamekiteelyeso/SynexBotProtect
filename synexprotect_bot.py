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
import os
import platform
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

BOT_NAME = "SynexProtectBot"
BOT_VERSION = "1.1.0"
COLOR = 0x2B2D31          # dark gray
COLOR_SOFT = 0x1E1F22     # near black
COLOR_TEXT = 0x949BA4     # muted gray

START_TIME = datetime.now(timezone.utc)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None, case_insensitive=True)

giveaways: dict[int, dict] = {}

EMOJI_MARKUP_RE = re.compile(r"<(a?):([A-Za-z0-9_]+):(\d+)>")
EMOJI_NAME_RE = re.compile(r":?([A-Za-z0-9_]{2,32}):?")


# ---------------------------------------------------------------- helpers

def base_embed(title: str | None = None, description: str | None = None, color: int = COLOR) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=BOT_NAME)
    return embed


def parse_color(value: str | None) -> int:
    if not value:
        return COLOR
    value = value.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return int(value, 16)
    raise ValueError("invalid color")


DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


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
# These are used by both the slash commands and the prefix commands.

def build_ping_embed() -> discord.Embed:
    ms = round(bot.latency * 1000)
    status = "Excellent" if ms < 100 else "Good" if ms < 200 else "Degraded"
    embed = base_embed("⚡ Pong", color=COLOR)
    embed.add_field(name="Latency", value=f"`{ms} ms`", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    return embed


def build_serverinfo_embed(guild: discord.Guild) -> discord.Embed:
    roles = [r for r in guild.roles if not r.is_default()]
    humans = sum(1 for m in guild.members if not m.bot)
    bots = sum(1 for m in guild.members if m.bot)

    embed = base_embed(guild.name, guild.description or None, COLOR)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="Boost Level", value=f"{guild.premium_tier} · {guild.premium_subscription_count} boosts", inline=True)
    embed.add_field(name="Verification", value=str(guild.verification_level).title(), inline=True)
    embed.add_field(name="Members", value=f"{guild.member_count:,} total\n{humans:,} humans · {bots:,} bots", inline=True)
    embed.add_field(name="Channels", value=f"{len(guild.text_channels)} text · {len(guild.voice_channels)} voice", inline=True)
    embed.add_field(name="Roles", value=str(len(roles)), inline=True)
    embed.add_field(
        name="Created",
        value=f"{discord.utils.format_dt(guild.created_at, 'D')}\n{discord.utils.format_dt(guild.created_at, 'R')}",
        inline=False,
    )
    embed.add_field(name="Server ID", value=f"`{guild.id}`", inline=False)
    return embed


def build_userinfo_embed(member: discord.Member) -> discord.Embed:
    roles = [r for r in reversed(member.roles) if not r.is_default()]
    role_text = " ".join(r.mention for r in roles[:15]) + (f" +{len(roles) - 15} more" if len(roles) > 15 else "")

    embed = base_embed(str(member), color=member.color if member.color.value else COLOR)
    embed.set_thumbnail(url=member.display_avatar.replace(size=1024).url)
    embed.add_field(name="Display Name", value=member.display_name, inline=True)
    embed.add_field(name="User ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(member.joined_at, "D") if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Account Created", value=discord.utils.format_dt(member.created_at, "D"), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=role_text or "None", inline=False)
    return embed


def build_botinfo_embed() -> discord.Embed:
    uptime = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    total_users = sum(g.member_count or 0 for g in bot.guilds)

    embed = base_embed(f"🤖 {BOT_NAME}", "Utility and protection bot for your community.", COLOR)
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="Uptime", value=fmt_seconds(uptime), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Version", value=BOT_VERSION, inline=True)
    embed.add_field(name="Servers", value=f"{len(bot.guilds):,}", inline=True)
    embed.add_field(name="Users Reached", value=f"{total_users:,}", inline=True)
    embed.add_field(name="Commands", value=str(len(bot.tree.get_commands())), inline=True)
    embed.add_field(
        name="Libraries",
        value=f"discord.py `{discord.__version__}`\nPython `{platform.python_version()}`",
        inline=False,
    )
    return embed


def build_avatar(user: discord.abc.User) -> tuple[discord.Embed, discord.ui.View]:
    url = user.display_avatar.with_size(4096).url
    embed = base_embed(f"🖼️ {user.display_name}'s avatar", color=COLOR)
    embed.set_image(url=url)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Download", url=url, style=discord.ButtonStyle.link))
    return embed, view


# ---------------------------------------------------------------- events

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{BOT_NAME} online as {bot.user} ({len(bot.guilds)} servers)")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        text = "You don't have permission to use this command."
    elif isinstance(error, app_commands.BotMissingPermissions):
        text = "I'm missing the permissions needed to run this command."
    else:
        text = "An unexpected error occurred. Please try again."
        print(f"[error] {error}")

    embed = base_embed(description=text, color=COLOR_SOFT)
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
    await interaction.response.send_message(
        embed=base_embed(description=f"Message sent to {target.mention}.", color=COLOR_SOFT),
        ephemeral=True,
    )


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
            embed=base_embed(description="Invalid color. Use a 6-digit hex value such as `2B2D31`.", color=COLOR_SOFT),
            ephemeral=True,
        )

    if image and not (image.content_type or "").startswith("image/"):
        return await interaction.response.send_message(
            embed=base_embed(description="The attached file must be an image.", color=COLOR_SOFT),
            ephemeral=True,
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
    await interaction.response.send_message(
        embed=base_embed(description="✅ Embed sent.", color=COLOR_SOFT), ephemeral=True
    )


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
        # Fall back to finding an emoji the bot can see by its name.
        name_match = EMOJI_NAME_RE.fullmatch(emoji.strip())
        if name_match:
            wanted = name_match.group(1).lower()
            found = next((e for e in bot.emojis if e.name.lower() == wanted), None)
            if found:
                partial = discord.PartialEmoji(animated=found.animated, name=found.name, id=found.id)

    if partial is None:
        return await interaction.followup.send(
            embed=base_embed(
                description="I couldn't find that emoji. Paste the emoji itself, or use a name from a server the bot is in.",
                color=COLOR_SOFT,
            ),
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
            embed=base_embed(description=f"Could not add the emoji: {exc.text or 'the server may be full.'}", color=COLOR_SOFT),
            ephemeral=True,
        )

    await interaction.followup.send(
        embed=base_embed("😎 Emoji added", f"{created} `:{created.name}:`", COLOR),
        ephemeral=True,
    )


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


# ---------------------------------------------------------------- /help  (prefix: !help)

# (name, description, usage, admin_only)
COMMANDS_INFO = [
    ("ping", "Show the bot's current latency.", "/ping · !ping", False),
    ("serverinfo", "Show statistics and information about this server.", "/serverinfo · !server", False),
    ("userinfo", "Show details about a user.", "/userinfo [member] · !user [member]", False),
    ("botinfo", "Show statistics about the bot.", "/botinfo · !botinfo", False),
    ("avatar", "Show a user's avatar at full size with a download link.", "/avatar [member] · !avatar [member]", False),
    ("help", "Show this interactive command list.", "/help · !help", False),
    ("poll", "Create an interactive poll with up to 5 options.", "/poll question option1 option2 [option3] [option4] [option5]", False),
    ("remind", "Schedule a reminder for you or a channel.", "/remind time reminder [channel]", False),
    ("translate", "Translate a text into another language.", "/translate language text", False),
    # Admin commands (hidden from /help)
    ("bot-say", "Send a message without revealing who sent it.", "/bot-say message: [channel]", True),
    ("embed", "Send a custom embed with optional color, footer and image.", "/embed [title] [description] [color] [footer] [image]", True),
    ("emojisteal", "Copy a custom emoji from another server into this one.", "/emojisteal emoji [name]", True),
    ("giveaway start", "Start a giveaway with a time limit and a join button.", "/giveaway start prize duration [winners]", True),
    ("giveaway reroll", "Pick a new winner if the previous one did not claim the prize.", "/giveaway reroll message_id", True),
    ("giveaway end", "End a giveaway early and pick the winner(s).", "/giveaway end message_id", True),
]

PUBLIC_COMMANDS = [c for c in COMMANDS_INFO if not c[3]]

PREFIX_MAP = {
    "ping": "ping",
    "serverinfo": "server",
    "userinfo": "user",
    "botinfo": "botinfo",
    "avatar": "avatar",
    "help": "help",
}


class HelpSelect(discord.ui.Select):
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        options = [
            discord.SelectOption(label=f"/{name}", description=desc[:100], value=name)
            for name, desc, _, _ in PUBLIC_COMMANDS
        ]
        super().__init__(placeholder="Select a command to see its usage...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("This menu belongs to someone else.", ephemeral=True)
        name = self.values[0]
        _, desc, usage, _ = next(c for c in PUBLIC_COMMANDS if c[0] == name)
        embed = base_embed(f"/{name}", desc, COLOR)
        embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=180)
        self.add_item(HelpSelect(owner_id))


def build_help_embed() -> discord.Embed:
    lines = []
    for name, desc, _, _ in PUBLIC_COMMANDS:
        line = f"`/{name}` — {desc}"
        if name in PREFIX_MAP:
            line += f"  ·  `!{PREFIX_MAP[name]}`"
        lines.append(line)
    embed = base_embed(f"📖 {BOT_NAME} · Commands", "\n".join(lines), COLOR)
    embed.set_footer(text=f"{BOT_NAME} · Use the menu below for details")
    return embed


@bot.tree.command(name="help", description="Show the interactive list of commands.")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=build_help_embed(), view=HelpView(interaction.user.id), ephemeral=True
    )


@bot.command(name="help")
async def help_prefix(ctx: commands.Context):
    await ctx.send(embed=build_help_embed(), view=HelpView(ctx.author.id))


# ---------------------------------------------------------------- /poll

class PollView(discord.ui.View):
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
            )
            button.callback = self._make_callback(index)
            self.add_item(button)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            user_id = interaction.user.id
            if self.user_choice.get(user_id) == index:
                del self.user_choice[user_id]          # click again to remove vote
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
            lines.append(f"**{option}**\n{progress_bar(percent)}  {counts[i]} · {percent:.0f}%")

        embed = base_embed(f"📊 {self.question}", "\n\n".join(lines), COLOR)
        embed.set_footer(text=f"{total} vote(s) · Click an option again to remove your vote")
        return embed


@bot.tree.command(name="poll", description="Create an interactive poll.")
@app_commands.describe(
    question="The poll question",
    option1="First option",
    option2="Second option",
    option3="Third option (optional)",
    option4="Fourth option (optional)",
    option5="Fifth option (optional)",
)
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
    embed = base_embed("⏰ Reminder", text, COLOR)
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
            embed=base_embed(description="Use a time between 5 seconds and 30 days, e.g. `10m`, `2h`, `1d`.", color=COLOR_SOFT),
            ephemeral=True,
        )

    target = channel or interaction.channel
    asyncio.create_task(_send_reminder(target, interaction.user, reminder, seconds))
    await interaction.response.send_message(
        embed=base_embed(
            "⏰ Reminder set",
            f"**When:** in {fmt_seconds(seconds)}\n**Where:** {target.mention}\n**Message:** {reminder}",
            COLOR_SOFT,
        ),
        ephemeral=True,
    )


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
            embed=base_embed(description="Could not translate. Check the language code (e.g. `en`, `es`).", color=COLOR_SOFT),
            ephemeral=True,
        )

    embed = base_embed("🌐 Translation", color=COLOR)
    embed.add_field(name="Original", value=text[:1024], inline=False)
    embed.add_field(name=f"Translated · `{language.lower()}`", value=(translated or "—")[:1024], inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ---------------------------------------------------------------- giveaways (admin)

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.gid: int | None = None

    @discord.ui.button(label="Enter", emoji="🎟️", style=discord.ButtonStyle.secondary, custom_id="giveaway:enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = giveaways.get(self.gid)
        if not data or data["ended"]:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)

        uid = interaction.user.id
        if uid in data["entries"]:
            data["entries"].discard(uid)
            msg = f"You left the giveaway. Total entries: **{len(data['entries'])}**"
        else:
            data["entries"].add(uid)
            msg = f"You're entered! Total entries: **{len(data['entries'])}**"
        await interaction.response.send_message(msg, ephemeral=True)


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
            embed = message.embeds[0]
            embed.color = COLOR_SOFT
            embed.set_footer(text=f"{BOT_NAME} · Giveaway ended · {len(data['entries'])} entries")
            await message.edit(embed=embed, view=_disabled(GiveawayView()))
        except discord.HTTPException:
            pass

        if winners:
            mentions = ", ".join(f"<@{w}>" for w in winners)
            await channel.send(
                content=mentions,
                embed=base_embed("🏆 Giveaway winner", f"Congratulations {mentions}! You won **{data['prize']}**.", COLOR),
            )
        else:
            await channel.send(embed=base_embed("Giveaway ended", "No valid entries were found.", COLOR_SOFT))
    return winners


async def _auto_end(gid: int, delay: int):
    await asyncio.sleep(delay)
    data = giveaways.get(gid)
    if data and not data["ended"]:
        await _finish_giveaway(gid)


giveaway_group = app_commands.Group(
    name="giveaway",
    description="Manage giveaways",
    guild_only=True,
    default_permissions=discord.Permissions(manage_guild=True),
)
bot.tree.add_command(giveaway_group)


@giveaway_group.command(name="start", description="Start a giveaway.")
@app_commands.describe(
    prize="What the winner receives",
    duration="How long it lasts, e.g. 30m, 2h, 1d or 1h30m",
    winners="Number of winners (1-20, default 1)",
)
async def giveaway_start(
    interaction: discord.Interaction,
    prize: str,
    duration: str,
    winners: app_commands.Range[int, 1, 20] = 1,
):
    seconds = parse_duration(duration)
    if seconds is None or seconds < 10 or seconds > 30 * 86400:
        return await interaction.response.send_message(
            embed=base_embed(description="Use a duration between 10 seconds and 30 days, e.g. `1h` or `2d`.", color=COLOR_SOFT),
            ephemeral=True,
        )

    ends_at = int(datetime.now(timezone.utc).timestamp()) + seconds
    embed = base_embed("🎉 Giveaway", f"## {prize}", COLOR)
    embed.add_field(name="Winners", value=str(winners), inline=True)
    embed.add_field(name="Hosted by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Ends", value=f"<t:{ends_at}:R>", inline=True)
    embed.set_footer(text=f"{BOT_NAME} · Click Enter to join")

    view = GiveawayView()
    await interaction.response.send_message(embed=embed, view=view)
    message = await interaction.original_response()

    view.gid = message.id
    giveaways[message.id] = {
        "prize": prize,
        "winners": winners,
        "entries": set(),
        "ended": False,
        "last_winners": [],
        "channel_id": interaction.channel_id,
    }
    asyncio.create_task(_auto_end(message.id, seconds))


def _parse_message_id(value: str) -> int | None:
    try:
        return int(value.strip())
    except ValueError:
        return None


@giveaway_group.command(name="end", description="End a giveaway early and pick the winner(s).")
@app_commands.describe(message_id="ID of the giveaway message")
async def giveaway_end(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    data = giveaways.get(gid) if gid else None
    if not data:
        return await interaction.response.send_message(
            embed=base_embed(description="No giveaway found with that ID.", color=COLOR_SOFT), ephemeral=True
        )
    if data["ended"]:
        return await interaction.response.send_message(
            embed=base_embed(description="This giveaway has already ended. Use `/giveaway reroll` instead.", color=COLOR_SOFT),
            ephemeral=True,
        )

    await interaction.response.send_message(
        embed=base_embed(description="Ending giveaway…", color=COLOR_SOFT), ephemeral=True
    )
    await _finish_giveaway(gid)


@giveaway_group.command(name="reroll", description="Pick a new winner for an ended giveaway.")
@app_commands.describe(message_id="ID of the giveaway message")
async def giveaway_reroll(interaction: discord.Interaction, message_id: str):
    gid = _parse_message_id(message_id)
    data = giveaways.get(gid) if gid else None
    if not data:
        return await interaction.response.send_message(
            embed=base_embed(description="No giveaway found with that ID.", color=COLOR_SOFT), ephemeral=True
        )
    if not data["ended"]:
        return await interaction.response.send_message(
            embed=base_embed(description="This giveaway is still running. Use `/giveaway end` first.", color=COLOR_SOFT),
            ephemeral=True,
        )

    previous = set(data["last_winners"])
    new_winners = await _finish_giveaway(gid, pick=1, exclude=previous)
    if not new_winners:
        return await interaction.response.send_message(
            embed=base_embed(description="No eligible entries left to reroll.", color=COLOR_SOFT), ephemeral=True
        )
    await interaction.response.send_message(
        embed=base_embed(description="New winner selected.", color=COLOR_SOFT), ephemeral=True
    )


# ---------------------------------------------------------------- run

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to your .env file.")
    bot.run(TOKEN)
