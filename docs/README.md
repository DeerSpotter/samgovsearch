# SAM.gov Search Tool, No API Key

This folder contains the GitHub Pages front end for the hosted SAM.gov Search tool.

It is a real hosted tool architecture, not just a static fallback page:

- GitHub Pages serves `docs/index.html` from this repo.
- The existing OSIRIS Cloudflare Worker now exposes a SAM.gov proxy route at `/samgov`.
- The browser calls the OSIRIS Worker route, so GitHub Pages is not blocked by SAM.gov CORS.
- No `SAM_API_KEY` is used anywhere in this hosted version.

## What it does

- Batch search for keywords, part numbers, solicitation numbers, notice IDs, or NAICS.
- NAICS checkbox: number only lines such as `336414`, `336415`, and `336419` are searched as NAICS filters when checked.
- Date windows with normal range or all date ranges from `01/01/2018` to today.
- Status and procurement type filtering.
- Optional attachment enrichment using the SAM.gov internal resources endpoint.
- Attachment count and total MB filters.
- Title only local result filter, including hide terms.
- Sortable result table.
- Details panel with SAM.gov links, resource links, attachment names, and descriptions when available.
- CSV export of the currently displayed rows.

## Hosted pieces

### Front end

```text
docs/index.html
```

Expected GitHub Pages URL:

```text
https://deerspotter.github.io/samgovsearch/
```

### Worker proxy

The active proxy is now part of the existing OSIRIS Worker entry point:

```text
https://github.com/DeerSpotter/osiris-v2/blob/master/workers/osiris-flight-proxy/src/worker.ts
```

The OSIRIS Worker config now points to that wrapper entry point:

```text
https://github.com/DeerSpotter/osiris-v2/blob/master/wrangler.toml
```

Default Worker route used by the SAM.gov Search page:

```text
https://osiris-v2.spotterdeer.workers.dev/samgov
```

Health check:

```text
https://osiris-v2.spotterdeer.workers.dev/samgov/health
```

The front end has a **Proxy Worker URL** field. If the Worker URL changes, paste the new URL and click **Save URL**.

## GitHub Pages setup

1. Open this repository on GitHub.
2. Go to **Settings**.
3. Go to **Pages**.
4. Set **Source** to **Deploy from a branch**.
5. Set **Branch** to `main`.
6. Set **Folder** to `/docs`.
7. Save.

## Worker deployment

The separate `samgovsearch` Worker workflow was removed because it required Cloudflare secrets that were not available in GitHub Actions.

The SAM.gov proxy now deploys whenever the existing OSIRIS Worker deployment picks up changes to:

```text
DeerSpotter/osiris-v2
wrangler.toml
workers/osiris-flight-proxy/src/worker.ts
```

## SAM.gov endpoints relayed by the Worker

```text
https://sam.gov/api/prod/sgs/v1/search/
https://sam.gov/api/prod/opps/v2/opportunities/{notice_id}
https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources
https://sam.gov/api/prod/opps/v3/opportunities/resources/files/{resource_id}/download
```

## Limits

Controlled attachments still require normal SAM.gov authorization. This tool does not bypass SAM.gov sign in, controlled document access, or any SAM.gov permission rules.
