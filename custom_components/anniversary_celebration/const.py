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

# Current (list-based) fields: a person can have 1-2 notification times and
# any number of notify.* targets.
CONF_NOTIFY_TIMES = "notify_times"
CONF_NOTIFY_TARGETS = "notify_targets"

# Legacy (pre-multi) single-value fields, still read for backward
# compatibility with people created before this was a list - see
# util.normalize_notify_times / normalize_notify_targets.
CONF_NOTIFY_TIME = "notify_time"
CONF_NOTIFY_TIME_2 = "notify_time_2"
CONF_NOTIFY_TARGET = "notify_target"

STATUS_ALIVE = "alive"
STATUS_DECEASED = "deceased"
STATUSES = [STATUS_ALIVE, STATUS_DECEASED]

DEFAULT_NOTIFY_TIME = "09:00:00"

# Optional death date for a deceased person. Independent from the birth-date
# "souvenir" anniversary: this triggers its own separate yearly reminder
# ("anniversaire de deces"), tracked under its own namespaced key in the
# same notified / mobile_sent_today storage maps (see NOTIFIED_KEY_DEATH_SUFFIX
# below) so it never collides with that person's birthday slots.
CONF_DEATH_DATE = "death_date"

# Suffix appended to a person's id to build a distinct, namespaced "virtual
# person id" used as a key in the notified / mobile_sent_today storage maps
# when tracking the death-anniversary trigger, so it can never collide with
# that same person's real birthday slot tracking (which uses the bare
# person id). Example: notified["<person_id>:death"] = {...}.
NOTIFIED_KEY_DEATH_SUFFIX = ":death"

# Integration-level (not per-person) list of notify.* targets that get every
# notification in addition to each person's own notify_targets. Lives in the
# config entry's options, next to CONF_PEOPLE, not inside a person dict.
CONF_DEFAULT_NOTIFY_TARGETS = "default_notify_targets"

# Optional spoken (TTS) announcement, per person. Entirely separate from the
# written notify_targets above: its own target list (media_player entities),
# its own TTS entity, its own time, and three independent opt-in toggles
# (all default False) for which trigger(s) should be spoken out loud.
CONF_ANNOUNCE_TARGETS = "announce_targets"
CONF_ANNOUNCE_TTS_ENTITY = "announce_tts_entity"
CONF_ANNOUNCE_TIME = "announce_time"
CONF_ANNOUNCE_BIRTHDAY = "announce_birthday"
CONF_ANNOUNCE_SOUVENIR = "announce_souvenir"
CONF_ANNOUNCE_DEATH = "announce_death"

# Integration-level (not per-person) default spoken announcement. Its own
# media_player targets, TTS entity, time, and three opt-in toggles (all
# default False) - entirely independent from the per-person announce_*
# fields above, not merged into them: two different TTS engines/times
# cannot be combined into a single speak call, so this fires as a second,
# parallel broadcast instead, with its own anti-duplicate tracking (see
# NOTIFIED_KEY_DEFAULT_ANNOUNCE_SUFFIX / _DEATH_SUFFIX below).
CONF_DEFAULT_ANNOUNCE_TARGETS = "default_announce_targets"
CONF_DEFAULT_ANNOUNCE_TTS_ENTITY = "default_announce_tts_entity"
CONF_DEFAULT_ANNOUNCE_TIME = "default_announce_time"
CONF_DEFAULT_ANNOUNCE_BIRTHDAY = "default_announce_birthday"
CONF_DEFAULT_ANNOUNCE_SOUVENIR = "default_announce_souvenir"
CONF_DEFAULT_ANNOUNCE_DEATH = "default_announce_death"

# Suffixes for the namespaced tracking keys used by the default-announce
# broadcast above (one per person, per trigger kind), so they can never
# collide with that same person's own per-person announce tracking
# (":announce" / ":death:announce") or with the written notify tracking.
NOTIFIED_KEY_DEFAULT_ANNOUNCE_SUFFIX = ":default_announce"
NOTIFIED_KEY_DEFAULT_ANNOUNCE_DEATH_SUFFIX = ":death:default_announce"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_notified"

SIGNAL_PEOPLE_UPDATED = f"{DOMAIN}_people_updated"

# Card / resource
CARD_FILENAME = "anniversary-celebration-card.js"
CARD_URL_PATH = f"/{DOMAIN}/{CARD_FILENAME}"
