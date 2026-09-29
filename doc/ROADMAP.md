# Roadmap

Each section describes one feature idea. Implementation steps are included when
they are known.

## Scoped API tokens

### Summary

Allow profiles to use scoped Atlassian API tokens, including read-only tokens
for `pull` and `status`. Classic tokens must continue to work. Commands that
need permissions missing from a scoped token should report the required
permission clearly. This changes credential configuration, not the workarea
format.

### Implementation steps

1. Handle HTTP 401 responses with `OAuth` or `Basic` challenges as `APIError`
   instead of an uncaught exception. For an `OAuth` challenge, suggest checking
   whether the token needs a scoped-token profile.
2. Verify the scoped-token gateway against Atlassian documentation and a real
   site. Confirm the cloud ID lookup, v1 and v2 API URLs, attachment downloads,
   pagination and download-link resolution, and the scopes required by each
   command. Record the results in [SPEC.md](SPEC.md).
3. Add an optional `cloud_id` to profiles. Route profiles with a cloud ID
   through the gateway while keeping existing site-URL profiles compatible.
   Update `auth` to configure scoped tokens and `auth --list` to identify
   gateway profiles. Report missing-scope errors with the affected operation.
4. Document scoped-token setup and read-only and full-use scopes in the README
   and [SPEC.md](SPEC.md). Test both token types, gateway URL construction,
   authentication failures, and permission errors.

The feature is complete when all commands work with classic tokens and scoped
tokens carrying the documented scopes, while read-only scoped tokens support
`pull` and `status` and produce clear permission errors for other commands.
