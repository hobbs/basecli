"""Compatibility shim.

All project metadata lives in ``pyproject.toml``. This file exists only so that
``pip install -e .`` works on older pip/setuptools (pre-PEP-660) that require a
setuptools entry point for editable installs.
"""

from setuptools import setup

setup()
