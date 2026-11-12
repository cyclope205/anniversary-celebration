"""Anniversary Celebration integration.

Tracks birthdays (living and deceased) and sends a notification on the day,
with a persisted "already notified" record so a restart never causes a
duplicate, and a per-minute recheck so a restart never causes a miss either.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CARD_FILENAME,
    CARD_URL_PATH,
    CONF_BIRTH_DATE,
    CONF_FIRST_NAME,
    CONF_LAST_NAME,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_TIME,
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
from .util import current_age, parse_birth_date, should_notify

_LOGGER = logging.getLogger(__name__)

_CARD_REGISTERED_KEY = f"{DOMAIN}_card_registered"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Anniversary Celebration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{entry.entry_id}")
    notified: dict[str, str] = await store.async_load() or {}

    hass.data[DOMAIN][entry.entry_id] = {
        "store": store,
        "notified": notified,
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
    """Evaluate every person; notify + persist if today is the day and the
    configured time has been reached, guarding against duplicates."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return

    people = entry.options.get(CONF_PEOPLE, [])
    if not people:
        return

    now = dt_util.now()
    today = now.date()
    today_iso = today.isoformat()
    notified: dict[str, str] = data["notified"]
    changed = False

    for person in people:
        try:
            birth = parse_birth_date(person[CONF_BIRTH_DATE])
        except (KeyError, ValueError):
            continue

        person_id = person[CONF_PERSON_ID]
        if not should_notify(
            birth,
            today,
            now.hour,
            now.minute,
            person.get(CONF_NOTIFY_TIME),
            notified.get(person_id),
        ):
            continue

        await _async_send_notification(hass, person, birth, today)
        notified[person_id] = today_iso
        changed = True

    if changed:
        await data["store"].async_save(notified)

    # Always refresh listeners (sensors) so days-remaining / notified-today
    # stay accurate minute to minute, not just when a notification fired.
    async_dispatcher_send(hass, SIGNAL_PEOPLE_UPDATED)


async def _async_send_notification(hass, person, birth, today) -> None:
    full_name = f"{person.get(CONF_FIRST_NAME, '')} {person.get(CONF_LAST_NAME, '') or ''}".strip()
    age = current_age(birth, today)
    if person.get(CONF_STATUS, STATUS_ALIVE) == STATUS_ALIVE:
        title = "🎂🎉 Joyeux anniversaire !"
        message = f"{full_name} a {age} ans aujourd'hui !"
    else:
        title = "🕯️ En mémoire"
        message = f"{full_name} aurait eu {age} ans aujourd'hui."

    target = person.get(CONF_NOTIFY_TARGET)
    sent = False
    if target and "." in target:
        domain, service = target.split(".", 1)
        try:
            await hass.services.async_call(
                domain,
                service,
                {"title": title, "message": message},
                blocking=True,
            )
            sent = True
        except Exception as err:  # noqa: BLE001 - never let a bad target break the loop
            _LOGGER.error(
                "Anniversary Celebration: échec d'envoi à %s pour %s : %s",
                target,
                full_name,
                err,
            )

    # Always also raise a persistent notification in Home Assistant itself,
    # so the reminder is never silently lost even if the chosen device/
    # service is unreachable or none was configured.
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{person[CONF_PERSON_ID]}_{today.isoformat()}",
            },
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Anniversary Celebration: échec persistent_notification : %s", err)

    _LOGGER.info(
        "Anniversary Celebration: notification envoyée pour %s (cible device=%s)",
        full_name,
        "oui" if sent else "non",
    )


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
    """Make sure the card resource is registered (and on the right version)."""
    try:
        resources = hass.data.get("lovelace", {}).get("resources")
        if resources is None:
            return
        if hasattr(resources, "async_items") and not getattr(resources, "loaded", True):
            await resources.async_load()
        version_tag = "1.0.0"
        url = f"{CARD_URL_PATH}?v={version_tag}"
        existing = [r for r in resources.async_items() if CARD_FILENAME in r.get("url", "")]
        if not existing:
            await resources.async_create_item({"res_type": "module", "url": url})
        elif existing[0].get("url") != url:
            await resources.async_update_item(existing[0]["id"], {"res_type": "module", "url": url})
    except Exception as err:  # noqa: BLE001 - resource sync is best-effort
        _LOGGER.debug("Anniversary Celebration: resource sync skipped (%s)", err)
