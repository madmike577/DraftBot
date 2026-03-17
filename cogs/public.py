"""
cogs/public.py — All /brackt public commands in a single cog.
Draft commands: onclock, last5, team, mysports, status, sport, help
Schedule commands: schedule, nextmatch (dispatched to sport handlers)
"""

import discord
from discord import app_commands
from discord.ext import commands

from config import DISPLAY_CHOICES
from league import (
    load_league, league_display_name, mode_label, is_ephemeral,
    get_team_for_pick, get_next_pick_username, format_pick_number,
    mention, get_missing_sports, get_flex_remaining, get_total_picks,
    no_league_response, draft_inactive_response,
    brackt_username_autocomplete,
)
from sports import SPORT_HANDLERS


# ---------------------------------------------------------------------------
# Autocomplete helpers (defined at module level for decorator use)
# ---------------------------------------------------------------------------

async def sport_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for /brackt sport — shows all required_sports."""
    league = load_league(interaction.channel_id)
    if not league or not league.get('required_sports'):
        return []
    return [
        app_commands.Choice(name=s, value=s)
        for s in league['required_sports']
        if current.lower() in s.lower()
    ][:25]


async def schedule_sport_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """
    Autocomplete for /brackt schedule and /brackt nextmatch.
    Only shows sports that are in required_sports AND have a handler.
    """
    league = load_league(interaction.channel_id)
    if not league or not league.get('required_sports'):
        return []
    supported = {name for handler in SPORT_HANDLERS for name in handler.sport_names}
    return [
        app_commands.Choice(name=s, value=s)
        for s in league['required_sports']
        if s in supported and current.lower() in s.lower()
    ][:25]


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class PublicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    brackt = app_commands.Group(
        name='brackt',
        description='Brackt Draft Bot commands',
    )

    # ------------------------------------------------------------------
    # Draft state
    # ------------------------------------------------------------------

    @brackt.command(name='onclock', description='Show who is currently on the clock')
    @app_commands.describe(display='Show publicly or privately (default: public)')
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def onclock(self, interaction: discord.Interaction, display: str = 'public'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if not league.get('draft_active', True):
            await draft_inactive_response(interaction); return
        if not league['draft_order']:
            await interaction.response.send_message('❌ Draft not configured yet.', ephemeral=True); return
        pick_num       = league['current_pick']
        formatted, _   = format_pick_number(league, pick_num)
        username       = get_team_for_pick(league, pick_num)
        after_username = get_next_pick_username(league, pick_num)
        up_next = f'\nUp next: {mention(league, after_username)}' if after_username else ''
        msg = (
            f'🕐 **Pick {formatted} ({pick_num}):** {mention(league, username)} is on the clock!'
            f'{up_next}'
        )
        await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

    @brackt.command(name='last5', description='Show the last 5 picks')
    @app_commands.describe(display='Show publicly or privately (default: public)')
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def last5(self, interaction: discord.Interaction, display: str = 'public'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if not league.get('draft_active', True):
            await draft_inactive_response(interaction); return
        if not league['pick_history']:
            await interaction.response.send_message(
                '📋 No picks have been made yet.', ephemeral=is_ephemeral(display)
            ); return
        recent = league['pick_history'][-5:]
        text   = '📋 **Last 5 Picks**\n\n'
        for p in recent:
            formatted, _ = format_pick_number(league, p['pick'])
            handle = league['handles'].get(p['team'], p['team'])
            text += f'Pick {formatted} ({p["pick"]}): **{handle}** — **{p["player"]}** ({p["sport"]})\n'
        await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

    @brackt.command(name='team', description='Show all picks made by a specific team')
    @app_commands.describe(
        brackt_username='Start typing a team name or brackt username',
        display='Show publicly or privately (default: public)',
    )
    @app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def team_command(self, interaction: discord.Interaction, brackt_username: str,
                           display: str = 'public'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if brackt_username not in league['team_rosters']:
            known = ', '.join(f'`{u}`' for u in league['draft_order']) or 'None configured'
            await interaction.response.send_message(
                f'❌ Unknown username: `{brackt_username}`\nKnown teams: {known}', ephemeral=True
            ); return
        roster = league['team_rosters'].get(brackt_username, [])
        handle = league['handles'].get(brackt_username, brackt_username)
        if not roster:
            await interaction.response.send_message(
                f'📋 No picks recorded for **{handle}** yet.', ephemeral=is_ephemeral(display)
            ); return
        text = f'📋 **{handle}\'s Picks ({len(roster)}/{league["total_rounds"]})**\n\n'
        for p in roster:
            _, round_num = format_pick_number(league, p['pick'])
            text += f'Round {round_num}: **{p["player"]}** ({p["sport"]})\n'
        await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

    @brackt.command(name='mysports', description='Show missing sports and flex spots for a team')
    @app_commands.describe(
        brackt_username='Start typing a team name or brackt username (leave blank for your own)',
        display='Show publicly or privately (default: public)',
    )
    @app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def mysports(self, interaction: discord.Interaction, brackt_username: str = None,
                       display: str = 'public'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if not league['required_sports']:
            await interaction.response.send_message(
                '❌ No required sports configured yet.', ephemeral=True
            ); return
        if brackt_username is None:
            sender_id       = str(interaction.user.id)
            brackt_username = next(
                (u for u, uid in league['players'].items() if uid == sender_id), None
            )
            if brackt_username is None:
                await interaction.response.send_message(
                    '❌ Could not find your team. Try `/brackt mysports [brackt username]`',
                    ephemeral=True
                ); return
        if brackt_username not in league['team_rosters']:
            await interaction.response.send_message(
                f'❌ Unknown username: `{brackt_username}`', ephemeral=True
            ); return
        missing      = get_missing_sports(league, brackt_username)
        flex_left    = get_flex_remaining(league, brackt_username)
        total_picks  = len(league['team_rosters'].get(brackt_username, []))
        handle       = league['handles'].get(brackt_username, brackt_username)
        missing_text = '✅ All sports covered!' if not missing else '\n'.join(f'  • {s}' for s in missing)
        msg = (
            f'📊 **{handle}\'s Roster ({total_picks}/{league["total_rounds"]} picks)**\n\n'
            f'**Missing Sports ({len(missing)}):**\n{missing_text}\n\n'
            f'**Flex Spots Remaining:** {flex_left} of {league["flex_spots"]}'
        )
        await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

    @brackt.command(name='status', description='Show current draft round, pick number, and who is on the clock')
    @app_commands.describe(display='Show publicly or privately (default: public)')
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def status(self, interaction: discord.Interaction, display: str = 'public'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if not league.get('draft_active', True):
            await draft_inactive_response(interaction); return
        if not league['draft_order']:
            await interaction.response.send_message('❌ Draft not configured yet.', ephemeral=True); return
        pick_num     = league['current_pick']
        total        = get_total_picks(league)
        _, round_num = format_pick_number(league, pick_num)
        username     = get_team_for_pick(league, pick_num)
        msg = (
            f'📋 **Draft Status — {league_display_name(league)}** ({mode_label(league)})\n'
            f'Round: {round_num} of {league["total_rounds"]}\n'
            f'Current Pick: {pick_num} of {total}\n'
            f'On the Clock: {mention(league, username)}'
        )
        await interaction.response.send_message(msg, ephemeral=is_ephemeral(display))

    # ------------------------------------------------------------------
    # Sport picks
    # ------------------------------------------------------------------

    @brackt.command(name='sport', description='Show all drafted picks for a specific sport')
    @app_commands.describe(
        sport='Select a sport',
        display='Show publicly or privately (default: private)',
    )
    @app_commands.autocomplete(sport=sport_autocomplete)
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def sport_command(self, interaction: discord.Interaction, sport: str,
                            display: str = 'private'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        if not league.get('pick_history'):
            await interaction.response.send_message('📋 No picks recorded yet.', ephemeral=True); return

        SPORT_DISPLAY_TO_PICK = {
            "NCAA Basketball - Men's":   'NCAAM Basketball',
            "NCAA Basketball - Women's": 'NCAAW Basketball',
        }
        pick_sport  = SPORT_DISPLAY_TO_PICK.get(sport, sport)
        sport_picks = sorted(
            [p for p in league['pick_history'] if p['sport'].lower() == pick_sport.lower()],
            key=lambda x: x['pick']
        )
        if not sport_picks:
            available = ', '.join(f'`{s}`' for s in league['required_sports'])
            await interaction.response.send_message(
                f'❌ No picks found for **{sport}**.\nAvailable sports: {available}',
                ephemeral=True
            ); return

        lines = []
        for i, p in enumerate(sport_picks, 1):
            handle = league['handles'].get(p['team'], p['team'])
            lines.append(f'{i}. **{p["player"]}** — {handle} ({p["pick"]})')
        text  = f'🏅 **{sport}** — {len(sport_picks)} pick{"s" if len(sport_picks) > 1 else ""}\n\n'
        text += '\n'.join(lines)
        await interaction.response.send_message(text, ephemeral=is_ephemeral(display))

    # ------------------------------------------------------------------
    # Schedule + nextmatch (dispatch to sport handlers)
    # ------------------------------------------------------------------

    @brackt.command(name='schedule', description='Show upcoming fixtures and results for a sport')
    @app_commands.describe(
        sport='Select a sport',
        display='Show publicly or privately (default: private)',
    )
    @app_commands.autocomplete(sport=schedule_sport_autocomplete)
    @app_commands.choices(display=DISPLAY_CHOICES)
    async def schedule_command(self, interaction: discord.Interaction, sport: str,
                               display: str = 'private'):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        for handler in SPORT_HANDLERS:
            if handler.handles(sport):
                await handler.schedule(interaction, league, display)
                return
        await interaction.response.send_message(
            f'🚧 Schedule support for **{sport}** is coming soon!', ephemeral=True
        )

    @brackt.command(name='nextmatch', description='Show your next upcoming match for a sport')
    @app_commands.describe(sport='Select a sport with fixture support')
    @app_commands.autocomplete(sport=schedule_sport_autocomplete)
    async def nextmatch_command(self, interaction: discord.Interaction, sport: str):
        league = load_league(interaction.channel_id)
        if not league:
            await no_league_response(interaction); return
        for handler in SPORT_HANDLERS:
            if handler.handles(sport):
                await handler.nextmatch(interaction, league)
                return
        await interaction.response.send_message(
            f'🚧 Schedule support for **{sport}** is coming soon!', ephemeral=True
        )

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    @brackt.command(name='help', description='Show all available draft commands')
    async def help_command(self, interaction: discord.Interaction):
        league = load_league(interaction.channel_id)
        mode   = mode_label(league) if league else '⚪ Not configured'
        name   = league_display_name(league) if league else 'Brackt Draft Bot'
        msg = (
            f'📖 **{name}** ({mode})\n\n'
            '**Commands:**\n'
            '`/brackt onclock` — Show who is on the clock\n'
            '`/brackt last5` — Show the last 5 picks\n'
            '`/brackt team [username]` — Show a team\'s picks\n'
            '`/brackt mysports [username]` — Show missing sports and flex spots\n'
            '`/brackt sport [sport]` — Show all picks for a specific sport\n'
            '`/brackt schedule [sport]` — Show upcoming fixtures and results\n'
            '`/brackt nextmatch [sport]` — Show your next upcoming match\n'
            '`/brackt status` — Show current draft state\n'
            '`/brackt help` — Show this message\n\n'
            'All commands support a `display` option: **public** (default) or **private**\n\n'
            '⚙️ *Server managers can access admin commands via `/bradmin`*'
        )
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PublicCog(bot))
