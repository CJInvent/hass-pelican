# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dev rule 17: a behavior change lands under `## [Unreleased]`; the version in
`manifest.json` moves once, at release. `release.yml` refuses to publish a tag
with no matching section.

## [Unreleased]

## [0.1.0] - 2026-09-24

First release.

### Added
- **Climate entity per thermostat.** Current temperature and humidity,
  Off/Heat/Cool/Auto, a single setpoint or a heat/cool range depending on mode,
  Auto/On fan, and live heating/cooling/fan action derived from `runStatus`.
  Temperatures keep the tenth of a degree Pelican reports rather than being
  rounded to whole degrees; setpoints are whole-degree, because the API only
  accepts integers there.
- **Pelican cloud schedules are reported as a fixable Repairs issue.**
  Schedules belong in Home Assistant automations; a Pelican schedule running
  underneath them silently overwrites their setpoints at every set time. The
  issue names every affected thermostat, and its fix turns their schedules off
  in one step. An offline thermostat is skipped and named rather than aborting
  the rest. Turning a schedule off keeps current setpoints and pauses rather
  than deletes it, verified against a live site.
- **Writes select by `nodeName`.** The site rejects `serialNo:` selection, and
  selecting by `name:` would mean putting customer-editable free text into a
  selector -- names carry significant trailing spaces and are not unique. The
  coordinator refuses to write when a node name is missing, duplicated, or
  contains selector punctuation, because a selector the site cannot parse is
  not an error there: it matches every thermostat and reports success.
- **Offline thermostats are unavailable and refuse writes.** An unplugged unit
  reports `Unreachable` with frozen last-known values, and the site still
  accepts writes to it with a success response. Showing those values as live, or
  reporting a change as made, would both be false.
- **Schedule and keypad switches.** The schedule switch is the per-thermostat
  equivalent of the Repairs fix.
- **Diagnostic sensors** for site status, run status and who last changed the
  settings (`Station`, `Schedule` or `Remote`), plus a CO2 sensor created only
  on thermostats that report one.
- **A distinct exception and log message per API failure mode**: authentication,
  connection, timeout, HTTP status, unparseable response, and site refusal.
  Repeated identical failures throttle to DEBUG so an offline gateway cannot
  flood the log; recovery logs at INFO. Credentials never reach the log, since
  Pelican puts them in the query string.
- **UI config flow** with credential validation, duplicate-site detection and
  reauthentication. Poll interval configurable from 15 to 900 seconds.
- **Single-request polling.** Every thermostat at a site is read in one
  `api.cgi` call regardless of count.
- **Config entry diagnostics** with credentials redacted.
- Dev rules, the CI gate set, local gate reproduction, and the dev/release
  pipelines.

[Unreleased]: https://github.com/CJInvent/hass-pelican/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.1.0
