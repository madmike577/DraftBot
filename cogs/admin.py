"""
cogs/admin.py — All /bradmin commands. Requires manage_guild permission.
"""

import discord
from discord import app_commands
from discord.ext import commands
import requests

from config import DISPLAY_CHOICES
from league import (
    load_league, update_cache, default_league, is_admin,
    get_num_teams, get_total_picks, league_display_name, mode_label,
    get_team_for_pick, format_pick_number, mention, get_flex_remaining,
    fetch_draft_state, sync_from_api,
    no_league_response, not_league_admin_response, check_league_and_admin,
    brackt_username_autocomplete,
)


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # discord.py cogs use app_commands.Group defined at class level
    brackt = app_commands.Group(
        name='bradmin',
        description='Brackt Draft Bot admin commands',
        default_permissions=discord.Permissions(manage_guild=True),
    )

    # ------------------------------------------------------------------
    # League setup
    # ------------------------------------------------------------------

    @brackt.command(name='setup', description='Initialize a new league in this channel')
    async def setup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and \
           not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                '❌ You need **Manage Server** or **Administrator** permission to run this.',
                ephemeral=True
            ); return

        channel_id = interaction.channel_id
        existing   = load_league(channel_id)
        if existing:
            await interaction.response.send_message(
                '⚠️ A league is already configured in this channel. '
                'Use `/bradmin adminsettings` to view current settings.',
                ephemeral=True
            ); return

        league = default_league(channel_id, interaction.user.id)
        update_cache(channel_id, league)
        await interaction.response.send_message(
            f'✅ **League initialized!** You ({interaction.user.mention}) are the league admin.\n\n'
            f'**Recommended setup order:**\n'
            f'1️⃣ `/bradmin setapi [url]` — Connect your brackt.com draft\n'
            f'2️⃣ `/bradmin setrounds [n]` — Set total rounds (default: 20)\n'
            f'3️⃣ `/bradmin setflex [n]` — Set flex spots (default: 4)\n'
            f'4️⃣ `/bradmin addplayer [username] [@user]` — Map each player\n'
            f'5️⃣ `/bradmin setdraftorder [u1,u2,...]` — Set snake draft order\n'
            f'6️⃣ `/bradmin syncnow` — Pull live data and auto-populate sports\n'
            f'\n💡 `/bradmin addsport` is available for new drafts with no picks yet.',
            ephemeral=True
        )

    @brackt.command(name='setapi', description='Set the brackt.com API URL for this league')
    @app_commands.describe(url='The brackt.com draft API URL')
    async def setapi(self, interaction: discord.Interaction, url: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if not url.startswith('https://www.brackt.com/api/'):
            await interaction.response.send_message(
                '❌ URL does not look like a valid brackt.com API URL. '
                'It should start with `https://www.brackt.com/api/`',
                ephemeral=True
            ); return
        league['api_url'] = url
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(
            '✅ API URL set. Run `/bradmin syncnow` to pull current draft data.',
            ephemeral=True
        )

    @brackt.command(name='setrounds', description='Set total number of rounds')
    @app_commands.describe(rounds='Total number of rounds in the draft')
    async def setrounds(self, interaction: discord.Interaction, rounds: int):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if rounds < 1 or rounds > 100:
            await interaction.response.send_message(
                '❌ Rounds must be between 1 and 100.', ephemeral=True
            ); return
        league['total_rounds'] = rounds
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(f'✅ Total rounds set to **{rounds}**.', ephemeral=True)

    @brackt.command(name='setflex', description='Set number of flex spots per team')
    @app_commands.describe(spots='Number of flex spots')
    async def setflex(self, interaction: discord.Interaction, spots: int):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if spots < 0 or spots > 20:
            await interaction.response.send_message(
                '❌ Flex spots must be between 0 and 20.', ephemeral=True
            ); return
        league['flex_spots'] = spots
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(f'✅ Flex spots set to **{spots}**.', ephemeral=True)

    @brackt.command(name='addsport', description='Add a required sport to this league')
    @app_commands.describe(sport='Sport name exactly as it appears on brackt.com')
    async def addsport(self, interaction: discord.Interaction, sport: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        sport = sport.strip()
        if not sport:
            await interaction.response.send_message('❌ Sport name cannot be empty.', ephemeral=True); return
        if sport in league['required_sports']:
            await interaction.response.send_message(
                f'⚠️ **{sport}** is already in the required sports list.', ephemeral=True
            ); return
        league['required_sports'].append(sport)
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(
            f'✅ Added **{sport}**. ({len(league["required_sports"])} required sports total)',
            ephemeral=True
        )

    @brackt.command(name='removesport', description='Remove a required sport from this league')
    @app_commands.describe(sport='Sport name to remove')
    async def removesport(self, interaction: discord.Interaction, sport: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if sport not in league['required_sports']:
            await interaction.response.send_message(
                f'❌ **{sport}** is not in the required sports list.', ephemeral=True
            ); return
        league['required_sports'].remove(sport)
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(f'✅ Removed **{sport}**.', ephemeral=True)

    @brackt.command(name='addplayer', description='Map a brackt.com username to a Discord user')
    @app_commands.describe(
        brackt_username='The player\'s brackt.com username',
        discord_user='The player\'s Discord account',
    )
    async def addplayer(self, interaction: discord.Interaction, brackt_username: str, discord_user: discord.Member):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        brackt_username = brackt_username.strip()
        if not brackt_username:
            await interaction.response.send_message('❌ Brackt username cannot be empty.', ephemeral=True); return
        if discord_user.bot:
            await interaction.response.send_message(
                '❌ Cannot map a brackt username to a bot account.', ephemeral=True
            ); return
        league['players'][brackt_username] = str(discord_user.id)
        league['handles'][brackt_username] = discord_user.display_name
        if brackt_username not in league['team_rosters']:
            league['team_rosters'][brackt_username] = []
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(
            f'✅ Mapped **{brackt_username}** → {discord_user.mention}', ephemeral=True
        )

    @brackt.command(name='removeplayer', description='Remove a player mapping')
    @app_commands.describe(brackt_username='The brackt.com username to remove')
    async def removeplayer(self, interaction: discord.Interaction, brackt_username: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if brackt_username not in league['players']:
            await interaction.response.send_message(
                f'❌ **{brackt_username}** not found in player list.', ephemeral=True
            ); return
        league['players'].pop(brackt_username)
        league['handles'].pop(brackt_username, None)
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(f'✅ Removed **{brackt_username}**.', ephemeral=True)

    @brackt.command(name='setdraftorder', description='Set the snake draft order (comma separated brackt usernames)')
    @app_commands.describe(order='Comma separated brackt usernames in pick order')
    async def setdraftorder(self, interaction: discord.Interaction, order: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        draft_order = [u.strip() for u in order.split(',') if u.strip()]
        if len(draft_order) < 2:
            await interaction.response.send_message(
                '❌ Please provide at least 2 usernames separated by commas.', ephemeral=True
            ); return
        if len(draft_order) != len(set(draft_order)):
            await interaction.response.send_message(
                '❌ Duplicate usernames detected.', ephemeral=True
            ); return
        unknown = [u for u in draft_order if u not in league['players']]
        for u in draft_order:
            if u not in league['team_rosters']:
                league['team_rosters'][u] = []
        league['draft_order'] = draft_order
        update_cache(interaction.channel_id, league)
        order_text = '\n'.join([f'{i+1}. {u}' for i, u in enumerate(draft_order)])
        warning = (
            f'\n\n⚠️ These usernames are not yet mapped to Discord users: '
            f'{", ".join(f"`{u}`" for u in unknown)}'
        ) if unknown else ''
        await interaction.response.send_message(
            f'✅ Draft order set ({len(draft_order)} teams):\n{order_text}{warning}',
            ephemeral=True
        )

    @brackt.command(name='syncnow', description='Manually sync draft state from brackt.com API')
    async def syncnow(self, interaction: discord.Interaction):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if not league.get('api_url'):
            await interaction.response.send_message(
                '❌ No API URL set. Run `/bradmin setapi [url]` first.', ephemeral=True
            ); return

        await interaction.response.defer(ephemeral=True)
        data = fetch_draft_state(league)
        if data is None:
            await interaction.followup.send(
                '❌ Could not reach the brackt.com API. Check the URL or try again later.',
                ephemeral=True
            ); return

        if not league.get('draft_order'):
            seen = []
            for pick in sorted(data['picks'], key=lambda x: x['pickNumber']):
                if pick['username'] not in seen:
                    seen.append(pick['username'])
            league['draft_order'] = seen
            for u in seen:
                if u not in league['team_rosters']:
                    league['team_rosters'][u] = []

        sports_populated = False
        if not league.get('required_sports'):
            seen_sports = []
            for pick in data['picks']:
                if pick['sport'] not in seen_sports:
                    seen_sports.append(pick['sport'])
            league['required_sports'] = sorted(seen_sports)
            sports_populated = True

        preserved = league.get('last_known_pick', 0)
        sync_from_api(league, data)
        league['last_known_pick'] = (data['currentPickNumber'] - 1) if preserved == 0 else preserved
        update_cache(interaction.channel_id, league)

        sports_note = (
            f'\n📋 **{len(league["required_sports"])} required sports auto-populated** from pick history.'
            if sports_populated else ''
        )
        await interaction.followup.send(
            f'✅ Synced! **{len(league["pick_history"])} picks** loaded, '
            f'currently at pick **{league["current_pick"]}** of **{get_total_picks(league)}**.\n'
            f'On the clock: {mention(league, get_team_for_pick(league, league["current_pick"]))}'
            f'{sports_note}',
            ephemeral=True
        )

    @brackt.command(name='admintransfer', description='Transfer league admin role to another user')
    @app_commands.describe(new_admin='The Discord user to transfer admin to')
    async def admintransfer(self, interaction: discord.Interaction, new_admin: discord.Member):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if new_admin.bot:
            await interaction.response.send_message(
                '❌ Cannot transfer admin to a bot account.', ephemeral=True
            ); return
        if new_admin.id == interaction.user.id:
            await interaction.response.send_message('❌ You are already the admin.', ephemeral=True); return
        league['admin_id'] = new_admin.id
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(
            f'✅ Admin role transferred to {new_admin.mention}.', ephemeral=True
        )

    @brackt.command(name='adminsettings', description='View current league configuration')
    async def adminsettings(self, interaction: discord.Interaction):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        players_text = '\n'.join(
            [f'  {u} → <@{uid}>' for u, uid in league['players'].items()]
        ) or '  None configured'
        sports_text = '\n'.join(
            [f'  • {s}' for s in league['required_sports']]
        ) or '  None configured'
        order_text = ', '.join(league['draft_order']) or 'Not set'
        msg = (
            f'⚙️ **League Settings**\n\n'
            f'**API URL:** `{league["api_url"] or "Not set"}`\n'
            f'**Total Rounds:** {league["total_rounds"]}\n'
            f'**Flex Spots:** {league["flex_spots"]}\n'
            f'**Teams:** {get_num_teams(league)}\n'
            f'**Total Picks:** {get_total_picks(league)}\n'
            f'**Current Pick:** {league["current_pick"]}\n'
            f'**Draft Active:** {"✅ Yes" if league.get("draft_active", True) else "🔴 No (disabled)"}\n'
            f'**Status:** {mode_label(league)}\n\n'
            f'**League Name:** {league.get("league_name") or "Not set"}\n'
            f'**Draft Order:** {order_text}\n\n'
            f'**Players ({len(league["players"])}):**\n{players_text}\n\n'
            f'**Required Sports ({len(league["required_sports"])}):**\n{sports_text}'
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @brackt.command(name='setname', description='Set a display name for this league')
    @app_commands.describe(name='The league name e.g. Diablo, Rumble, Omnifantasy')
    async def setname(self, interaction: discord.Interaction, name: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        name = name.strip()
        if not name:
            await interaction.response.send_message('❌ League name cannot be empty.', ephemeral=True); return
        if len(name) > 32:
            await interaction.response.send_message(
                '❌ League name must be 32 characters or fewer.', ephemeral=True
            ); return
        league['league_name'] = name
        update_cache(interaction.channel_id, league)
        await interaction.response.send_message(f'✅ League name set to **{name}**.', ephemeral=True)

    @brackt.command(name='draftstatus', description='Enable or disable draft commands for this league')
    @app_commands.describe(status='Enable or disable draft commands')
    @app_commands.choices(status=[
        app_commands.Choice(name='enable',  value='enable'),
        app_commands.Choice(name='disable', value='disable'),
    ])
    async def draftstatus(self, interaction: discord.Interaction, status: str):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        league['draft_active'] = (status == 'enable')
        update_cache(interaction.channel_id, league)
        state = '✅ enabled' if league['draft_active'] else '🔴 disabled'
        await interaction.response.send_message(
            f'Draft commands are now **{state}**.\n'
            f'Affected commands: `/brackt onclock`, `/brackt last5`, `/brackt status`',
            ephemeral=True
        )

    @brackt.command(name='adminpick', description='Manually record a pick')
    @app_commands.describe(
        player='Team or player name being picked',
        sport='Sport of the pick — must match brackt.com exactly',
        brackt_username='Start typing a team name or brackt username (leave blank for current pick)',
    )
    @app_commands.autocomplete(brackt_username=brackt_username_autocomplete)
    async def adminpick(self, interaction: discord.Interaction, player: str, sport: str,
                        brackt_username: str = None):
        league, admin = check_league_and_admin(interaction)
        if not league:
            await no_league_response(interaction); return
        if not admin:
            await not_league_admin_response(interaction); return
        if not league['draft_order']:
            await interaction.response.send_message(
                '❌ Draft order not set. Use `/bradmin setdraftorder` first.', ephemeral=True
            ); return

        player = player.strip()
        sport  = sport.strip()
        if not player or not sport:
            await interaction.response.send_message(
                '❌ Player and sport cannot be empty.', ephemeral=True
            ); return

        if league['required_sports'] and sport not in league['required_sports']:
            target_team    = brackt_username or get_team_for_pick(league, league['current_pick'])
            remaining_flex = get_flex_remaining(league, target_team)
            if remaining_flex <= 0:
                await interaction.response.send_message(
                    f'❌ **{sport}** is not a required sport and this team has no flex spots remaining.',
                    ephemeral=True
                ); return

        team = brackt_username if brackt_username else get_team_for_pick(league, league['current_pick'])
        if not team:
            await interaction.response.send_message(
                '❌ Could not determine team for this pick.', ephemeral=True
            ); return
        if brackt_username and brackt_username not in league['draft_order']:
            await interaction.response.send_message(
                f'❌ **{brackt_username}** is not in the draft order.', ephemeral=True
            ); return
        if team not in league['team_rosters']:
            league['team_rosters'][team] = []

        formatted, _ = format_pick_number(league, league['current_pick'])
        pick_entry = {
            'pick':   league['current_pick'],
            'round':  ((league['current_pick'] - 1) // get_num_teams(league)) + 1,
            'team':   team,
            'player': player,
            'sport':  sport,
        }
        league['pick_history'].append(pick_entry)
        league['team_rosters'][team].append({
            'pick': league['current_pick'], 'player': player, 'sport': sport,
        })
        league['last_known_pick'] = league['current_pick'] - 1
        league['current_pick'] += 1

        next_team     = get_team_for_pick(league, league['current_pick'])
        on_deck_team  = get_team_for_pick(league, league['current_pick'] + 1)
        on_deck       = f'\n📋 **On Deck:** {mention(league, on_deck_team)}' if on_deck_team else ''
        update_cache(interaction.channel_id, league)

        channel = self.bot.get_channel(interaction.channel_id)
        await channel.send(
            f'━━━━━━━━━━━━━━━━━━━━━━\n'
            f'✅ **Pick {formatted}** — {mention(league, team)}\n'
            f'**{player}** · {sport}\n'
            f'━━━━━━━━━━━━━━━━━━━━━━\n'
            f'🕐 **On the Clock:** {mention(league, next_team)}'
            f'{on_deck}'
        )
        await interaction.response.send_message(
            f'✅ Pick recorded: **{player}** ({sport}) for **{league["handles"].get(team, team)}**',
            ephemeral=True
        )

    @brackt.command(name='nbaids', description='Fetch and log all balldontlie NBA team IDs')
    async def nbaids(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild and \
           not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('❌ Admin only.', ephemeral=True); return

        await interaction.response.defer(ephemeral=True)
        from config import BDL_BASE, NBA_TEAM_IDS
        from sports.nba import bdl_headers
        try:
            resp = requests.get(
                f'{BDL_BASE}/teams', headers=bdl_headers(), params={'per_page': 35}, timeout=10
            )
            if resp.status_code != 200:
                await interaction.followup.send(f'❌ API error {resp.status_code}', ephemeral=True); return
            teams = resp.json().get('data', [])
            lines = ['**balldontlie NBA Team IDs:**\n```']
            for t in sorted(teams, key=lambda x: x['full_name']):
                marker = ' ← OUR TEAMS' if t['full_name'] in NBA_TEAM_IDS.values() else ''
                lines.append(f'{t["id"]:3d}  {t["full_name"]}{marker}')
            lines.append('```')
            await interaction.followup.send('\n'.join(lines), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f'❌ Error: {e}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
