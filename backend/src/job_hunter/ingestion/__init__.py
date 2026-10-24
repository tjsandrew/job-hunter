"""Bounded adapters for public employer job-board APIs and the MyCareersFuture search API.

Only publicly listed postings are read. This package does not crawl
HTML pages, submit applications, or bypass access controls.
"""

__all__ = [
    "DiscoveryConfig",
    "DiscoveryReport",
    "ProviderHTTPError",
    "ProviderRequestError",
    "discover",
    "discover_report",
]


def __getattr__(name: str):
    # Keep `python -m job_hunter.ingestion.discovery` clean from runpy warnings.
    if name in __all__:
        from . import discovery

        return getattr(discovery, name)
    raise AttributeError(name)
