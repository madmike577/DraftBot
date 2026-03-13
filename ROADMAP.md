# Brackt Notify — Roadmap

## In Progress
- [ ] UCL quarterfinals — update `stage=LAST_16` to `LAST_8` before April 15 (QF draw March 21)
- [ ] NBA play-in/playoffs — verify balldontlie tags play-in games as `postseason=true` when April 15 arrives

## Backlog
- [ ] Discord embeds for cleaner output
- [ ] Proactive event alerts (upcoming/completed events posted to channel)
- [ ] Cross-channel commands
- [ ] F1 schedule support
- [ ] IndyCar schedule support
- [ ] Auto-configuration for new leagues
- [ ] Investigate scoring/leaderboard via brackt.com API
- [ ] MLB schedule support (playoffs only, series tracker)
- [ ] NFL schedule support (playoffs only, series tracker)
- [ ] NBA Cup — update `NBA_CUP_GAME_IDS` each season with new final game ID

## Completed
- [x] Snake draft polling and pick announcements
- [x] Rollback detection and announcement
- [x] Draft complete detection
- [x] Multi-league support
- [x] /brackt sport command
- [x] /brackt schedule command (UCL two-leg with aggregate)
- [x] /brackt nextmatch command (UCL + NBA)
- [x] /bradmin draftstatus enable/disable
- [x] /bradmin setname — league naming (Diablo, Rumble, Omnifantasy)
- [x] UCL name mapping across all 3 leagues
- [x] Unified /brackt schedule command replacing sport-specific commands
- [x] NBA regular season — W/L record + next game via balldontlie free tier
- [x] NBA live game detection (🔴 LIVE with score + period)
- [x] NBA playoffs series tracker (activates automatically)
- [x] NBA rate limit fix — reduced to 2 API calls per team via fetch_nba_team_data()
- [x] NBA Cup Final exclusion from W/L record (NBA_CUP_GAME_IDS)
- [x] Correct balldontlie team IDs verified for all 17 drafted teams
