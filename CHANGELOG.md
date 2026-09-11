# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dev rule 17: a behavior change lands under `## [Unreleased]`; the version in
`manifest.json` moves once, at release. `release.yml` refuses to publish a tag
with no matching section.

## [Unreleased]

## [0.1.0] - 2026-09-11

First release.

### Added
- **Climate entity per thermostat.** Current temperature and humidity,
  Off/Heat/Cool/Auto, a single setpoint or a heat/cool range depending on mode,
  Auto/On fan, and live heating/cooling/fan action derived from `runStatus`.
  Temperatures keep the tenth of a degree Pelican reports rather than being
  rounded to whole degrees; setpoints are whole-degree, because the API only
  accepts integers there.
- **Cloud schedule visibility**, because a Pelican schedule silently reverting a
  setpoint an automation just wrote is the most confusing thing this integration
  can do, and nothing errors when it happens. Surfaced three ways: a Repairs
  warning naming the affected thermostats, a `Cloud schedule` binary sensor to
  gate automations on, and a `Next schedule change` timestamp with the settings
  it will apply. The full weekly schedule is published as an attribute.
- **Site-local schedule times.** Set times are wall-clock at the building, so
  they are resolved against the site's own time zone from the Pelican `Site`
  object and published in UTC. DST is handled: a 07:00 set time stays 07:00
  local across the transition. A site reporting an unresolvable zone, or none,
  falls back to Home Assistant's zone and says so at WARNING.
- **Schedule and keypad switches.** Turning the schedule off is what makes a
  manual setpoint hold. Turning it back on restores the *same* shared schedule
  by name, persisted across restarts, rather than sending a bare `On` and
  detaching the thermostat onto its own schedule.
- **Diagnostic sensors** for site status, run status and who set the current
  settings, plus a CO2 sensor created only on thermostats that report one.
- **A distinct exception and log message per API failure mode**: authentication,
  connection, timeout, HTTP status, unparseable response, and site refusal.
  Repeated identical failures throttle to DEBUG so an offline gateway cannot
  flood the log; recovery logs at INFO. Credentials never reach the log, since
  Pelican puts them in the query string.
- **UI config flow** with credential validation, duplicate-site detection and
  reauthentication. Poll interval configurable from 15 to 900 seconds.
- **Single-request polling.** Every thermostat at a site is read in one
  `api.cgi` call regardless of count; schedules poll separately every 30
  minutes.
- **Config entry diagnostics** with credentials redacted.
- Dev rules, the CI gate set, local gate reproduction, and the dev/release
  pipelines.

[Unreleased]: https://github.com/CJInvent/hass-pelican/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.1.0
