"""Error types and the throttled failure logger.

Every failure mode of the Pelican API gets its own exception class and its own
human-readable message, so the Home Assistant log says what actually went wrong
and what to do about it (dev rule 25).

Polling runs on a 60 second timer. Logging every failure at ERROR would fill the
log with 1,440 identical lines a day for one unplugged gateway, so repeats are
throttled: the first occurrence of a given failure logs at ERROR, identical
repeats drop to DEBUG, a *different* failure logs at ERROR again, and recovery
logs at INFO so the log shows when it came back (dev rule 26).
"""

from __future__ import annotations

import logging


class PelicanError(Exception):
    """Base class for every Pelican failure.

    `message` is what the user sees in the log and in the UI; it must be
    actionable and must never contain credentials (rule 11).
    """


class PelicanAuthError(PelicanError):
    """Credentials were rejected, or the account lacks access.

    Raised on an explicit authentication message from the site and on HTTP 401
    or 403. Triggers Home Assistant's reauth flow rather than a retry, because
    retrying with the same rejected credentials cannot succeed.
    """


class PelicanConnectionError(PelicanError):
    """The site could not be reached at all.

    DNS failure, refused connection, TLS failure, or no route. Distinct from an
    API error because nothing was ever parsed.
    """


class PelicanTimeoutError(PelicanConnectionError):
    """The site accepted the connection but did not answer in time."""


class PelicanResponseError(PelicanError):
    """The site answered, but not with something we could use.

    An HTTP error status, a login page instead of JSON, or a payload whose shape
    does not match the documented API.
    """


class PelicanApiError(PelicanError):
    """The API understood the request and refused it.

    `success` was not 1. The site's own message is carried through verbatim,
    because Pelican's refusals ("Setting out of range", "No thermostats found
    matching selection criteria") are more specific than anything we could
    invent.
    """


class ErrorLog:
    """Throttles repeated identical failures down to DEBUG.

    One instance per logical activity (thermostat poll, schedule poll). Not
    shared, because a stuck schedule poll must not mask a new thermostat poll
    failure.
    """

    def __init__(self, logger: logging.Logger, activity: str) -> None:
        """Initialize with the logger and a short description of the activity."""
        self._logger = logger
        self._activity = activity
        self._last_signature: str | None = None

    def failure(self, err: Exception) -> None:
        """Log a failure, at ERROR when it is new and DEBUG when it repeats."""
        signature = f"{type(err).__name__}:{err}"
        if signature == self._last_signature:
            self._logger.debug("%s still failing: %s", self._activity, err)
            return
        self._last_signature = signature
        self._logger.error(
            "%s failed: %s",
            self._activity,
            err,
            # The traceback matters for the unexpected classes; for the modeled
            # ones the message is the whole story.
            exc_info=not isinstance(err, PelicanError),
        )

    def success(self) -> None:
        """Note a success, logging recovery at INFO if we were previously failing."""
        if self._last_signature is not None:
            self._logger.info("%s recovered", self._activity)
            self._last_signature = None
