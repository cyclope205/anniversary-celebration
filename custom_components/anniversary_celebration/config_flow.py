"""Config and options flow for Anniversary Celebration."""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BIRTH_DATE,
    CONF_FIRST_NAME,
    CONF_LAST_NAME,
    CONF_NOTIFY_TARGET,
    CONF_NOTIFY_TIME,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DEFAULT_NOTIFY_TIME,
    DOMAIN,
    STATUS_ALIVE,
    STATUS_DECEASED,
)

NO_TARGET = "__none__"


def _notify_targets(hass) -> list[dict[str, str]]:
    """Build the list of selectable notify targets."""
    options = [{"value": NO_TARGET, "label": "(Aucun appareil / optionnel)"}]
    try:
        services = hass.services.async_services().get("notify", {})
    except Exception:  # pragma: no cover - defensive
        services = {}
    for service in sorted(services):
        options.append({"value": f"notify.{service}", "label": f"notify.{service}"})
    return options


def _person_schema(hass, defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_FIRST_NAME, default=defaults.get(CONF_FIRST_NAME, "")
            ): str,
            vol.Optional(
                CONF_LAST_NAME, default=defaults.get(CONF_LAST_NAME, "")
            ): str,
            vol.Required(
                CONF_BIRTH_DATE, default=defaults.get(CONF_BIRTH_DATE)
            ): selector.DateSelector(),
            vol.Required(
                CONF_STATUS, default=defaults.get(CONF_STATUS, STATUS_ALIVE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {"value": STATUS_ALIVE, "label": "Vivant(e)"},
                        {"value": STATUS_DECEASED, "label": "Décédé(e)"},
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                    translation_key="status",
                )
            ),
            vol.Optional(
                CONF_NOTIFY_TIME,
                default=defaults.get(CONF_NOTIFY_TIME, DEFAULT_NOTIFY_TIME),
            ): selector.TimeSelector(),
            vol.Optional(
                CONF_NOTIFY_TARGET,
                default=defaults.get(CONF_NOTIFY_TARGET, NO_TARGET) or NO_TARGET,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_notify_targets(hass),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class AnniversaryCelebrationConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the (single instance) initial setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Anniversary Celebration", data={}, options={CONF_PEOPLE: []}
            )
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AnniversaryCelebrationOptionsFlow(config_entry)


class AnniversaryCelebrationOptionsFlow(config_entries.OptionsFlow):
    """Manage the people list (add / edit / remove)."""

    def __init__(self, config_entry) -> None:
        # Do NOT assign self.config_entry here: on current Home Assistant
        # versions, OptionsFlow.config_entry is a read-only property
        # already populated by the base class from the flow context, and
        # assigning to it raises AttributeError ("has no setter"). Only
        # the selection state specific to this flow is stored here.
        self._selected_id: str | None = None

    @property
    def _people(self) -> list[dict[str, Any]]:
        return list(self.config_entry.options.get(CONF_PEOPLE, []))

    def _save(self, people: list[dict[str, Any]]):
        return self.async_create_entry(title="", data={CONF_PEOPLE: people})

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        people = self._people
        menu_options = ["add_person"]
        if people:
            menu_options += ["edit_person", "remove_person"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_add_person(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            target = user_input.get(CONF_NOTIFY_TARGET)
            if target == NO_TARGET:
                user_input[CONF_NOTIFY_TARGET] = None
            person = {CONF_PERSON_ID: uuid.uuid4().hex, **user_input}
            people = self._people
            people.append(person)
            return self._save(people)
        return self.async_show_form(
            step_id="add_person",
            data_schema=_person_schema(self.hass),
            errors=errors,
        )

    async def async_step_edit_person(self, user_input: dict[str, Any] | None = None):
        people = self._people
        if user_input is not None and self._selected_id is None:
            self._selected_id = user_input["person"]
            return await self.async_step_edit_person()

        if self._selected_id is None:
            return self.async_show_form(
                step_id="edit_person",
                data_schema=vol.Schema(
                    {
                        vol.Required("person"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    {
                                        "value": p[CONF_PERSON_ID],
                                        "label": f"{p[CONF_FIRST_NAME]} {p.get(CONF_LAST_NAME, '')}".strip(),
                                    }
                                    for p in people
                                ],
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            )
                        )
                    }
                ),
            )

        current = next(
            (p for p in people if p[CONF_PERSON_ID] == self._selected_id), None
        )
        if current is None:
            self._selected_id = None
            return await self.async_step_init()

        if user_input is not None and "person" not in user_input:
            updated = {CONF_PERSON_ID: self._selected_id, **user_input}
            if updated.get(CONF_NOTIFY_TARGET) == NO_TARGET:
                updated[CONF_NOTIFY_TARGET] = None
            new_people = [
                updated if p[CONF_PERSON_ID] == self._selected_id else p
                for p in people
            ]
            return self._save(new_people)

        return self.async_show_form(
            step_id="edit_person",
            data_schema=_person_schema(self.hass, current),
        )

    async def async_step_remove_person(self, user_input: dict[str, Any] | None = None):
        people = self._people
        if user_input is not None:
            new_people = [
                p for p in people if p[CONF_PERSON_ID] != user_input["person"]
            ]
            return self._save(new_people)
        return self.async_show_form(
            step_id="remove_person",
            data_schema=vol.Schema(
                {
                    vol.Required("person"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": p[CONF_PERSON_ID],
                                    "label": f"{p[CONF_FIRST_NAME]} {p.get(CONF_LAST_NAME, '')}".strip(),
                                }
                                for p in people
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
