# SAM.gov Search Tool, No API Key

This folder contains the GitHub Pages front end for the hosted SAM.gov Search tool.

It is a real hosted tool architecture, not just a static fallback page:

- GitHub Pages serves `docs/index.html` from this repo.
- Cloudflare Worker `samgovsearch` relays the no key SAM.gov website/internal endpoints.
- The browser calls the Worker, so GitHub Pages is not blocked by SAM.gov CORS.
- No `SAM_API_KEY` is used anywhere in this hosted version.

## What it does

- Batch search for keywords, part numbers, solicitation numbers, notice IDs, or NAICS.
- NAICS checkbox: number only lines such as `336414`, `336415`, and `336419` are searched as NAICS filters when checked.
- Search modes for Auto, Title, Solicitation Number, Notice ID, Title + Solicitation Number, and Attachment Name Only.
- Attachment Name Only scans returned notices in the selected date/status range and matches against attachment filenames.
- Date windows with normal range or all date ranges from `01/01/2018` to today.
- Status and procurement type filtering.
- Optional attachment enrichment using the SAM.gov internal resources endpoint.
- Attachment count and total MB filters.
- Title only local result filter, including hide terms.
- Sortable result table.
- Details panel with SAM.gov links, resource links, attachment names, and descriptions when available.
- CSV export of the currently displayed rows.

## Attachment filename searching

SAM.gov does not expose a simple public search box that directly searches every attachment filename.

The hosted tool implements this by:

1. Pulling notices for the selected date/status/procurement range.
2. Calling the resources endpoint for each notice scanned.
3. Matching the search term against the returned attachment names.

Use a tight date range and a reasonable **Max / Term** value for this mode because it requires one resources request per notice scanned.

## Hosted pieces

### Front end

```text
docs/index.html
```

GitHub Pages URL:

```text
https://deerspotter.github.io/samgovsearch/
```

### Worker proxy

Worker source in this repo:

```text
workers/samgov-proxy-worker.js
workers/wrangler.toml
```

Worker URL:

```text
https://samgovsearch.spotterdeer.workers.dev
```

Health check:

```text
https://samgovsearch.spotterdeer.workers.dev/health
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

The Worker is deployed from this repository through Cloudflare Git integration.

Cloudflare settings:

```text
Repository: DeerSpotter/samgovsearch
Branch: main
Root directory: workers
Build command: blank
Deploy command: npx wrangler deploy
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
