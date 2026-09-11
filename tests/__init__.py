"""Tests for the Pelican Wireless integration.

This file exists so `tests` is a real package. Without it pytest imports each
test module as a top-level module with no parent, and `from .conftest import ...`
fails with "attempted relative import with no known parent package". Home
Assistant core ships the same file for the same reason.
"""
