"""Thin AWS Lambda entry points: parse event, call an application service, format
response. No business logic belongs in this package (CONTRIBUTING.md).

`api_handler.py` (Phase 5) is the single Lambda entry point for all six REST API
routes (ADR-016) — dispatch, request/response mapping, and error mapping live here.
"""
