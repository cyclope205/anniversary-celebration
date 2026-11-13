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
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import (
    CARD_FILENAME,
    CARD_URL_PATH,
    CONF_BIRTH_DATE,
    CONF_FIRST_NAME,
    CONF_LAST_NAME,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DOMAIN,
    PLATFORMS,
    SIGNAL_PEOPLE_UPDATED,
    STATUS_ALIVE,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .util import (
    current_age,
    due_slots,
    normalize_notify_targets,
    normalize_notify_times,
    parse_birth_date,
)

_LOGGER = logging.getLogger(__name__)

_CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"


def _migrate_slot_map(raw: dict) -> dict:
    """Convert a legacy flat {person_id: iso_date} map to the per-slot
    {person_id: {"0": iso_date}} shape used for multi-time support.

    Each configured notification time is tracked independently (slot
    index "0", "1", ...), so a person with two notification times can
    have one already sent today and the other still pending. Entries
    already in the new shape (dict values) pass through unchanged.
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

    # Storage format: {"notified": {person_id: {slot_index: iso_date}},
    # "mobile_sent_today": {person_id: {slot_index: {target: iso_date}}}}.
    # One entry per configured notification time (slot_index is "0", "1",
    # ...), so a person with two notification times tracks each
    # independently, and each notify.* target within a slot tracks its own
    # success independently too. Older versions of this integration saved
    # progressively flatter shapes - see _migrate_slot_map and
    # _migrate_mobile_sent_map - so existing installs don't lose their
    # notified-today state on upgrade.
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
        # person_id -> {slot_index: {target: iso_date}}: which notify.*
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

        for person in people:
            try:
                birth = parse_birth_date(person[CONF_BIRTH_DATE])
            except (KeyError, ValueError):
                continue

            person_id = person[CONF_PERSON_ID]
            notify_times = normalize_notify_times(person)
            person_notified = notified.get(person_id, {})
            due = due_slots(
                birth, today, now.hour, now.minute, notify_times, person_notified
            )
            if not due:
                continue

            person_mobile_sent = mobile_sent_today.get(person_id, {})
            for slot_index in due:
                persisted, mobile_changed, mobile_fully_ok = await _async_send_notification(
                    hass, person, birth, today, slot_index, person_mobile_sent
                )
                if persisted and mobile_fully_ok:
                    person_notified[str(slot_index)] = today_iso
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

        if changed:
            await data["store"].async_save(
                {"notified": notified, "mobile_sent_today": mobile_sent_today}
            )

        # Always refresh listeners (sensors) so days-remaining / notified-today
        # stay accurate minute to minute, not just when a notification fired.
        async_dispatcher_send(hass, SIGNAL_PEOPLE_UPDATED)


async def _async_send_notification(
    hass, person, birth, today, slot_index: int, person_mobile_sent: dict[str, dict[str, str]]
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

    Each target's own success is tracked individually in
    person_mobile_sent[slot_key] (a {target: iso_date} map, not a single
    all-or-nothing flag for the whole slot): a target already marked as
    succeeded today is skipped on a retry, so a device that already got
    its notification is never notified again while a sibling device is
    still being retried - and, conversely, an unreachable device is never
    abandoned just because the others succeeded.
    """
    full_name = f"{person.get(CONF_FIRST_NAME, '')} {person.get(CONF_LAST_NAME, '') or ''}".strip()
    age = current_age(birth, today)
    if person.get(CONF_STATUS, STATUS_ALIVE) == STATUS_ALIVE:
        title = "🎂🎉 Joyeux anniversaire !"
        message = f"{full_name} a {age} ans aujourd'hui !"
    else:
        title = "🕯️ En mémoire"
        message = f"{full_name} aurait eu {age} ans aujourd'hui."

    person_id = person[CONF_PERSON_ID]
    today_iso = today.isoformat()
    targets = [t for t in normalize_notify_targets(person) if "." in t]
    slot_key = str(slot_index)
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
                "notification_id": f"{DOMAIN}_{person_id}_{slot_key}_{today_iso}",
            },
            blocking=True,
        )
        persisted = True
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Anniversary Celebration: échec persistent_notification : %s", err)

    _LOGGER.info(
        "Anniversary Celebration: notification envoyée pour %s (cibles=%s, toutes_ok=%s, persistante=%s)",
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
