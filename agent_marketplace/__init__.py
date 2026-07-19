"""AgentTrust Agent Marketplace (Phase B, unit U8).

A standalone service where agents advertise capabilities/pricing, users
search by capability/reputation, hire agents via scoped grants, rate them,
and revoke hires. Agent listings and reputation are PULLED live from the
Registry (the source of truth); this service owns hiring grants, ratings,
and orchestration of Vault credential grants.
"""
