-- migrations/0003_vault.sql (unit U3)
--
-- Vault persistence: wrapped keyrings, encrypted credentials, and agent
-- access grants. Verbatim from docs/architecture/database-design.md
-- Section 8 -- this is pure ciphertext-in/ciphertext-out storage; nothing
-- here ever holds a KEK, a plaintext DEK, or plaintext credential data (R4,
-- zero-knowledge). Depends on migrations/0001_identity.sql for
-- identity.principals (the user_principal_id / agent_principal_id /
-- granted_by foreign keys below).
--
-- Principal-FK note (see vault/repository.py's module docstring for the
-- full rationale): vault/app.py has never required a caller to register a
-- principal before storing a keyring/credential/grant against its
-- principal_id -- it just accepts whatever string shows up in the request
-- body, and tests/vault/* exercises exactly that. Rather than weakening
-- these foreign keys (which would let a typo'd principal_id silently rot
-- into vault tables forever), vault/repository.py ensures a minimal
-- identity.principals row exists for a new principal_id the first time the
-- vault sees it, via libs.identity_repository.IdentityRepository. The FK
-- stays a real constraint; no existing caller has to change.
--
-- No organization_id / RLS on these tables yet -- the design doc leaves
-- multi-tenancy on vault tables as an open question (see this unit's report
-- for U9 to pick up: a credential's tenant is really its owning principal's
-- home_organization_id, one join away in identity.principals, so RLS here
-- would need a subquery-based policy rather than the direct
-- organization_id = current_setting(...) pattern identity.organization_members
-- uses).

create schema vault;

create table vault.keyrings (
    user_principal_id       text primary key references identity.principals(principal_id),
    encrypted_dek            text not null,
    salt                      text not null,
    nonce                     text not null,
    kdf                       text not null default 'pbkdf2-sha256',
    kdf_params                jsonb not null default '{"iterations": 600000}',
    encrypted_private_key     text not null,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

create table vault.credentials (
    credential_id       text primary key,
    user_principal_id   text not null references identity.principals(principal_id),
    name                text not null,
    credential_type     text not null,
    encrypted_data      text not null,
    nonce               text not null,
    created_at            timestamptz not null default now()
);
create index credentials_owner_idx on vault.credentials(user_principal_id);

create table vault.credential_grants (
    grant_id             text primary key,
    credential_id        text not null references vault.credentials(credential_id) on delete cascade,
    agent_principal_id    text not null references identity.principals(principal_id),
    scope                 text not null,
    granted_by             text not null references identity.principals(principal_id),
    granted_at              timestamptz not null default now(),
    revoked_at              timestamptz
);
create index credential_grants_credential_idx on vault.credential_grants(credential_id) where revoked_at is null;
create index credential_grants_agent_idx on vault.credential_grants(agent_principal_id) where revoked_at is null;
