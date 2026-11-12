"""Sensor platform for Anniversary Celebration — one entity per person."""
from __future__ import annotations

from datetime import date

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    CONF_BIRTH_DATE,
    CONF_FIRST_NAME,
    CONF_LAST_NAME,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_TIME,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DOMAIN,
    SIGNAL_PEOPLE_UPDATED,
    STATUS_ALIVE,
)
from .util import age_at_next_anniversary, current_age, days_until, parse_birth_date


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

    def _handle_update(self) -> None:
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
        attrs = {
            "attribution": ATTRIBUTION,
            "person_id": person_id,
            "first_name": self._person.get(CONF_FIRST_NAME, ""),
            "last_name": self._person.get(CONF_LAST_NAME, "") or "",
            "status": self._person.get(CONF_STATUS, STATUS_ALIVE),
            "notify_time": self._person.get(CONF_NOTIFY_TIME),
            "notify_target": self._person.get(CONF_NOTIFY_TARGET),
            "notified_today": notified.get(person_id) == today.isoformat(),
        }
        if birth is not None:
            attrs["date"] = birth.isoformat()
            attrs["current_years"] = current_age(birth, today)
            attrs["years_at_anniversary"] = age_at_next_anniversary(birth, today)
        return attrs

    def _birth_date(self) -> date | None:
        try:
            return parse_birth_date(self._person[CONF_BIRTH_DATE])
        except (KeyError, ValueError):
            return None
