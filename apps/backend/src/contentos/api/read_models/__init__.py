"""Read-only API projections over ContentOS-owned durable state.

Modules here own bounded list/detail queries and their immutable response
DTOs. They never write, never commit, and never return ORM entities.
"""
