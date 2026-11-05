# SynexProtectBot

Discord utility and moderation helper bot.

## Commands

| Command | Description |
|---|---|
| `/bot-say` | Send a message without revealing who sent it |
| `/embed` | Send a custom embed (title, description, color, footer, image) |
| `/ping` | Show bot latency |
| `/serverinfo` | Server statistics |
| `/userinfo` | User details |
| `/botinfo` | Bot statistics |
| `/avatar` | Full-size avatar with download link |
| `/help` | Interactive command list |
| `/poll` | Interactive poll (2 to 5 options) |
| `/remind` | Scheduled reminder |
| `/translate` | Translate text |
| `/giveaway start` | Start a giveaway |
| `/giveaway reroll` | Reroll a winner |
| `/giveaway end` | End a giveaway early |

## Setup

1. Create an application at the Discord Developer Portal and add a bot.
2. In **Bot**, enable **Server Members Intent**.
3. Invite the bot with the `bot` and `applications.commands` scopes.
4. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.

```bash
pip install -r requirements.txt
python synexprotect_bot.py
```

## Deploy on Railway

1. Push this repository to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Add the variable `DISCORD_TOKEN` in the service's **Variables** tab.
4. Railway uses the `Procfile` (`worker: python synexprotect_bot.py`).

## Notes

- Reminders and giveaways are stored in memory and are lost on restart.
- Slash commands can take up to an hour to appear globally the first time.
