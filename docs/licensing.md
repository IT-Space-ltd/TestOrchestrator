# Licence format and date semantics

## Code
`TO1.<b64url(payload-json)>.<b64url(ed25519 signature)>` — pasted into the
installer, `/licence` activation page, or Admin → Licence.

## Payload (canonical JSON, sorted keys, compact separators)
`version`, `key_id`, `licence_id`, `product` (`TestOrchestrator`),
`customer`, `valid_from`, `valid_until` (ISO-8601 UTC). No installation
binding — licences are portable (owner decision).

## Cryptography
Ed25519 sign/verify. The app holds only the public key
(`release/licence_pubkey.pem`, key_id `prod`); the issuer holds the
private key. Tampered payloads, bad signatures, unknown key_ids,
wrong products, malformed codes, and invalid date ranges are rejected.

## Dates
UTC, internally half-open `[valid_from, valid_until)`. States:
missing / invalid / not-yet-valid / valid / expired. Relies on the
host clock — no tamper-proof expiry is claimed.

## Status is informational
The application licence is NOT an enforcement gate. Install, startup,
login, dispatch, workers, imports, reports, admin routes, and the CLI
all work with a missing/expired/invalid licence. The sole
user-visible effect of a non-valid licence is the exact notice
`This version is not supported` on the login page (login itself is
never blocked). `/licence` and `/licence-activate` remain for status
viewing and recording a code; `scripts/install.py` accepts an
optional `TO_LICENCE_CODE` and warns — never aborts — on a rejected
code. Signature verification and stored-row re-verification are
unchanged; this is separate from KRE licensing, which is untouched.

## Test coverage boundary — production issuer key

Two tests in `tests/test_licence_enforcement.py` are **blocked** under
the current security boundary and must not be reported as passing or
silently removed. Any release exception requires explicit acceptance.

### Blocked tests

- `test_production_key_auto_loaded` — proves that a fresh process,
  with no test-side `register_key`, verifies a `key_id:"prod"`
  signed code against the shipped `release/licence_pubkey.pem`
  (the production key auto-load path). It signs a payload in-test
  with `/tmp/to-license-issuer/private.pem`, which requires the
  production issuer private key.
- `test_payload_fields_signed` — proves that swapping signed payload
  fields (customer/licence_id) inside a valid `prod`-signed code is
  rejected. It reads a production-signed code fixture
  (`/tmp/lic-valid.txt`). Verifying the negative requires a
  genuine prod signature; a test-key code would not exercise the
  `key_id:"prod"` path.

### What test-key coverage proves

The remaining 16 tests in the file run against a test key fixture
(`key_id:"test"`): signature verification, tampered payload, bad
signature, unknown key_id, wrong product, malformed code, date-range
enforcement, forged stored rows, activation rate limiting, and the
informational (non-enforcing) status semantics. The Ed25519 verify
path itself is fully exercised.

### What remains unverified

- That `release/licence_pubkey.pem` is auto-loaded by a fresh
  process as the `prod` verification key (registration wiring, not
  cryptography).
- Rejection of field-tampered payloads specifically under the
  `prod` key_id.

### Future fixture option

A checked-in **production-signed sample licence code** (an artifact
generated once by the issuer — never the private key itself) would
let both tests run without any signing capability at test time:
auto-load verified by parsing the fixture, tamper rejection by
mutating it. This changes no production trust behavior; it only
ships a signed artifact, the same class of data as the shipped
public key. `test_production_key_auto_loaded` specifically cannot
be satisfied any other way — generating a fresh prod signature is
its entire point.
