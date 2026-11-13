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
    CONF_NOTIFY_TARGETS,
    CONF_NOTIFY_TIME,
    CONF_NOTIFY_TIME_2,
    CONF_NOTIFY_TIMES,
    CONF_PEOPLE,
    CONF_PERSON_ID,
    CONF_STATUS,
    DEFAULT_NOTIFY_TIME,
    DOMAIN,
    STATUS_ALIVE,
    STATUS_DECEASED,
)
from .util import normalize_notify_targets, normalize_notify_times, parse_flexible_date

NO_TARGET = "__none__"


def _validate_person_input(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the typed birth date and the optional second notify time.

    Returns a form errors dict (empty when everything is valid). Mutates
    user_input in place to normalize the birth date to ISO once parsed,
    the same way the previous _validate_and_normalize_birth_date did.
    """
    errors: dict[str, str] = {}
    try:
        parsed = parse_flexible_date(user_input[CONF_BIRTH_DATE])
    except (ValueError, KeyError):
        errors[CONF_BIRTH_DATE] = "invalid_date"
    else:
        user_input[CONF_BIRTH_DATE] = parsed.isoformat()

    time_2 = (user_input.get(CONF_NOTIFY_TIME_2) or "").strip()
    if time_2:
        parts = time_2.split(":")
        try:
            # Every part must be purely numeric: "08:30:abc".split(":") is
            # ["08", "30", "abc"], and only checking parts[0]/parts[1] let
            # that through silently (the trailing junk was never looked
            # at). Checking isdigit() on every part, including a 3rd
            # seconds part when present, closes that gap.
            if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
                raise ValueError
            hh, mm = int(parts[0]), int(parts[1])
            ss = int(parts[2]) if len(parts) == 3 else 0
            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                raise ValueError
        except (ValueError, IndexError):
            errors[CONF_NOTIFY_TIME_2] = "invalid_time"

    return errors


def _notify_targets(hass) -> list[dict[str, str]]:
    """Build the list of selectable notify targets."""
    options = []
    try:
        services = hass.services.async_services().get("notify", {})
    except Exception:  # pragma: no cover - defensive
        services = {}
    for service in sorted(services):
        options.append({"value": f"notify.{service}", "label": f"notify.{service}"})
    return options


def _collect_person_fields(user_input: dict[str, Any]) -> dict[str, Any]:
    """Fold the flat form answer into the list-based notify fields.

    The form shows a single primary time (CONF_NOTIFY_TIME) plus an
    optional second time (CONF_NOTIFY_TIME_2) as separate fields, and a
    multi-select for CONF_NOTIFY_TARGETS. This collapses them into the
    CONF_NOTIFY_TIMES / CONF_NOTIFY_TARGETS list fields and drops the
    legacy singular key, so every person saved from now on is stored in
    the current list-based shape (util.normalize_notify_times /
    normalize_notify_targets still read the legacy shape for people
    saved before this change, so they keep working unedited).
    """
    data = dict(user_input)

    primary = (data.pop(CONF_NOTIFY_TIME, None) or DEFAULT_NOTIFY_TIME).strip()
    second = (data.pop(CONF_NOTIFY_TIME_2, None) or "").strip()
    times = [primary] if primary else [DEFAULT_NOTIFY_TIME]
    if second:
        times.append(second)
    data[CONF_NOTIFY_TIMES] = times

    targets = data.pop(CONF_NOTIFY_TARGETS, None) or []
    data[CONF_NOTIFY_TARGETS] = list(targets)

    data.pop(CONF_NOTIFY_TARGET, None)

    return data


def _person_schema(hass, defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    default_times = normalize_notify_times(defaults) if defaults else [DEFAULT_NOTIFY_TIME]
    default_time_2 = default_times[1] if len(default_times) > 1 else ""
    return vol.Schema(
        {
            vol.Required(
                CONF_FIRST_NAME, default=defaults.get(CONF_FIRST_NAME, "")
            ): str,
            vol.Optional(
                CONF_LAST_NAME, default=defaults.get(CONF_LAST_NAME, "")
            ): str,
            # Typed text, not selector.DateSelector(): its calendar widget has
            # no quick year jump, so reaching an old birth date (e.g. 1949)
            # means clicking "previous month" dozens of times. Typing the
            # date (ISO or day/month/year) is validated and normalized in
            # async_step_add_person / async_step_edit_person below.
            vol.Required(
                CONF_BIRTH_DATE, default=defaults.get(CONF_BIRTH_DATE, "")
            ): str,
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
                default=default_times[0],
            ): selector.TimeSelector(),
            # Plain str, not selector.TimeSelector(): HA selectors reject a
            # None/empty default for a TimeSelector, and this field must stay
            # optional since most people only need one notification time.
            # Typed HH:MM is validated in _validate_person_input above.
            vol.Optional(
                CONF_NOTIFY_TIME_2,
                default=default_time_2,
            ): str,
            vol.Optional(
                CONF_NOTIFY_TARGETS,
                default=normalize_notify_targets(defaults) if defaults else [],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_notify_targets(hass),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
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
            errors = _validate_person_input(user_input)
            if not errors:
                person = {
                    CONF_PERSON_ID: uuid.uuid4().hex,
                    **_collect_person_fields(user_input),
                }
                people = self._people
                people.append(person)
                return self._save(people)
        return self.async_show_form(
            step_id="add_person",
            data_schema=_person_schema(self.hass, user_input),
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

        errors: dict[str, str] = {}
        if user_input is not None and "person" not in user_input:
            errors = _validate_person_input(user_input)
            if not errors:
                updated = {
                    CONF_PERSON_ID: self._selected_id,
                    **_collect_person_fields(user_input),
                }
                new_people = [
                    updated if p[CONF_PERSON_ID] == self._selected_id else p
                    for p in people
                ]
                return self._save(new_people)
            current = user_input

        return self.async_show_form(
            step_id="edit_person",
            data_schema=_person_schema(self.hass, current),
            errors=errors,
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
