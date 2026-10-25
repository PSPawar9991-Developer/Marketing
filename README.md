# Prospect Studio

A local client prospecting dashboard for Prasad's website development and SEO services in Australia and the UK. Python 3.12+; no third-party packages or build step.

## Run

```sh
cd /workspace/Marketing
python3 app.py
```

The server binds only to loopback on port 8000 (`PORT` overrides it). Use a local browser or a trusted development port-forwarding tool to interact with it. This is a single-user development application, not an authenticated public deployment. Do not expose it publicly without authentication, TLS, and access controls.

Data is in ignored `.data/prospects.sqlite3`. Back it up separately. `.env.example` documents variable names; the app reads exported environment variables and does **not** automatically load `.env`. Never commit keys or tokens.

## What works

- Search Google Places or Yelp business listings for an industry, city and market. Results require an explicit Save lead action and are deduplicated by provider ID or matching website.
- Manually add businesses or import CSV (`name,website,email,region,category`). Yelp provides its listing URL, not the business website: add the website after verifying it.
- Inspect public homepage HTML for HTTPS, title, meta description, viewport, and H1 elements. Private addresses and redirects to private addresses are blocked. TLS remains verified. These are basic HTML observations, not a rendered-browser, speed, ranking, conversion or accessibility audit. Check findings manually before using them in outreach.
- Generate and edit deterministic message drafts grounded in recorded findings. No invented contact information or AI credentials required.
- Track New, Reviewed, Contacted, Replied, Won, Closed, notes, opt-outs, and activity. Export CSV.
- Send a saved email individually via Gmail OAuth after review and an explicit Send click. One attempt per prospect prevents automatic duplicate sends. An uncertain result requires checking Gmail Sent; it cannot be retried from the UI. Successful API acceptance does not guarantee delivery.
- Copy messages and open a stored LinkedIn or Instagram profile for manual outreach. Social login, automated connections and social sending are not implemented.

No live search, messaging, or unattended outreach is possible until the relevant integration is configured. There is no background scheduler, reply synchronization, automatic email discovery, or automated follow-up sending.

## Connect live business search

### Google Places

Create a Google Cloud project, enable **Places API (New)** and billing, and create a restricted API key permitted to call that API. Export `GOOGLE_PLACES_API_KEY` into the server process and restart it. The app calls `places:searchText` with a maximum of 20 results and asks for business names, place IDs, website URLs, listing URLs and addresses. Requested fields can affect billing. Search is business discovery, not Google Search scraping. Review current Google Maps Platform storage and attribution terms before retaining or exporting provider data; this app does not implement provider-specific retention automation. Names in search results are marked with their source.

### Yelp

Obtain Yelp API access for your account and region, export `YELP_API_KEY`, and restart. The app calls `/v3/businesses/search`. Availability, quotas, permitted storage and use depend on your Yelp plan and current terms. Coverage in a region is not guaranteed. Listing results do not supply verified business email addresses.

## Connect Gmail

In Google Cloud, enable Gmail API and configure an OAuth consent screen and client for your own account. Authorize the minimum `https://www.googleapis.com/auth/gmail.send` scope through a supported OAuth flow, requesting offline access. Store the resulting refresh token securely. This repository does not host an OAuth login or consent callback.

Export `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, and `GMAIL_SENDER` in the server process. The sender must be the authorized account or an allowed send-as alias. Restart the app. Configuration indicators report presence, not verified authorization. OAuth verification, test-user restrictions and token expiry can depend on your Google project.

Before sending, verify the business contact address, personalize the saved draft, mark the prospect Reviewed, and click Send via Gmail. Opted-out prospects are blocked. Do not guess email addresses. Follow applicable UK/Australian marketing requirements, provider terms and recipient preferences. Use appropriate sender identification and a workable opt-out process; this application does not establish consent or legal eligibility.

## Validation

```sh
python3 -m unittest discover -s tests -v
node --check static/app.js
```

Tests use temporary databases and mocked external APIs; they do not send email. A real provider search and Gmail send still require your credentials and a recipient you choose. No live integration is claimed verified until tested.

## Cloud tasks

Use the existing checkout in each isolated cloud task; no extra Git worktree is necessary. Start `python3 app.py` in this repository when the dashboard is needed. Processes must be restarted after restoring an environment snapshot. No package installation is required. The onboarding chat cannot run a permanent outreach service; continuous hosting is a separate deployment task.
