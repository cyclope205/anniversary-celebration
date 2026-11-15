"""Sensor platform for Anniversary Celebration — one entity per person."""
from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    CONF_ANNOUNCE_BIRTHDAY,
    CONF_ANNOUNCE_DEATH,
    CONF_ANNOUNCE_SOUVENIR,
    CONF_ANNOUNCE_TARGETS,
    CONF_ANNOUNCE_TIME,
    CONF_ANNOUNCE_TTS_ENTITY,
    CONF_BIRTH_DATE,
    CONF_DEATH_DATE,
    CONF_FIRST_NAME,
    CONF_LAST_NAME,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DOMAIN,
    NOTIFIED_KEY_DEATH_SUFFIX,
    SIGNAL_PEOPLE_UPDATED,
    STATUS_ALIVE,
)
from .util import (
    age_at_next_anniversary,
    current_age,
    days_until,
    normalize_notify_targets,
    normalize_notify_times,
    parse_birth_date,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    people = entry.options.get(CONF_PEOPLE, [])
    async_add_entities(
        [AnniversaryPersonSensor(hass, entry, person) for person in people]
    )


class AnniversaryPersonSensor(SensorEntity):
    """Days remaining until a person's next anniversary."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:cake-variant"
    _attr_native_unit_of_measurement = "jours"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, person: dict) -> None:
        self.hass = hass
        self._entry = entry
        self._person = person
        person_id = person[CONF_PERSON_ID]
        self._attr_unique_id = f"{entry.entry_id}_{person_id}"
        first = person.get(CONF_FIRST_NAME, "")
        last = person.get(CONF_LAST_NAME, "") or ""
        self._attr_name = f"{first} {last}".strip()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_PEOPLE_UPDATED, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        # Without @callback, Home Assistant doesn't know this dispatcher
        # signal handler is safe to run directly on the event loop, and
        # dispatches it to an executor thread instead - which is exactly
        # what async_write_ha_state must never be called from (see
        # https://contributors.home-assistant.io/core/internals/thread-safety/).
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        birth = self._birth_date()
        if birth is None:
            return None
        return days_until(birth, dt_util.now().date())

    @property
    def extra_state_attributes(self) -> dict:
        birth = self._birth_date()
        today = dt_util.now().date()
        person_id = self._person[CONF_PERSON_ID]
        notified = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get(
            "notified", {}
        )
        # Per-slot shape is {slot_index: iso_date}; a person is "notified
        # today" if any of their configured notification-time slots fired
        # today. A bare string value is the legacy pre-multi-time shape,
        # handled for safety even though __init__.py migrates it on load.
        person_notified = notified.get(person_id, {})
        today_iso = today.isoformat()
        if isinstance(person_notified, dict):
            notified_today = today_iso in person_notified.values()
        else:
            notified_today = person_notified == today_iso
        attrs = {
            "attribution": ATTRIBUTION,
            "person_id": person_id,
            "first_name": self._person.get(CONF_FIRST_NAME, ""),
            "last_name": self._person.get(CONF_LAST_NAME, "") or "",
            "status": self._person.get(CONF_STATUS, STATUS_ALIVE),
            "notify_times": normalize_notify_times(self._person),
            "notify_targets": normalize_notify_targets(self._person),
            "notified_today": notified_today,
        }
        if birth is not None:
            attrs["date"] = birth.isoformat()
            attrs["current_years"] = current_age(birth, today)
            attrs["years_at_anniversary"] = age_at_next_anniversary(birth, today)

        # Death anniversary (Feature A): independent from the birthday
        # "souvenir" reminder above, and only present at all when a death
        # date is actually configured.
        death_date_raw = self._person.get(CONF_DEATH_DATE)
        if death_date_raw:
            try:
                death_date = date.fromisoformat(death_date_raw)
            except ValueError:
                death_date = None
            if death_date is not None:
                death_key = f"{person_id}{NOTIFIED_KEY_DEATH_SUFFIX}"
                death_notified = notified.get(death_key, {})
                if isinstance(death_notified, dict):
                    notified_death_today = today_iso in death_notified.values()
                else:
                    notified_death_today = death_notified == today_iso
                attrs["death_date"] = death_date.isoformat()
                attrs["years_since_death"] = current_age(death_date, today)
                attrs["notified_death_today"] = notified_death_today

        # Spoken announcement config (Feature C): exposed mainly so the
        # bundled card and any automation/template can see what is
        # configured, same spirit as notify_times/notify_targets above.
        attrs["announce_targets"] = list(self._person.get(CONF_ANNOUNCE_TARGETS) or [])
        attrs["announce_tts_entity"] = self._person.get(CONF_ANNOUNCE_TTS_ENTITY) or ""
        attrs["announce_time"] = self._person.get(CONF_ANNOUNCE_TIME) or ""
        attrs["announce_birthday"] = bool(self._person.get(CONF_ANNOUNCE_BIRTHDAY, False))
        attrs["announce_souvenir"] = bool(self._person.get(CONF_ANNOUNCE_SOUVENIR, False))
        attrs["announce_death"] = bool(self._person.get(CONF_ANNOUNCE_DEATH, False))

        return attrs

    def _birth_date(self) -> date | None:
        try:
            return parse_birth_date(self._person[CONF_BIRTH_DATE])
        except (KeyError, ValueError):
            return None
