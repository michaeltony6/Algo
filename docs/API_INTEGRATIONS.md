# API Integrations

This project has connector scaffolding for official partner APIs and a normalization layer that converts approved data into `Offer` objects for the optimizer.

## Compliance Boundary

The major delivery APIs do not provide a general-purpose public feed of courier app offers. The connector methods named `fetch_available_offers()` therefore raise a clear `ApiIntegrationError` unless a platform-approved source is available. Use these inputs instead:

- Official merchant/logistics/order APIs where your account is approved.
- Platform webhooks or exports where allowed by the platform agreement.
- User-entered offers.
- Internal/simulated payloads for testing.

## Uber Eats

File: `src/delivery_optimizer/integrations/uber.py`

What is implemented:

- OAuth 2.0 client credentials token request.
- Authenticated order detail request builder.
- `order_to_offer()` normalizer for approved order-like payloads.

Useful credential fields:

- `client_id`
- `client_secret`
- `scope`, for example `eats.order` when approved.

Official reference: https://developer.uber.com/docs/eats/guides/authentication

## DoorDash

File: `src/delivery_optimizer/integrations/doordash.py`

What is implemented:

- HS256 JWT generation using `developer_id`, `key_id`, and `signing_secret`.
- Delivery quote request builder for approved Drive integrations.
- `quote_to_offer()` normalizer for approved quote-like payloads.

Useful credential fields:

- `developer_id`
- `key_id`
- `signing_secret`

Official references:

- https://developer.doordash.com/docs/drive/tutorials/get_started/
- https://developer.doordash.com/docs/drive/how_to/JWTs/

## Grubhub

File: `src/delivery_optimizer/integrations/grubhub.py`

What is implemented:

- Partner key header.
- MAC authorization header with nonce, body hash, and HMAC signature.
- `order_to_offer()` normalizer for approved order-like payloads.

Useful credential fields:

- `partner_key`
- `client_id`
- `signing_secret`

Official reference: https://grubhub-developers.zendesk.com/hc/en-us/articles/360000061003-Authentication

## Manual And Webhook Ingestion

File: `src/delivery_optimizer/integrations/manual.py`

Use `offers_from_json(path)` or `offer_from_mapping(payload)` to convert JSON into the shared `Offer` model. This is the recommended path for early product development because it lets the optimizer mature before any live platform approval is granted.
