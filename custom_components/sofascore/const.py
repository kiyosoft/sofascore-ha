"""Constants for the SofaScore integration."""
from datetime import timedelta

DOMAIN = "sofascore"

CONF_TEAM_ID = "team_id"
CONF_TEAM_NAME = "team_name"

# Polling: slow when idle, fast around/during a match.
DEFAULT_SCAN_INTERVAL = timedelta(minutes=10)
LIVE_SCAN_INTERVAL = timedelta(seconds=10)
PREMATCH_WINDOW = timedelta(minutes=20)
STANDINGS_TTL = timedelta(hours=3)
# ponytail: keep the final on the game sensor for 8h after a ~2h match, then show the next fixture
RESULT_HOLD = timedelta(hours=8)

# Home Assistant bus event fired on kickoff / goal / status change / full time.
EVENT_TYPE = "sofascore_team_update"

STATUS_LIVE = "inprogress"
STATUS_FINISHED = "finished"
STATUS_NOT_STARTED = "notstarted"

TEAM_IMAGE_URL = "https://api.sofascore.app/api/v1/team/{team_id}/image"
TOURNAMENT_IMAGE_URL = "https://api.sofascore.app/api/v1/unique-tournament/{tournament_id}/image"
