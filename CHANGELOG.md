# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dev rule 17: a behavior change bumps `manifest.json` and adds an entry here in
the same commit. `release.yml` refuses to publish a tag with no matching
section.

## [Unreleased]

## [0.3.0] - 2026-09-11

### Added
- Schedule set times are now resolved against the **site's own time zone**, read
  from the Pelican `Site` object, and published in UTC. Previously they were
  interpreted in Home Assistant's zone, which silently produced wrong
  next-change times whenever Home Assistant and the building disagreed — nothing
  looked broken, the answer was just off by the offset. DST transitions are
  handled: a 07:00 set time stays 07:00 local across the boundary.
- The resolved zone is published as `site_timezone` on the Cloud schedule binary
  sensor and included in diagnostics, so a wrong answer is diagnosable.
- A site that reports an unresolvable zone, or none at all, falls back to Home
  Assistant's zone and says so at WARNING rather than failing the poll.
- The schedule switch now persists the active schedule name across restarts via
  `RestoreEntity`. Once `schedule` is set to Off the shared schedule's name is
  gone from the API, so a restart between turning it off and back on would
  previously have sent a literal `On` and detached the thermostat from a shared
  schedule other people at the site rely on.
- Temperatures keep the tenth of a degree the API reports. Home Assistant
  defaults Fahrenheit climate entities to whole-degree precision, which was
  rounding a reported 72.4 F down to 72; setpoints are still whole-degree,
  because the Pelican API only accepts integers there.
- The consistency gate covers the new `SITE_ATTRIBUTES` contract, and its
  read-but-not-polled check is now grouped by reader — two contracts share the
  `field()` helper, so checking them independently flagged valid Site attributes
  as missing Schedule ones.

### Changed
- The schedule coordinator now returns a `SiteSchedules` object carrying the
  resolved time zone alongside the parsed entries, rather than a bare dict.
- `next_change()` takes the site time zone explicitly and returns UTC.

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

[Unreleased]: https://github.com/CJInvent/hass-pelican/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.3.0
[0.2.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.2.0
[0.1.0]: https://github.com/CJInvent/hass-pelican/releases/tag/v0.1.0
