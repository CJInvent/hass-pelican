# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dev rule 17: a behavior change bumps `manifest.json` and adds an entry here in
the same commit. `release.yml` refuses to publish a tag with no matching
section.

## [Unreleased]

## [0.2.0] - 2026-09-10

### Added
- Cloud schedule visibility. The site's recurring `ThermostatSchedule` entries
  are read on a slow poll and surfaced three ways: a **Cloud schedule** binary
  sensor per thermostat to gate automations on, a **Next schedule change**
  timestamp sensor, and the full weekly schedule as an entity attribute.
- A Repairs warning naming the thermostats whose Pelican schedule will override
  Home Assistant, since that is the failure mode where nothing errors and the
  setpoint quietly reverts hours later. Self-clearing.
- A distinct exception class and log message per API failure mode:
  authentication, connection, timeout, HTTP status, unparseable response, and
  site refusal. Repeats throttle to DEBUG and recovery logs at INFO.
- Config entry diagnostics with credentials redacted.
- Translated exception messages, so service errors read properly in the UI.
- The consistency gate now covers the schedule attribute contract and
  distinguishes entity, exception and issue translation keys.

### Changed
- Runtime data is now a `PelicanData` object holding both coordinators.
- A single setpoint requested while in Auto now raises `ServiceValidationError`
  rather than a generic error, so it is reported as bad input rather than a
  failure.
- Thermostat records with no serial number are counted and logged instead of
  silently dropped.

### Removed
- `setTime` is no longer polled. It was requested and never read — caught by the
  consistency gate on its first run against the schedule contract.

## [0.1.0] - 2026-09-10

### Added
- Climate entity per Pelican thermostat: current temperature and humidity,
  Off/Heat/Cool/Auto, single setpoint or heat/cool range, Auto/On fan, and live
  heating/cooling/fan action derived from `runStatus`.
- Diagnostic sensors for site status, run status and who set the current
  settings, plus a CO2 sensor created only on thermostats that report one.
- Schedule switch, so a setpoint pushed from Home Assistant can be made to hold
  instead of being overwritten at the next scheduled period.
- Keypad lock switch.
- UI config flow with credential validation, duplicate-site detection and
  reauthentication; poll interval configurable from 15 to 900 seconds.
- Single-request polling: every thermostat at a site is read in one `api.cgi`
  call regardless of count.
- Dev rules, the CI gate set, local gate reproduction and the dev/release
  pipelines.

[Unreleased]: https://github.com/CJInvent/hass-pelican/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.2.0
[0.1.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.1.0
