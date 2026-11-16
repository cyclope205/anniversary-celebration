"""Config and options flow for Anniversary Celebration."""
from __future__ import annotations

import uuid
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ANNOUNCE_BIRTHDAY,
    CONF_ANNOUNCE_DEATH,
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
    CONF_DEFAULT_ANNOUNCE_TTS_ENTITY,
    CONF_DEFAULT_NOTIFY_TARGETS,
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

        # A second slot at the same minute would send the same reminder
        # twice. Compare normalized clock values, so 08:30 and 08:30:00
        # are treated as duplicates too.
        if CONF_NOTIFY_TIME_2 not in errors:
            primary = (user_input.get(CONF_NOTIFY_TIME) or DEFAULT_NOTIFY_TIME).strip()
            normalized = normalize_notify_times(
                {CONF_NOTIFY_TIMES: [primary, time_2]}
            )
            if len(normalized) < 2:
                errors[CONF_NOTIFY_TIME_2] = "invalid_time"

    # Optional: only meaningful when CONF_STATUS is Décédé(e), but always
    # validated/normalized here regardless of status, same as the other
    # fields above. Triggers its own independent yearly reminder, separate
    # from the birthday "souvenir" notification.
    death_date_raw = (user_input.get(CONF_DEATH_DATE) or "").strip()
    if death_date_raw:
        try:
            parsed_death = parse_flexible_date(death_date_raw)
        except ValueError:
            errors[CONF_DEATH_DATE] = "invalid_date"
        else:
            user_input[CONF_DEATH_DATE] = parsed_death.isoformat()
            if CONF_BIRTH_DATE not in errors and parsed_death < parsed:
                errors[CONF_DEATH_DATE] = "death_before_birth"

    # Same HH:MM[:SS] validation as CONF_NOTIFY_TIME_2 above, for the
    # optional spoken-announcement time.
    announce_time_raw = (user_input.get(CONF_ANNOUNCE_TIME) or "").strip()
    if announce_time_raw:
        parts = announce_time_raw.split(":")
        try:
            if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
                raise ValueError
            hh, mm = int(parts[0]), int(parts[1])
            ss = int(parts[2]) if len(parts) == 3 else 0
            if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                raise ValueError
        except (ValueError, IndexError):
            errors[CONF_ANNOUNCE_TIME] = "invalid_time"

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
    # Normalize here as a final safeguard for existing/imported data too.
    data[CONF_NOTIFY_TIMES] = normalize_notify_times({CONF_NOTIFY_TIMES: times})

    targets = data.pop(CONF_NOTIFY_TARGETS, None) or []
    data[CONF_NOTIFY_TARGETS] = list(targets)

    data.pop(CONF_NOTIFY_TARGET, None)

    # Death date: stored only when actually provided, never as an empty
    # string, so util/__init__ code can treat its mere presence as "this
    # person has a death date configured" without an extra truthiness check.
    death_date = (data.pop(CONF_DEATH_DATE, None) or "").strip()
    if death_date:
        data[CONF_DEATH_DATE] = death_date

    # Spoken announcement fields: always normalized to a concrete value
    # (never left missing), so a person saved before this feature existed
    # and one saved after look identical once saved - no legacy fallback
    # needed, unlike the notify_time / notify_target fields above.
    data[CONF_ANNOUNCE_TARGETS] = list(data.get(CONF_ANNOUNCE_TARGETS) or [])
    data[CONF_ANNOUNCE_TTS_ENTITY] = (data.get(CONF_ANNOUNCE_TTS_ENTITY) or "").strip()
    data[CONF_ANNOUNCE_TIME] = (data.get(CONF_ANNOUNCE_TIME) or "").strip()
    data[CONF_ANNOUNCE_BIRTHDAY] = bool(data.get(CONF_ANNOUNCE_BIRTHDAY, False))
    data[CONF_ANNOUNCE_SOUVENIR] = bool(data.get(CONF_ANNOUNCE_SOUVENIR, False))
    data[CONF_ANNOUNCE_DEATH] = bool(data.get(CONF_ANNOUNCE_DEATH, False))

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
            # Only used when CONF_STATUS is Décédé(e); see
            # _validate_person_input for the "not before birth date" check.
            # Independent from the birthday "souvenir" reminder: triggers
            # its own yearly death-anniversary notification.
            vol.Optional(
                CONF_DEATH_DATE, default=defaults.get(CONF_DEATH_DATE, "")
            ): str,
            # Spoken announcement (TTS), entirely separate from the written
            # notify_targets above: its own media_player targets, its own
            # TTS entity, its own time, and its own three opt-in toggles
            # (all default False, so nobody gets an unexpected spoken
            # announcement just from configuring notify_targets).
            vol.Optional(
                CONF_ANNOUNCE_TARGETS,
                default=defaults.get(CONF_ANNOUNCE_TARGETS, []),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player", multiple=True)
            ),
            vol.Optional(
                CONF_ANNOUNCE_TTS_ENTITY,
                default=defaults.get(CONF_ANNOUNCE_TTS_ENTITY, ""),
            ): vol.Any(
                "",
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="tts")
                ),
            ),
            # Plain str like CONF_NOTIFY_TIME_2 above, for the same reason:
            # must stay optional. An empty value here simply means the
            # spoken announcement never fires, regardless of the toggles.
            vol.Optional(
                CONF_ANNOUNCE_TIME, default=defaults.get(CONF_ANNOUNCE_TIME, "")
            ): str,
            vol.Optional(
                CONF_ANNOUNCE_BIRTHDAY,
                default=defaults.get(CONF_ANNOUNCE_BIRTHDAY, False),
            ): bool,
            vol.Optional(
                CONF_ANNOUNCE_SOUVENIR,
                default=defaults.get(CONF_ANNOUNCE_SOUVENIR, False),
            ): bool,
            vol.Optional(
                CONF_ANNOUNCE_DEATH,
                default=defaults.get(CONF_ANNOUNCE_DEATH, False),
            ): bool,
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
        # Preserve any other top-level option (e.g.
        # CONF_DEFAULT_NOTIFY_TARGETS): async_create_entry's data replaces
        # config_entry.options wholesale, it does not merge, so overwriting
        # with {CONF_PEOPLE: people} alone would silently wipe out the
        # integration-level default targets.
        options = dict(self.config_entry.options)
        options[CONF_PEOPLE] = people
        return self.async_create_entry(title="", data=options)

    def _save_default_targets(self, targets: list[str]):
        options = dict(self.config_entry.options)
        options[CONF_DEFAULT_NOTIFY_TARGETS] = targets
        return self.async_create_entry(title="", data=options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        people = self._people
        menu_options = ["add_person"]
        if people:
            menu_options += ["edit_person", "remove_person"]
        menu_options += ["default_targets"]
        menu_options += ["default_announce"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_default_targets(
        self, user_input: dict[str, Any] | None = None
    ):
        """Integration-level notify.* targets added to every notification,
        on top of each person's own notify_targets (see __init__.py's
        _async_send_notification, which unions the two lists)."""
        if user_input is not None:
            return self._save_default_targets(
                list(user_input.get(CONF_DEFAULT_NOTIFY_TARGETS, []))
            )
        current = self.config_entry.options.get(CONF_DEFAULT_NOTIFY_TARGETS, [])
        return self.async_show_form(
            step_id="default_targets",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEFAULT_NOTIFY_TARGETS, default=current
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_notify_targets(self.hass),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    )
                }
            ),
        )

    def _save_default_announce(self, values: dict[str, Any]):
        options = dict(self.config_entry.options)
        options[CONF_DEFAULT_ANNOUNCE_TARGETS] = list(
            values.get(CONF_DEFAULT_ANNOUNCE_TARGETS) or []
        )
        options[CONF_DEFAULT_ANNOUNCE_TTS_ENTITY] = (
            values.get(CONF_DEFAULT_ANNOUNCE_TTS_ENTITY) or ""
        ).strip()
        options[CONF_DEFAULT_ANNOUNCE_TIME] = (
            values.get(CONF_DEFAULT_ANNOUNCE_TIME) or ""
        ).strip()
        options[CONF_DEFAULT_ANNOUNCE_BIRTHDAY] = bool(
            values.get(CONF_DEFAULT_ANNOUNCE_BIRTHDAY, False)
        )
        options[CONF_DEFAULT_ANNOUNCE_SOUVENIR] = bool(
            values.get(CONF_DEFAULT_ANNOUNCE_SOUVENIR, False)
        )
        options[CONF_DEFAULT_ANNOUNCE_DEATH] = bool(
            values.get(CONF_DEFAULT_ANNOUNCE_DEATH, False)
        )
        return self.async_create_entry(title="", data=options)

    async def async_step_default_announce(
        self, user_input: dict[str, Any] | None = None
    ):
        """Integration-level default spoken announcement: its own
        media_player targets, TTS entity, time and three opt-in toggles,
        fired as an independent broadcast in __init__.py's
        _async_check_and_notify - see const.py's CONF_DEFAULT_ANNOUNCE_*
        comment for why this is never merged into each person's own
        announce_* settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            time_raw = (user_input.get(CONF_DEFAULT_ANNOUNCE_TIME) or "").strip()
            if time_raw:
                parts = time_raw.split(":")
                try:
                    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
                        raise ValueError
                    hh, mm = int(parts[0]), int(parts[1])
                    ss = int(parts[2]) if len(parts) == 3 else 0
                    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
                        raise ValueError
                except (ValueError, IndexError):
                    errors[CONF_DEFAULT_ANNOUNCE_TIME] = "invalid_time"
            if not errors:
                return self._save_default_announce(user_input)
        current = self.config_entry.options
        return self.async_show_form(
            step_id="default_announce",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_TARGETS,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_TARGETS, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="media_player", multiple=True
                        )
                    ),
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_TTS_ENTITY,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_TTS_ENTITY, ""),
                    ): vol.Any(
                "",
                selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="tts")
                ),
                    ),
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_TIME,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_TIME, ""),
                    ): str,
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_BIRTHDAY,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_BIRTHDAY, False),
                    ): bool,
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_SOUVENIR,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_SOUVENIR, False),
                    ): bool,
                    vol.Optional(
                        CONF_DEFAULT_ANNOUNCE_DEATH,
                        default=current.get(CONF_DEFAULT_ANNOUNCE_DEATH, False),
                    ): bool,
                }
            ),
                errors=errors,
        )
