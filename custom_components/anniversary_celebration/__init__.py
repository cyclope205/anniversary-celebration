"""Anniversary Celebration integration.

Tracks birthdays (living and deceased) and sends a notification on the day,
with a persisted "already notified" record so a restart never causes a
duplicate, and a per-minute recheck so a restart never causes a miss either.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    CARD_FILENAME,
    CARD_URL_PATH, PLATFORMS,
    CONF_ANNOUNCE_BIRTHDAY,
    CONF_ANNOUNCE_DEATH,
    CONF_ANNOUNCE_VOLUME,
    CONF_ANNOUNCE_SOUVENIR,
    CONF_ANNOUNCE_TARGETS,
    CONF_ANNOUNCE_TIME,
    CONF_ANNOUNCE_TTS_ENTITY,
    CONF_BIRTH_DATE,
    CONF_DEATH_DATE,
    CONF_DEFAULT_ANNOUNCE_BIRTHDAY,
    CONF_DEFAULT_ANNOUNCE_DEATH,
    CONF_DEFAULT_ANNOUNCE_SOUVENIR,
    CONF_DEFAULT_ANNOUNCE_TARGETS,
    CONF_DEFAULT_ANNOUNCE_TIME,
    CONF_DEFAULT_ANNOUNCE_TTS_ENTITY, CONF_DEFAULT_NOTIFY_TARGETS, CONF_FIRST_NAME, CONF_LAST_NAME,
    CONF_DEFAULT_ANNOUNCE_VOLUME,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DOMAIN,
    NOTIFIED_KEY_DEATH_SUFFIX,
    NOTIFIED_KEY_DEFAULT_ANNOUNCE_DEATH_SUFFIX,
    NOTIFIED_KEY_DEFAULT_ANNOUNCE_SUFFIX,
    SIGNAL_PEOPLE_UPDATED,
    STATUS_ALIVE,
    STATUS_DECEASED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .util import (
    announcement_message,
    current_age,
    due_slots,
    merge_notify_targets,
    normalize_notify_targets,
    normalize_notify_times,
    parse_birth_date,
)

_LOGGER = logging.getLogger(__name__)

_CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"

# hass.data keys used to coordinate the announce-volume override across
# concurrent announcements targeting the same media_player - see
# _async_speak and _async_restore_volume for why this coordination is
# needed (two or more announcements firing in the same per-minute check,
# e.g. several test people sharing one announce time, would otherwise
# each capture the other's already-bumped volume as "original").
_VOLUME_BASELINE_KEY = f"{DOMAIN}_volume_baseline"
_VOLUME_PENDING_KEY = f"{DOMAIN}_volume_pending"


def _migrate_slot_map(raw: dict) -> dict:
    """Convert a legacy flat {person_id: iso_date} map to the per-slot
    {person_id: {"0": iso_date}} shape used for multi-time support.

    Each configured notification time is tracked independently, so a
    person with two notification times can have one already sent today
    and the other still pending. Entries already in the new shape (dict
    values) pass through unchanged.

    Note: slot keys moved again after this - see due_slots()'s docstring
    in util.py - from the notify_times list INDEX ("0", "1", ...) to the
    time value itself ("08:00:00"), since index-based tracking silently
    mis-tracked a person's notifications whenever notify_times was
    reordered or edited. That second migration is deliberately NOT
    performed here: an index-keyed entry left over from before that
    change simply never matches any time-value lookup again, so it sits
    unused (harmless clutter, never read) rather than being remapped -
    the one-time consequence is a possible extra resend on the first day
    a slot already sent under the old scheme is re-evaluated, which is
    exactly the same "worst case: one harmless extra resend" trade-off
    _migrate_mobile_sent_map below already accepts for the same reason.
    """
    migrated = {}
    for person_id, value in raw.items():
        migrated[person_id] = value if isinstance(value, dict) else {"0": value}
    return migrated


def _migrate_mobile_sent_map(raw: dict) -> dict:
    """Convert mobile_sent_today to its current per-target shape.

    Shape history, oldest to newest:
    - flat {person_id: iso_date} (pre multi-time, single implicit target)
    - {person_id: {slot_index: iso_date}} (multi-time, but all-or-nothing
      per slot: one failing target blocked or duplicated every target)
    - {person_id: {slot_index: {target: iso_date}}} (current: each target's
      success is tracked on its own, so one unreachable device is retried
      on its own without blocking or duplicating the others)

    A slot value that isn't already a dict-of-targets is reset to an empty
    per-target map rather than guessed at: the worst case is one extra
    resend to a target that had already succeeded under the old
    bookkeeping, which is harmless and far safer than assuming which
    target an old flat date referred to.
    """
    migrated: dict = {}
    for person_id, value in raw.items():
        if not isinstance(value, dict):
            migrated[person_id] = {}
            continue
        slots: dict = {}
        for slot_index, slot_value in value.items():
            slots[slot_index] = slot_value if isinstance(slot_value, dict) else {}
        migrated[person_id] = slots
    return migrated


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anniversary Celebration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry.entry_id}")
    loaded: dict = await store.async_load() or {}

    # Storage format: {"notified": {person_id: {slot_key: iso_date}},
    # "mobile_sent_today": {person_id: {slot_key: {target: iso_date}}}}.
    # One entry per configured notification time (slot_key is the time
    # value itself, e.g. "08:00:00" - see due_slots() in util.py for why
    # it is no longer the list index), so a person with two notification
    # times tracks each independently, and each notify.* target within a
    # slot tracks its own success independently too. Older versions of
    # this integration saved progressively different shapes - see
    # _migrate_slot_map and _migrate_mobile_sent_map - so existing
    # installs don't lose their notified-today state on upgrade.
    if "notified" in loaded or "mobile_sent_today" in loaded:
        notified: dict = loaded.get("notified", {})
        mobile_sent_today: dict = loaded.get("mobile_sent_today", {})
    else:
        notified = loaded
        mobile_sent_today = {}
    notified = _migrate_slot_map(notified)
    mobile_sent_today = _migrate_mobile_sent_map(mobile_sent_today)

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "notified": notified,
        # Guards _async_check_and_notify against overlapping runs (e.g. the
        # immediate startup check overlapping with the first per-minute
        # tick), which could otherwise send the same notification twice.
        "lock": asyncio.Lock(),
        # person_id -> {slot_key: {target: iso_date}}: which notify.*
        # targets have already succeeded today, for which slot. Kept
        # separate from "notified" (which is only set once the persistent
        # notification AND every configured target have succeeded) so that
        # if the persistent notification keeps failing and the per-minute
        # check keeps retrying, a target that already succeeded is never
        # notified a second time while a sibling target is still being
        # retried. Persisted in the same store as "notified" so this
        # survives a restart or a config entry reload, not just the
        # current HA session.
        "mobile_sent_today": mobile_sent_today,
    }

    await _async_register_card(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def _check(now=None) -> None:
        await _async_check_and_notify(hass, entry)

    # Re-check every minute: cheap (pure date/time math) and guarantees that
    # a HA restart can never cause a birthday notification to be skipped —
    # the very next tick after startup re-evaluates everything from scratch.
    entry.async_on_unload(
        async_track_time_change(hass, _check, second=0)
    )

    # Also run once immediately so a restart catches up within seconds
    # instead of waiting up to a minute.
    hass.async_create_task(_check())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """People list changed: tell sensors to refresh and reload the entry."""
    async_dispatcher_send(hass, SIGNAL_PEOPLE_UPDATED)
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_check_and_notify(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Evaluate every person; notify + persist each due notification-time
    slot (a person can have more than one configured time), guarding
    against duplicates per slot."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return

    lock: asyncio.Lock = data["lock"]
    if lock.locked():
        # A check is already in flight (startup check overlapping with a
        # per-minute tick, or a slow notify service call) - skip this run
        # rather than risk sending the same notification twice.
        return

    async with lock:
        people = entry.options.get(CONF_PEOPLE, [])
        if not people:
            return

        now = dt_util.now()
        today = now.date()
        today_iso = today.isoformat()
        notified: dict = data["notified"]
        mobile_sent_today: dict = data["mobile_sent_today"]
        changed = False

        default_targets = [t for t in entry.options.get(CONF_DEFAULT_NOTIFY_TARGETS, []) if t]
        default_announce_targets = [t for t in entry.options.get(CONF_DEFAULT_ANNOUNCE_TARGETS, []) if t]
        default_announce_tts = (entry.options.get(CONF_DEFAULT_ANNOUNCE_TTS_ENTITY) or "").strip()
        default_announce_time = (entry.options.get(CONF_DEFAULT_ANNOUNCE_TIME) or "").strip()
        default_announce_birthday = bool(entry.options.get(CONF_DEFAULT_ANNOUNCE_BIRTHDAY, False))
        default_announce_souvenir = bool(entry.options.get(CONF_DEFAULT_ANNOUNCE_SOUVENIR, False))
        default_announce_death = bool(entry.options.get(CONF_DEFAULT_ANNOUNCE_DEATH, False))
        default_announce_volume = entry.options.get(CONF_DEFAULT_ANNOUNCE_VOLUME)

        for person in people:
            try:
                birth = parse_birth_date(person[CONF_BIRTH_DATE])
            except (KeyError, ValueError):
                continue

            person_id = person[CONF_PERSON_ID]
            status = person.get(CONF_STATUS, STATUS_ALIVE)
            notify_times = normalize_notify_times(person)

            # --- Birthday / "souvenir" written notification (same trigger
            # as before; now also receives the integration-level default
            # notify targets, unioned in _async_send_notification). ---
            person_notified = notified.get(person_id, {})
            due = due_slots(
                birth, today, now.hour, now.minute, notify_times, person_notified
            )
            person_mobile_sent = mobile_sent_today.get(person_id, {})
            for slot_index in due:
                # Tracked by the time VALUE, not the list index - see
                # due_slots()'s docstring in util.py: an index would
                # silently mis-track this person if notify_times is ever
                # reordered or edited between two sends on the same day.
                slot_key = notify_times[slot_index]
                persisted, mobile_changed, mobile_fully_ok = await _async_send_notification(
                    hass, person, birth, today, slot_key, person_mobile_sent,
                    kind="birthday", default_targets=default_targets,
                )
                if persisted and mobile_fully_ok:
                    person_notified[slot_key] = today_iso
                    notified[person_id] = person_notified
                    changed = True
                # else: leave this slot unmarked so the next per-minute
                # check retries - either persistent_notification is still
                # failing, or at least one configured target hasn't
                # succeeded yet (see _async_send_notification). A target
                # that already succeeded is not re-sent on that retry.
                if mobile_changed:
                    # mobile_sent_today was just updated for this slot - make
                    # sure that survives a restart even if persisted stays
                    # False (persistent_notification still failing).
                    mobile_sent_today[person_id] = person_mobile_sent
                    changed = True

            # --- Death anniversary: a separate, independent yearly trigger
            # for a deceased person with a death date configured. Tracked
            # under a namespaced virtual person id (NOTIFIED_KEY_DEATH_SUFFIX)
            # within the same notified / mobile_sent_today maps, so it can
            # never collide with this same person's birthday slot tracking
            # above - due_slots() is generic date math, it works the same
            # way on a death date as it does on a birth date. ---
            death_date = None
            death_date_raw = person.get(CONF_DEATH_DATE)
            if status == STATUS_DECEASED and death_date_raw:
                try:
                    death_date = parse_birth_date(death_date_raw)
                except ValueError:
                    death_date = None

            if death_date is not None:
                death_key = f"{person_id}{NOTIFIED_KEY_DEATH_SUFFIX}"
                death_notified = notified.get(death_key, {})
                due_death = due_slots(
                    death_date, today, now.hour, now.minute, notify_times, death_notified
                )
                death_mobile_sent = mobile_sent_today.get(death_key, {})
                for slot_index in due_death:
                    slot_key = notify_times[slot_index]
                    persisted, mobile_changed, mobile_fully_ok = await _async_send_notification(
                        hass, person, death_date, today, slot_key, death_mobile_sent,
                        kind="death", default_targets=default_targets,
                    )
                    if persisted and mobile_fully_ok:
                        death_notified[slot_key] = today_iso
                        notified[death_key] = death_notified
                        changed = True
                    if mobile_changed:
                        mobile_sent_today[death_key] = death_mobile_sent
                        changed = True

            # --- Spoken announcement: fully independent of the written
            # notifications above - its own time, its own media_player
            # targets, its own TTS entity, and three separate opt-in
            # toggles (one per trigger kind, all default False). Best
            # effort: a failure here never blocks or retries the written
            # path, and is itself never retried the next day even on
            # failure, since a TTS line that says "aujourd'hui" would be
            # wrong if actually spoken a day late. ---
            announce_time = (person.get(CONF_ANNOUNCE_TIME) or "").strip()
            announce_targets = [t for t in (person.get(CONF_ANNOUNCE_TARGETS) or []) if t]
            if announce_time and announce_targets:
                announce_jobs = []
                if status == STATUS_ALIVE and person.get(CONF_ANNOUNCE_BIRTHDAY):
                    announce_jobs.append((birth, f"{person_id}:announce", "anniversary"))
                elif status == STATUS_DECEASED and person.get(CONF_ANNOUNCE_SOUVENIR):
                    announce_jobs.append((birth, f"{person_id}:announce", "anniversary"))
                if death_date is not None and person.get(CONF_ANNOUNCE_DEATH):
                    announce_jobs.append((death_date, f"{person_id}:death:announce", "death"))

                for trigger_date, announce_key, announce_kind in announce_jobs:
                    announce_sent = notified.get(announce_key, {})
                    due_announce = due_slots(
                        trigger_date, today, now.hour, now.minute,
                        [announce_time], announce_sent,
                    )
                    if due_announce:
                        message = announcement_message(
                            person, announce_kind, trigger_date, today
                        )
                        await _async_send_announcement(hass, person, message)
                        # Always marked as done today, success or not - see
                        # the comment above on why this is never retried.
                        # Keyed by the announce time value itself (there is
                        # only ever one slot here), consistent with the
                        # birthday/death slots above.
                        announce_sent[announce_time] = today_iso
                        notified[announce_key] = announce_sent
                        changed = True
            if default_announce_time and default_announce_targets:
                default_jobs = []
                if status == STATUS_ALIVE and default_announce_birthday:
                    default_jobs.append((birth, f"{person_id}{NOTIFIED_KEY_DEFAULT_ANNOUNCE_SUFFIX}", "anniversary"))
                elif status == STATUS_DECEASED and default_announce_souvenir:
                    default_jobs.append((birth, f"{person_id}{NOTIFIED_KEY_DEFAULT_ANNOUNCE_SUFFIX}", "anniversary"))
                if death_date is not None and default_announce_death:
                    default_jobs.append((death_date, f"{person_id}{NOTIFIED_KEY_DEFAULT_ANNOUNCE_DEATH_SUFFIX}", "death"))
                for trigger_date, announce_key, announce_kind in default_jobs:
                    announce_sent = notified.get(announce_key, {})
                    due_announce = due_slots(
                        trigger_date, today, now.hour, now.minute,
                        [default_announce_time], announce_sent,
                    )
                    if due_announce:
                        message = announcement_message(
                            person, announce_kind, trigger_date, today
                        )
                        await _async_speak(
                            hass, default_announce_tts, default_announce_targets, message, volume=default_announce_volume
                        )
                        announce_sent[default_announce_time] = today_iso
                        notified[announce_key] = announce_sent
                        changed = True

        if changed:
            await data["store"].async_save(
                {"notified": notified, "mobile_sent_today": mobile_sent_today}
            )

        # Always refresh listeners (sensors) so days-remaining / notified-today
        # stay accurate minute to minute, not just when a notification fired.
        async_dispatcher_send(hass, SIGNAL_PEOPLE_UPDATED)


def _alexa_notify_slug(hass, entity_id: str) -> str | None:
    """notify.alexa_media_<slug> service name for this entity, if any.

    Alexa Media Player registers both a media_player entity and a
    notify.alexa_media_<slug> service for the same device. Routing an
    announcement through that notify service with data={"type": "tts"}
    makes the Echo speak in its own native voice, instead of tts.speak -
    which needs a publicly reachable URL for the generated audio file,
    something most home installs (no Nabu Casa Cloud) can't offer
    Amazon's servers, and which fails on-device with "Désolé, je ne
    peux pas accéder à...". Same fix already applied in Programme TNT
    FR's reminders.py.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is None or entry.platform != "alexa_media":
        return None
    slug = "alexa_media_" + entity_id.split(".", 1)[1]
    if hass.services.has_service("notify", slug):
        return slug
    return None


async def _async_restore_volume(hass, player: str, previous_volume: float, message: str) -> None:
    """Attend approximativement la fin de l'annonce puis restaure le volume.

    Plusieurs annonces peuvent viser le même haut-parleur au cours du même
    cycle de vérification (par exemple plusieurs personnes configurées
    avec la même heure d'annonce) : sans compteur, chacune lirait le
    volume déjà modifié par la précédente comme "volume d'origine", et la
    dernière restauration gagnante laisserait le haut-parleur sur une
    valeur de test au lieu de sa vraie valeur de départ. _VOLUME_PENDING_KEY
    compte les annonces encore en cours sur ce haut-parleur ; seule celle
    qui ramène ce compteur à zéro restaure réellement le volume, vers la
    valeur capturée une seule fois avant la toute première modification
    (voir _async_speak).
    """
    words = max(1, len(message.split()))
    delay = min(30.0, max(2.5, words / 2.5 + 1.5))
    await asyncio.sleep(delay)

    pending = hass.data.setdefault(_VOLUME_PENDING_KEY, {})
    remaining = pending.get(player, 1) - 1
    if remaining > 0:
        # Une autre annonce utilise encore ce haut-parleur : c'est sa
        # propre restauration (la dernière à se terminer) qui remettra
        # le volume d'origine - pas celle-ci.
        pending[player] = remaining
        return
    pending.pop(player, None)
    hass.data.setdefault(_VOLUME_BASELINE_KEY, {}).pop(player, None)

    try:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {"volume_level": previous_volume},
            target={"entity_id": player},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error(
            "Anniversary Celebration: échec de la restauration du volume pour %s : %s",
            player,
            err,
        )


async def _async_speak(
    hass, tts_entity: str, media_players: list[str], message: str, volume: float | None = None
) -> bool:
    """Speak message on every given media_player, preferring the Alexa
    device's own native voice (via its notify.alexa_media_<slug> service)
    over tts.speak - see _alexa_notify_slug for why. Falls back to
    tts.speak for any non-Alexa target, or an Alexa device whose notify
    service isn't available for some reason.

    volume, when given, is set on the player before speaking and restored
    afterward (in the background, after an estimated speaking duration),
    the same mechanism as Programme TNT FR's reminders.

    Shared by the per-person announcement path below and the
    integration-level default-announce broadcast - both ultimately just
    need "say this on these speakers", so the actual speak loop and its
    error handling live here once.
    """
    ok = True
    for player in media_players:
        previous_volume = None
        if volume is not None:
            # Capture the true pre-announce volume only once per player
            # per "batch": if another announcement already bumped this
            # same player earlier in this same check cycle and hasn't
            # been restored yet (_VOLUME_BASELINE_KEY already has an
            # entry), reuse ITS baseline instead of reading the current
            # (already-bumped) volume_level - otherwise this announcement
            # would "restore" to the wrong value later. See
            # _async_restore_volume for the matching half of this.
            baseline = hass.data.setdefault(_VOLUME_BASELINE_KEY, {})
            pending = hass.data.setdefault(_VOLUME_PENDING_KEY, {})
            if player not in baseline:
                state = hass.states.get(player)
                if state is not None:
                    baseline[player] = state.attributes.get("volume_level")
            previous_volume = baseline.get(player)
            if previous_volume is not None:
                pending[player] = pending.get(player, 0) + 1
            try:
                await hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"volume_level": volume},
                    target={"entity_id": player},
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Anniversary Celebration: échec du réglage du volume pour %s : %s",
                    player,
                    err,
                )
        alexa_slug = _alexa_notify_slug(hass, player)
        try:
            if alexa_slug:
                await hass.services.async_call(
                    "notify",
                    alexa_slug,
                    {
                        "title": "Anniversary Celebration",
                        "message": message,
                        "data": {"type": "tts"},
                    },
                )
            else:
                await hass.services.async_call(
                    "tts",
                    "speak",
                    {
                        "entity_id": tts_entity,
                        "media_player_entity_id": player,
                        "message": message,
                    },
                    blocking=True,
                )
        except Exception as err:  # noqa: BLE001 - never let a bad target break the loop
            ok = False
            _LOGGER.error(
                "Anniversary Celebration: échec de l'annonce vocale sur %s : %s",
                player,
                err,
            )
        if previous_volume is not None:
            hass.async_create_task(
                _async_restore_volume(hass, player, previous_volume, message)
            )
    return ok

async def _async_send_announcement(hass, person, message: str) -> bool:
    """Speak message on every configured media_player via the configured
    TTS entity.
    Entirely separate from the written notify.* path: its own targets,
    its own TTS entity. Best-effort - a failure here is only logged, never
    raised, and never blocks or retries the written notification.
    """
    tts_entity = (person.get(CONF_ANNOUNCE_TTS_ENTITY) or "").strip()
    media_players = [m for m in (person.get(CONF_ANNOUNCE_TARGETS) or []) if m]
    if not media_players:
        return False
    return await _async_speak(hass, tts_entity, media_players, message, volume=person.get(CONF_ANNOUNCE_VOLUME))
async def _async_send_notification(
    hass,
    person,
    birth,
    today,
    slot_key: str,
    person_mobile_sent: dict[str, dict[str, str]],
    kind: str = "birthday",
    default_targets: list[str] | None = None,
) -> tuple[bool, bool, bool]:
    """Send one due notification-time slot for a person.

    Returns (persisted, mobile_changed, mobile_fully_ok):
    - persisted is True only if the Home Assistant persistent notification
      itself was successfully created - the guaranteed fallback channel this
      feature promises ("always created even if no device was configured or
      it is unreachable").
    - mobile_changed is True only when at least one notify.* device/service
      call was just attempted for this slot (succeeded or not), so the
      caller knows it needs to persist the updated person_mobile_sent to
      survive a restart.
    - mobile_fully_ok is True once every configured target has succeeded
      today for this slot (trivially True when no target is configured).
      The caller only marks a slot as fully done (notified, stops
      retrying) when persisted AND mobile_fully_ok are both True - so a
      single unreachable device keeps this slot "due" and gets retried on
      its own every minute, without the caller ever concluding the slot is
      finished just because the persistent notification succeeded.

    slot_key identifies this notification time (the time value itself,
    e.g. "08:00:00" - see due_slots()'s docstring in util.py for why this
    is no longer the list index). Each target's own success is tracked
    individually in person_mobile_sent[slot_key] (a {target: iso_date}
    map, not a single all-or-nothing flag for the whole slot): a target
    already marked as succeeded today is skipped on a retry, so a device
    that already got its notification is never notified again while a
    sibling device is still being retried - and, conversely, an
    unreachable device is never abandoned just because the others
    succeeded.
    """
    full_name = f"{person.get(CONF_FIRST_NAME, '')} {person.get(CONF_LAST_NAME, '') or ''}".strip()
    age = current_age(birth, today)
    if kind == "death":
        title = "🕯️ Anniversaire de décès"
        message = (
            f"Aujourd'hui est l'anniversaire du décès de {full_name}, "
            f"décédé(e) depuis {age} ans."
        )
    elif person.get(CONF_STATUS, STATUS_ALIVE) == STATUS_ALIVE:
        title = "🎂🎉 Joyeux anniversaire !"
        message = f"{full_name} a {age} ans aujourd'hui !"
    else:
        title = "🕯️ En mémoire"
        message = f"{full_name} aurait eu {age} ans aujourd'hui."

    person_id = person[CONF_PERSON_ID]
    today_iso = today.isoformat()
    # Union of this person's own notify_targets and the integration-level
    # defaults (CONF_DEFAULT_NOTIFY_TARGETS); see util.merge_notify_targets
    # (tested in tests/test_util.py) for the dedup logic.
    targets = merge_notify_targets(
        [t for t in normalize_notify_targets(person) if "." in t],
        [t for t in (default_targets or []) if "." in t],
    )
    sent_targets: dict[str, str] = person_mobile_sent.get(slot_key, {})
    mobile_changed = False

    for target in targets:
        if sent_targets.get(target) == today_iso:
            # Already succeeded today for this specific target - never
            # re-send to it while a sibling target is still being retried.
            continue
        domain, service = target.split(".", 1)
        try:
            await hass.services.async_call(
                domain,
                service,
                {"title": title, "message": message},
                blocking=True,
            )
            sent_targets[target] = today_iso
            mobile_changed = True
        except Exception as err:  # noqa: BLE001 - never let a bad target break the loop
            _LOGGER.error(
                "Anniversary Celebration: échec d'envoi à %s pour %s : %s",
                target,
                full_name,
                err,
            )

    if mobile_changed:
        person_mobile_sent[slot_key] = sent_targets

    mobile_fully_ok = all(sent_targets.get(t) == today_iso for t in targets)

    # Always also raise a persistent notification in Home Assistant itself,
    # so the reminder is never silently lost even if every chosen device/
    # service is unreachable or none was configured.
    persisted = False
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{person_id}_{kind}_{slot_key}_{today_iso}",
            },
            blocking=True,
        )
        persisted = True
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Anniversary Celebration: échec persistent_notification : %s", err)

    _LOGGER.info(
        "Anniversary Celebration: notification [%s] envoyée pour %s (cibles=%s, toutes_ok=%s, persistante=%s)",
        kind,
        full_name,
        "oui" if targets else "non",
        "oui" if mobile_fully_ok else "non",
        "oui" if persisted else "non",
    )

    return persisted, mobile_changed, mobile_fully_ok


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled Lovelace card and register it as a dashboard resource."""
    if not hass.data.get(_CARD_REGISTERED_KEY):
        www_dir = Path(__file__).parent / "www"
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_PATH, str(www_dir / CARD_FILENAME), cache_headers=True)]
        )
        hass.data[_CARD_REGISTERED_KEY] = True

    await _async_sync_lovelace_resource(hass)


async def _async_sync_lovelace_resource(hass: HomeAssistant) -> None:
    """Make sure the card resource is registered (and on the right version).

    hass.data["lovelace"] is a plain dict on some Home Assistant versions
    and a LovelaceData-like object (attribute access, no .get) on others;
    support both instead of assuming one shape, since silently assuming
    the dict shape previously made this a no-op on newer Core versions
    (AttributeError swallowed by the except below, never surfaced).
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            return
        if isinstance(lovelace_data, dict):
            resources = lovelace_data.get("resources")
        else:
            resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            return
        if hasattr(resources, "async_items") and not getattr(resources, "loaded", True):
            await resources.async_load()
        # Read the version from the integration's own manifest.json instead
        # of a hardcoded string here, so this can never drift out of sync
        # with manifest.json (as it previously did: this was hardcoded to
        # "1.0.3" while the manifest still said "1.0.2").
        integration = await async_get_integration(hass, DOMAIN)
        version_tag = integration.manifest.get("version", "0")
        url = f"{CARD_URL_PATH}?v={version_tag}"
        existing = [r for r in resources.async_items() if CARD_FILENAME in r.get("url", "")]
        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
        elif existing[0].get("url") != url:
            await resources.async_update_item(existing[0]["id"], {"res_type": "module", "url": url})
    except Exception as err:  # noqa: BLE001 - resource sync is best-effort
        _LOGGER.warning(
            "Anniversary Celebration: automatic Lovelace resource registration "
            "failed (%s) - add the resource manually: Paramètres > Tableaux de "
            "bord > Ressources > %s",
            err,
            CARD_URL_PATH,
        )
