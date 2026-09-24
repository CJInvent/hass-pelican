# Pelican Wireless for Home Assistant

[![CI](https://github.com/CJInvent/hass-pelican/actions/workflows/ci.yml/badge.svg)](https://github.com/CJInvent/hass-pelican/actions/workflows/ci.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/)

A Home Assistant custom integration for [Pelican Wireless](https://www.pelicanwireless.com/)
commercial thermostats (TC and TS series), talking directly to the Pelican OpenAPI
on your own Site Manager instance (`https://<yoursite>.officeclimatecontrol.net/api.cgi`).

No cloud middleman, no paid API tier — the OpenAPI is included with the standard
Pelican Site Manager subscription and has no documented rate limit.

## What you get

Every thermostat at the site becomes a Home Assistant device with:

| Entity | Type | Notes |
| --- | --- | --- |
| Thermostat | `climate` | Current temperature and humidity, Off/Heat/Cool/Auto, heat and cool setpoints, Auto/On fan, live heating/cooling/fan action |
| Status | `sensor` | The site's `statusDisplay` text, including `Unreachable` |
| Run status | `sensor` | Raw `runStatus` (`Cool-Stage1`, `Heat-Stage2`, …) |
| Set by | `sensor` | Whether the current settings came from the Station, Remote, or Schedule |
| CO2 | `sensor` | Only created on thermostats that actually report CO2 |
| Schedule | `switch` | Turn the thermostat's schedule off so manual setpoints hold |
| Keypad unlocked | `switch` | Lock or unlock the physical keypad |
| Cloud schedule | `binary_sensor` | On while a Pelican-side schedule can override Home Assistant |

All thermostats at the site are read in a **single** API request per poll cycle,
so adding thermostats does not add API traffic.

## Before you install

Create a dedicated API user in Pelican Site Manager rather than reusing your own
login — Pelican recommends this, and it keeps the integration visible in the audit
trail as its own account.

1. Log in to `https://<yoursite>.officeclimatecontrol.net/`.
2. Go to **Admin → User Management**.
3. Add a user (for example `homeassistant@yourdomain.com`) with permission to view
   and change thermostats.
4. Note the email address and password — that's what you'll enter in Home Assistant.

## Installation

### Option A — HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Click the three-dot menu (top right) → **Custom repositories**.
3. Paste `https://github.com/CJInvent/hass-pelican` into the repository field,
   choose **Integration** as the type, and click **Add**.
4. Find **Pelican Wireless** in the HACS list, open it, and click
   **Download**.
5. Restart Home Assistant.

### Option B — no HACS, straight from GitHub

From a shell on the Home Assistant host (or the Terminal add-on), in your
config directory:

```bash
mkdir -p custom_components
cd custom_components
curl -L https://github.com/CJInvent/hass-pelican/archive/refs/heads/main.tar.gz \
  | tar -xz --strip-components=2 hass-pelican-main/custom_components/pelican
```

Then restart Home Assistant. To update later, re-run the same command.

## Configuration

1. **Settings → Devices & Services → Add Integration**.
2. Search for **Pelican Wireless**.
3. Enter:
   - **Site hostname** — e.g. `yoursite.officeclimatecontrol.net`
     (a full `https://…` URL is accepted too)
   - **Username** — the API user's email address
   - **Password**

The integration verifies the credentials and discovers every thermostat before it
finishes setup. The poll interval defaults to 60 seconds and can be changed later
under the integration's **Configure** button (15–900 seconds).

## Notes on behavior

<a id="schedules"></a>
### Schedules

This is the one thing worth reading before you write an automation.

If a thermostat is running a schedule configured in Pelican Site Manager, a
setpoint you push from Home Assistant holds only until that schedule's next set
time, then reverts. **Nothing errors.** The API call succeeds, the entity updates,
and hours later the temperature quietly goes back — exactly as it would if
someone pressed the buttons on the wall.

The integration says so two ways:

- **Settings → Repairs** shows a warning naming every thermostat with a
  schedule running. It clears itself when none are left.
- **`binary_sensor.<name>_cloud_schedule`** is on while a schedule can override
  you. Gate automations on it, or alert on it.

What it **can't** tell you is *when* the schedule will act or *what* it will
change things to. Pelican's API refuses to serve schedule contents — both
`ThermostatSchedule` and `SharedSchedule` answer "currently unsupported" — so
Home Assistant only knows that a schedule is assigned. The climate entity's
`set_by` attribute reads `Schedule` once one has taken over, which is the
closest after-the-fact evidence available.

Two ways to resolve it, depending on which side should win:

```yaml
# Option A — Home Assistant owns the setpoints. Turn the site schedule off.
- action: switch.turn_off
  target:
    entity_id: switch.shop_schedule

# Option B — the Pelican schedule stays authoritative. Don't fight it.
- if:
    - condition: state
      entity_id: binary_sensor.shop_cloud_schedule
      state: "off"
  then:
    - action: climate.set_temperature
      target:
        entity_id: climate.shop
      data:
        temperature: 68
```

#### Turning a schedule back on

Pelican's `schedule` attribute holds either `On` (the thermostat's own schedule)
or the **name** of a shared schedule. Once it is set to `Off`, that name is gone
from the API entirely.

So the Schedule switch remembers the name and persists it across Home Assistant
restarts. Turning the switch back on reattaches the same shared schedule rather
than sending a bare `On`, which would silently move the thermostat onto its own
local schedule and off the shared one everyone else at the site is using. The
remembered value is visible as the switch's `schedule_name` attribute.

This integration never edits schedule contents. Do that in Site Manager, where
everyone else who shares the site can see the change.

**Auto mode uses a setpoint range.** In `Auto` (`heat_cool`), Home Assistant shows
the heat and cool setpoints as a low/high pair. Calling `climate.set_temperature`
with a single `temperature` value while in Auto raises an error — use
`target_temp_low` and `target_temp_high` instead.

**Unreachable thermostats.** When the site reports `statusDisplay: Unreachable`,
that thermostat's entities go unavailable rather than reporting stale values.

## Example automation

```yaml
automation:
  - alias: "Set back the shop overnight"
    triggers:
      - trigger: time
        at: "19:00:00"
    actions:
      - action: switch.turn_off
        target:
          entity_id: switch.shop_schedule
      - action: climate.set_temperature
        target:
          entity_id: climate.shop
        data:
          hvac_mode: heat_cool
          target_temp_low: 60
          target_temp_high: 85
```

## Development

Conventions are numbered and citable in [`docs/DEV-RULES.md`](docs/DEV-RULES.md).
Read it before the first change — several rules exist because something already
broke once.

### Running the gates locally

```bash
./scripts/local-gates.sh
```

Runs lint, the consistency gate, typecheck, tests and a full-history gitleaks
scan, in the same order as CI, at the versions pinned in
`.github/workflows/ci.yml`. First run builds `.venv-gates/` and takes a few
minutes; after that it's fast. It does **not** cover `hassfest` or the HACS
validator — both are container actions with no standalone invocation — so read
those two jobs after pushing if you touched `manifest.json`, `hacs.json`, or
moved files.

Requires Python 3.14, which is what Home Assistant 2026.9 needs.

### The gate set

| Job | What it protects |
| --- | --- |
| `lint` | ruff check and format, including async-safety rules |
| `consistency` | Dev rules 3, 14, 15, 16 — polled attributes match their consumers, translations stay in sync, manifest stays valid |
| `typecheck` | mypy against the real Home Assistant package |
| `tests` | pytest with `pytest-homeassistant-custom-component` |
| `hassfest` | Home Assistant's own manifest validator |
| `hacs` | HACS repository structure validation |
| `gitleaks` | Full-history secret scan |

### Branches and releases

`dev` is the integration branch; `main` only advances by release merge.

- Every push to `dev` runs the gate set and, if it's green, publishes a
  prerelease `v<base>-dev.<run_number>` pinned to that exact commit. `dev` is
  therefore always installable and always traceable.
- A `vX.Y.Z` tag runs the same gates, asserts the tag matches
  `manifest.json` and that `CHANGELOG.md` has a matching section, then
  publishes a stable release with a `pelican.zip` asset for manual or
  air-gapped installs.

Version numbers are never hand-edited for a build. Dev builds derive theirs from
the run number and stamp it in the workflow workspace only, so no commit ever
carries a dev version.

One thing worth internalizing from prior repos: **do not read the release list
as a proxy for CI health.** Read the workflow run. See dev rule 21 for what that
mistake cost.

## Troubleshooting

Turn on debug logging to see every request the integration makes:

```yaml
logger:
  default: warning
  logs:
    custom_components.pelican: debug
```

- **"The site rejected those credentials"** — confirm the user exists under
  Admin → User Management and that you can log into the web app with it.
- **"Could not reach the site"** — check the hostname. It is the same host you use
  in a browser, without `https://` and without a trailing path.
- **"Connected, but the site reported no thermostats"** — the credentials are valid
  but that user has no thermostats assigned to it in Site Manager.
- **Something failed and you want the detail** — every API failure mode logs its
  own message naming the site and the actual cause. Repeated identical failures
  drop to DEBUG so an offline gateway doesn't flood the log, and recovery logs at
  INFO. Credentials are never logged: Pelican puts them in the query string, so
  the request URL is itself a secret and is deliberately absent.
- **Filing a bug** — use **Download diagnostics** on the integration page. It
  includes coordinator health, the last exception from the poll, and the raw
  thermostat payloads, with credentials redacted.

## How the API actually behaves

Pelican's published documentation differs from the live API in ways that matter.
Every item here was verified against a real site; the code depends on each one.

- **Responses are nested under `result`**, and `success` is the integer `1`. The
  docs show both flattened and stringly-typed.
- **`serialNo:` selection is rejected.** Writes select by `nodeName`
  (e.g. `thrm2A38`), a stable device identifier. Names work as selectors too,
  but they carry significant trailing spaces (`"Sales "` is not `"Sales"`) and
  aren't unique.
- **A selector the site can't parse matches every thermostat.** A malformed
  selection on a write returned `success: 1` with "Updated 7 thermostats." The
  integration refuses to send a blank, duplicate, or punctuation-bearing
  selector for exactly this reason.
- **Unknown attributes return `""` with `success: 1`**, so a misspelled
  attribute fails silently rather than with an error.
- **Schedule contents are not readable** over this API.

## References

- [Pelican OpenAPI — Getting Started](https://www.pelicanwireless.com/help-center/gettings-started2/)
- [Pelican OpenAPI — Requests & Responses](https://www.pelicanwireless.com/help-center/request-responses/)
- [Pelican OpenAPI — Thermostat Attributes](https://www.pelicanwireless.com/help-center/thermostat-attributes/)

## Disclaimer

Not affiliated with or endorsed by Pelican Wireless Systems. Uses the documented
public OpenAPI. Provided as-is under the MIT license.
