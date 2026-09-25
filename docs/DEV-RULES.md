# Dev Rules — hass-pelican

Numbered so they can be cited in commits, reviews and issues ("violates rule 7").
These are enforced by `scripts/local-gates.sh` and `.github/workflows/ci.yml`
wherever a machine can enforce them; the rest are on us.

Rules are append-only. A rule that turns out to be wrong gets **struck through
with the reason**, not deleted and not renumbered — a citation in an old commit
must keep resolving to the same rule.

---

## Dependencies and surface

**1. Zero runtime dependencies.** `manifest.json` `requirements` stays `[]`. If a
problem seems to need a library, it needs to be solved with what Home Assistant
core already ships (`aiohttp`, `voluptuous`, stdlib). Dev-only tooling in
`requirements-dev.txt` is exempt.

**2. Never edit vendored or third-party code.** Not to silence a linter, not to
fix a bug. If a gate can only be satisfied by editing code we don't own, the
gate is wrong and gets scoped — see rule 18.

**3. The polled attribute list is a closed contract.** Every name in
`api.THERMOSTAT_ATTRIBUTES` must have at least one consumer elsewhere in the
package, and every attribute an entity reads must appear in the list. Both directions are checked by
`scripts/check-consistency.py`. This exists because the keypad switch shipped
reading an attribute that was never polled.

**4. One API request per poll cycle.** All thermostats at a site come back in a
single `api.cgi` call. No per-entity fetching, no extra round trip in a property
getter. Adding thermostats must never add API traffic.

**5. All writes go through `PelicanCoordinator.async_apply`.** Entities never
call `PelicanApi.async_set_thermostat` directly. The coordinator owns optimistic
state and the follow-up refresh; bypassing it produces UI that lies for 60
seconds.

## Correctness

**6. Entities are keyed by `serialNo`, never by `name`.** Thermostat names are
editable in Site Manager and get changed by customers. A unique_id is
`{serial}` for the climate entity and `{serial}_{key}` for everything else.

**7. A unique_id is permanent.** Never reuse, repurpose, or reformat one. Changing
a unique_id orphans the user's entity, its history, and every automation
referencing it.

**8. Don't create entities for capabilities the hardware lacks.** Verified on
TS200 hardware: `co2Level` comes back `""` without the sensor, and `humidity`
comes back `0` on units without one -- even alongside identical models that
report 45-48. Gate creation on `exists_fn`, and read a zero humidity as "no
sensor," rather than shipping an entity that reports a permanent blank or zero.

**9. Every API failure reaching a service handler surfaces as
`HomeAssistantError`.** A swallowed exception makes a failed setpoint look like a
successful one.

**10. No blocking I/O in the event loop.** All HTTP goes through the shared
`async_get_clientsession(hass)`. No `requests`, no `time.sleep`, no file reads in
a property — including `ZoneInfo(...)`, which reads the tz database off disk and
must go through `dt_util.async_get_time_zone`.

## Logging

**25. Every API failure mode has its own exception class and its own message.**
Auth, connection, timeout, HTTP status, unparseable response and site refusal
are six different problems with six different fixes. A single generic error
class means the log says "request failed" and the user has nothing to act on.
Every one is logged before it becomes a reauth prompt, an `UpdateFailed`, or a
`HomeAssistantError`.

**26. Repeated identical failures throttle; recovery is logged.** Polling runs
on a timer, so an unreachable gateway would otherwise write the same ERROR
1,440 times a day. First occurrence ERROR, identical repeat DEBUG, a *different*
failure ERROR again, recovery INFO. That is `ErrorLog`; use it for anything on a
timer. User-initiated writes are not throttled — they are rare and every one
matters.

**27. A degraded feature never takes down a working one.** Anything optional --
a second coordinator, an auxiliary endpoint -- stays out of config entry setup, so a failure there leaves its own entities
unknown and climate control untouched. Ask of any new coordinator: if this fails
forever, what stops working? The answer must be "only itself."

**28.** ~~**Times from the site are wall-clock times at the site.** A Pelican set
time of "Monday 07:00" means 07:00 where the building is. Resolve it against the
zone from the `Site` object, then store and compare in UTC.~~

*Struck 2026-09-24: the only consumer was next-change prediction, and that was
deleted when the live site proved schedule contents are unreadable over the
API. The principle still stands for any future code that interprets site-local
times.*

**29. A selector the site cannot parse means EVERY thermostat.** Verified on a
live site: `selection=2S3-MNXA` (a bare serial, which Pelican does not accept)
on a `set` returned `success: 1` with "Updated 7 thermostats." There is no
error, nothing looks wrong, and a whole building changes. Writes select by
`nodeName`, and `PelicanCoordinator.selector_for` refuses a blank, duplicate or
punctuation-bearing selector before anything reaches the wire. Never relax those
guards, and never build a selector from free text a customer can edit.

**30. An attribute the site does not recognize returns `""` with `success: 1`.**
`thisIsNotAnAttribute` comes back empty and successful, so a typo in
`THERMOSTAT_ATTRIBUTES` yields `None` forever with no error anywhere and the
consistency gate cannot see it -- it checks that what we read is what we poll,
not that the site knows the name. Only add an attribute after confirming it
returns non-empty against a live site. The same behavior is a useful probe: a
non-empty value proves an attribute is real.

**31. `success: 1` on a write means accepted, not delivered.** Verified on a
live site: a physically unplugged thermostat reports `statusDisplay:
Unreachable`, keeps serving its last-known values, and a write to it returns
"Updated 1 thermostats." `selector_for` refuses writes to an unreachable
thermostat for that reason. Entity unavailability also blocks them, but that is
incidental; the coordinator must not depend on it.

**32. The integration connects Home Assistant to the Pelican API. Nothing more.**
Scheduling, occupancy logic and setpoint policy live in Home Assistant
automations, never in this package. The one opinion it holds is that a Pelican
cloud schedule running underneath those automations is a misconfiguration, which
it reports as a fixable Repairs issue. Before adding anything, ask whether it
exposes API state or control, or whether it is logic an automation should own.
The second kind does not go here. This rule exists because a web-UI schedule
reader, a next-change predictor and a schedule-name memory were each built and
then removed for crossing it.

## Secrets and logging

**11. Credentials never reach the log.** Debug logging may name serials, attributes
and values. It must never log the username, the password, or a full request URL —
Pelican puts credentials in the query string, so the URL *is* a credential.

**12. Never reproduce a secret-shaped line in order to explain it.** Not in a
comment, not in a changelog, not in a scanner ignore file. Describe the offending
construct in prose and cite the file and symbol. A scanner has no idea it is
reading an explanation of itself, and a commit meant to take findings from one to
zero will take them from one to three.

**13. A `.gitleaksignore` entry requires a written reason and a reviewer.** It is a
last resort for a confirmed false positive, never a way to unblock a push.

## Strings and UI

**14. No hardcoded user-visible strings.** Entity names, error text and flow copy
live in `strings.json` and reach the user through `translation_key`.

**15. `strings.json` and `translations/en.json` are byte-identical.** English is
maintained in `strings.json`; `en.json` is a copy. The consistency gate enforces
this, because they drift silently otherwise and the drift only shows in the UI.

## Versioning and release

**16. `manifest.json` `version` is the single source of truth, and is never
hand-edited for a build.** A tagged release must match its tag exactly
(`v0.3.1` → `0.3.1`). Dev builds derive their version from `github.run_number`
and stamp it in the workflow workspace only — no commit ever lands carrying a
dev version number.

**17. A behavior change adds a `CHANGELOG.md` entry under `## [Unreleased]` in
the same commit.** Not the commit after. The version in `manifest.json` moves
**once, at release**, when `[Unreleased]` becomes `[X.Y.Z]`.

Amended 2026-09-11: this rule originally said a behavior change bumps the
version too. Followed literally on unreleased work it walked a
never-published integration to 0.3.0 in an afternoon, inventing two releases
nobody ever saw. Version numbers describe what shipped, not how much changed.

**18. `main` only advances by release merge.** Work lands on `dev`. Every push to
`dev` cuts a numbered prerelease, so `dev` is always installable and always
traceable to a commit.

## Gates

**19. Pinned tool versions live in `.github/workflows/ci.yml` and nowhere else.**
`scripts/local-gates.sh` parses the pins out of that file at runtime. A second
hardcoded copy of a version is how local and CI silently diverge.

**20. Every gate must be reproducible locally.** If a check exists only inside a
GitHub Action, it is not a gate we can act on — it is a surprise. `local-gates.sh`
runs the same checks in the same order as `ci.yml`, and documents at the top
exactly which CI jobs it does *not* cover and why.

**21. Never infer CI health from the release list.** A missing prerelease can mean
a broken gate, or it can mean a workflow bug — on the Nimbus repos a
`target_commitish` default silently sorted 77 real prereleases out of view and
cost three sessions to a conclusion that was simply false. Read the workflow run,
or ask for the job output. The release list is not a proxy.

**22. Tests must fail when sabotaged.** Before trusting a new test, break the code
it covers and confirm it goes red. An assertion that passes against broken code
is worse than no test, because it is counted as coverage.

**23. Refactors leave no abandoned artifacts.** No dead constants, no unreferenced
helpers, no wiring left dangling from an earlier design. If it no longer has a
consumer, it leaves in the same commit that removed its last caller.

**24. Read the docs and the existing code before writing.** Both the Pelican
OpenAPI reference and this package. Most of what looks like it needs building
already exists in `entity.py` or `coordinator.py`.
