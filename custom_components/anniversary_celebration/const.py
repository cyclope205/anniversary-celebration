"""Constants for Anniversary Celebration."""
from __future__ import annotations

DOMAIN = "anniversary_celebration"
PLATFORMS = ["sensor"]

ATTRIBUTION = "Data calculated by Anniversary Celebration"

CONF_PEOPLE = "people"

CONF_PERSON_ID = "id"
CONF_FIRST_NAME = "first_name"
CONF_LAST_NAME = "last_name"
CONF_BIRTH_DATE = "birth_date"
CONF_STATUS = "status"
CONF_NOTIFY_TIME = "notify_time"
CONF_NOTIFY_TARGET = "notify_target"

STATUS_ALIVE = "alive"
STATUS_DECEASED = "deceased"
STATUSES = [STATUS_ALIVE, STATUS_DECEASED]

DEFAULT_NOTIFY_TIME = "09:00:00"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_notified"

SIGNAL_PEOPLE_UPDATED = f"{DOMAIN}_people_updated"

# Card / resource
CARD_FILENAME = "anniversary-celebration-card.js"
CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"
