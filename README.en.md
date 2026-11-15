# 🎂 Anniversary Celebration

🇫🇷 [Version française](README.md)

[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/cyclope205/anniversary-celebration)](https://github.com/cyclope205/anniversary-celebration/releases)
[![Build](https://github.com/cyclope205/anniversary-celebration/actions/workflows/validate.yml/badge.svg)](https://github.com/cyclope205/anniversary-celebration/actions/workflows/validate.yml)
[![Tests](https://github.com/cyclope205/anniversary-celebration/actions/workflows/tests.yml/badge.svg)](https://github.com/cyclope205/anniversary-celebration/actions/workflows/tests.yml)
[![Issues](https://img.shields.io/github/issues/cyclope205/anniversary-celebration)](https://github.com/cyclope205/anniversary-celebration/issues)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/cyclope205/anniversary-celebration/blob/main/LICENSE)
[![Downloads](https://img.shields.io/github/downloads/cyclope205/anniversary-celebration/total)](https://github.com/cyclope205/anniversary-celebration/releases)
[![Downloads latest](https://img.shields.io/github/downloads/cyclope205/anniversary-celebration/latest/total)](https://github.com/cyclope205/anniversary-celebration/releases/latest)
[![Stars](https://img.shields.io/github/stars/cyclope205/anniversary-celebration)](https://github.com/cyclope205/anniversary-celebration/stargazers)
[![Forks](https://img.shields.io/github/forks/cyclope205/anniversary-celebration)](https://github.com/cyclope205/anniversary-celebration/network/members)

---

### ❤️ GitHub Sponsors

<!--START_SECTION:github-sponsors-->
<!-- No active public GitHub sponsor at the moment -->
<!--END_SECTION:github-sponsors-->

---
### ☕ Thanks to our supporters

<!--START_SECTION:paypal-->

<!--END_SECTION:paypal-->

<!--START_SECTION:buy-me-a-coffee-->
<!-- New donations will be added here automatically -->
<!--END_SECTION:buy-me-a-coffee-->

---

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-cyclope205-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://bmc-eight-red.vercel.app/api/donate?repo=anniversary-celebration) [![PayPal](https://img.shields.io/badge/PayPal-Donate-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://bmc-eight-red.vercel.app/api/paypal?repo=anniversary-celebration&amount=5)
<img src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/custom_components/anniversary_celebration/brand/icon.png" alt="Anniversary Celebration" width="32">

### ☕ Buy me a coffee to help me stay awake and keep building your favorite integrations!

As a thank you, your name will appear (anonymized) in the "☕ Thanks to our supporters" section above.

---

Home Assistant integration that tracks the birthdays of living people and keeps the memory of those who have passed away, with a reliable notification on the day and a Lovelace card that builds itself.

## Table of contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Installation](#installation-hacs)
- [Configuration](#configuration)
- [Card — configuration](#card--configuration)
- [Notification reliability](#notification-reliability)
- [Available languages](#available-languages)
- [Tests](#tests)
- [Good to know](#good-to-know)

## Features

- Add/edit/remove people through the UI (Settings →
Devices & services → Anniversary Celebration → Configure): first name, last name,
date of birth, status (alive / deceased), up to two notification times
(optional), one or more devices/services to notify (optional).
- One sensor per person (`sensor.<first_name>_<last_name>`): number of days until the
next birthday, current age, age at the next birthday, date of
birth, status, and whether today's notification has already been sent.
- Deceased people can also be notified (a different "in
memory" message instead of the living one).
- Independent reminder for the death anniversary (if a death date is set):
a separate trigger from the birthday one, with its own anti-duplicate
tracking.
- Integration-level default notification targets (options menu), added
automatically on top of each person's own targets — handy for notifying a
shared device without configuring it on every person.
- Optional spoken announcement (text-to-speech), entirely independent from
the written notifications above: its own speakers, its own TTS engine, its
own time, and three separate opt-in checkboxes (birthday, in memory, death
anniversary), all off by default.
- `anniversary-celebration-card` card: builds itself automatically from
the configured people (no need to touch the dashboard YAML on every
addition), sorted by proximity, with a 🔔 next to the name
when a reminder device/service is configured for that person.
The number of people displayed is freely configurable
(`max_items`), and a visual editor lets you show or hide the
Memories section without writing any YAML.

## Screenshots

Birthdays / Memories card:

<img width="600" alt="Anniversary Celebration card" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/screenshot-1794520615511-6847d851.png" />

Add-a-person form (integration options):

<img width="600" alt="Add a person form" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/screenshot-1794518104949-7f50ec1c.png" />

Choosing the notification times and the devices/services to notify (further down the same form):

<img width="600" alt="Choosing the notification times and services" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/screenshot-1794553602042-1cabbc4d.jpg" />

Notification on the day (persistent in Home Assistant and on mobile):

<img width="600" alt="Anniversary Celebration persistent notification" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/screenshot-1794531746780-bec780a5.png" />

<img width="600" alt="Anniversary Celebration mobile notification" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/screenshot-1794531646890-41025284.png" />

Card editor with live preview (birth dates blurred out in this screenshot):

<img width="600" alt="Card editor with live preview" src="https://raw.githubusercontent.com/cyclope205/anniversary-celebration/main/docs/screenshots/anniversary-card-config-masked.png" />

## Installation (HACS)

1. Open Anniversary Celebration in HACS and install it:
2. [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cyclope205&repository=anniversary-celebration&category=integration)
3. [![Open in Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=cyclope205&repository=anniversary-celebration&category=integration)
4. or search for **Anniversary Celebration** in HACS if the repository is already listed.
5. Restart Home Assistant.
6. Add the integration:
7. [![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=anniversary_celebration)
8. or **Settings → Devices & services → Add integration → Anniversary Celebration**.
9. Configure it to add your first people.

10. The Lovelace card is registered automatically by the integration: no resource to declare by hand.

## Configuration

From the integration's options (**Settings → Devices & services →
Anniversary Celebration → Configure**), a menu lets you add, edit,
or remove a person. Each person has:

| Field | Required | Description |
|---|---|---|
| First name | Yes | First name shown on the card and in notifications |
| Last name | No | Last name, optional |
| Date of birth | Yes | Used to calculate age and the countdown |
| Status | Yes | Alive or Deceased — changes the notification message |
| Notification times | No | Up to two times on the day (default 09:00). Duplicate times are rejected/deduplicated. |
| Devices/services to notify | No | One or more `notify.*` services; if left empty, only the Home Assistant persistent notification is created |
| Death date | No | Only useful if status is Deceased. Triggers a separate yearly reminder from the birthday one. Must be after the date of birth |
| Speakers / TTS engine / announcement time | No | Spoken announcement configuration (see below) |
| "Announce..." checkboxes | No | Three independent checkboxes (birthday, in memory, death anniversary), all off by default |

A separate menu in the integration's options, **Default notification
targets**, lets you choose `notify.*` services that automatically receive
every notification, on top of the ones configured on each person.

### Spoken announcement

Optional feature, independent from the written notifications: for each
person, you can configure one or more `media_player.*` entities and a
text-to-speech engine (`tts.*`), plus a time of its own for the
announcement (different, if needed, from the written notification times).
Three checkboxes, all off by default, choose which events are spoken aloud:
birthday (alive), in memory (deceased), death anniversary. Unlike written
notifications, a missed spoken announcement is never retried the next day —
it would say "today" about a day that has already passed, which would be
wrong.

## Card — configuration

```yaml
type: custom:anniversary-celebration-card
title_alive: "🎂 Birthdays"
title_deceased: "🕯️ Memories"
show_deceased: true
max_items: 0 # 0 or absent = everyone; otherwise any number
```

## Notification reliability

There is no single timer scheduled months in advance (which could be lost on a
Home Assistant restart, even if the birthday is 8 months away).
The integration recalculates each person's state **every minute**.
When the anniversary day and one of the configured times are reached, each
time slot is handled independently. Success is tracked separately for every
`notify.*` service: a failed target is retried without resending to targets
that already succeeded. A Home Assistant persistent notification is also
created, and the delivery state is saved to persistent storage so it survives
Home Assistant restarts. The death-anniversary reminder follows the exact
same guarantees, with its own tracking independent from the birthday one.
The spoken announcement, however, is best-effort: it is never retried the
next day on failure (see the Spoken announcement section above).

## Available languages

The configuration UI (adding/editing/removing a person,
options menus) is translated into 22 of the languages most used by
Home Assistant: French, English, German, Spanish, Italian, Portuguese
(Portugal and Brazil), Dutch, Polish, Russian, Swedish, Norwegian,
Danish, Finnish, Czech, Slovak, Hungarian, Turkish, Greek, Romanian,
Ukrainian, and Catalan. Home Assistant automatically picks the translation
matching the language set in your user profile; if there is no
match, English is used.

*Note: the fields added for the death date, default targets, and spoken
announcement are currently translated only into French and English; the
other 20 languages still show the field's technical name until the
translations are updated.*

## Tests

The repository includes an automated test suite (`tests/`, based on
`pytest`) covering in particular date calculations (days remaining, current
age, age at the next birthday, the day-of and February 29th cases) and
the duplicate/missed-notification prevention logic. Tests run
automatically on every change via GitHub Actions (the "Tests" badge
above).

## Good to know

- The check runs every minute: a notification scheduled for
a given time may fire up to ~59 seconds after it, never
before.
- "Deceased" status does not prevent the notification: only the message
changes ("in memory" instead of "happy birthday").
- Bugs and feature requests are reported via the repository's
**Issues** tab.

## License

MIT — see [LICENSE](https://github.com/cyclope205/anniversary-celebration/blob/main/LICENSE).
