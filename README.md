# SofaScore for Home Assistant

Follow a team (any sport SofaScore covers) and get match updates in Home Assistant.

## Install
1. Copy `custom_components/sofascore` into your HA `config/custom_components/` folder
   (or add this repo to HACS as a custom repository).
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **SofaScore**.
4. Type a team name (e.g. `Benfica`) or its SofaScore ID, then pick the team.
   Add the integration again for each extra team.

## Entities (one device per team)
| Entity | State | Useful attributes |
|---|---|---|
| `sensor.<team>_next_match` | kickoff time | opponent, venue (home/away), tournament, round, opponent_logo |
| `sensor.<team>_last_match` | e.g. `W 2-1` | score, result, opponent, tournament |
| `sensor.<team>_live_match` | `1st half`, `Halftime`… or `Not playing` | score, minute, opponent |
| `sensor.<team>_league_position` | table position | points, matches, wins, draws, losses, goal_difference, promotion |

Polling is every 10 minutes normally and every 30 seconds from 20 minutes before kickoff until full time.

## Events
The integration fires `sofascore_team_update` on the event bus with `type` set to
`kickoff`, `goal`, `status_change` (e.g. halftime) or `full_time`. Goal events also include
`scoring_team`, `scored_by_us` and `player` (when SofaScore has it).

```yaml
automation:
  - alias: "Goal alert"
    triggers:
      - trigger: event
        event_type: sofascore_team_update
        event_data:
          type: goal
          scored_by_us: true
    actions:
      - action: notify.notify
        data:
          title: "GOAL! {{ trigger.event.data.team_name }}"
          message: >
            {{ trigger.event.data.player or 'Goal' }} –
            {{ trigger.event.data.home_team }} {{ trigger.event.data.score }} {{ trigger.event.data.away_team }}
            ({{ trigger.event.data.minute }}')

  - alias: "Full time result"
    triggers:
      - trigger: event
        event_type: sofascore_team_update
        event_data:
          type: full_time
    actions:
      - action: notify.notify
        data:
          message: >
            FT: {{ trigger.event.data.home_team }} {{ trigger.event.data.score }}
            {{ trigger.event.data.away_team }} ({{ trigger.event.data.result }})
```

## Caveats
SofaScore's API is unofficial. Plain Python HTTP clients get HTTP 403; this
integration impersonates Chrome via `curl_cffi`. A datacenter IP can still be
blocked. Enable debug logging to see raw errors:

```yaml
logger:
  logs:
    custom_components.sofascore: debug
```
