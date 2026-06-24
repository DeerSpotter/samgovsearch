# SAM.gov Search, No API Key GitHub Pages App

This folder contains a static GitHub Pages version of the SAM.gov Search tool.

## What it does

- Runs as one static `index.html` file.
- Requires no `SAM_API_KEY`.
- Requires no Python, Tkinter, SQLite, Playwright, or server.
- Uses the same no key SAM.gov website endpoints as the desktop app where the browser allows it:
  - `https://sam.gov/api/prod/sgs/v1/search/`
  - `https://sam.gov/api/prod/opps/v2/opportunities/{notice_id}`
  - `https://sam.gov/api/prod/opps/v3/opportunities/{notice_id}/resources`
- Supports batch search, date windows, active status, procurement type, attachment filters, title only result filtering, sortable columns, result details, resource links, and CSV export.
- Includes a NAICS helper checkbox. When checked, number only lines are sent with NAICS style parameters and results are client filtered by NAICS when the returned data includes a NAICS value.

## GitHub Pages setup

Use either Pages source option.

### Simple branch based setup

1. Open the repository on GitHub.
2. Go to **Settings**.
3. Go to **Pages**.
4. Set **Source** to **Deploy from a branch**.
5. Set **Branch** to `main`.
6. Set **Folder** to `/docs`.
7. Save.

The page should publish as:

```text
https://deerspotter.github.io/samgovsearch/
```

### GitHub Actions setup

This static app does not need a build step. A Pages workflow is optional. The branch based `/docs` setting is enough.

## Important browser limit

GitHub Pages is static browser JavaScript. If SAM.gov does not allow cross origin browser reads from `github.io`, the live table cannot read the internal no key endpoint. In that case, the page creates SAM.gov search links for each batch term.

That is a browser CORS limit. It is different from an API key problem.

If live browser search is blocked and you still want this hosted tool to fetch results, the next step is a very small no key proxy such as a Cloudflare Worker. The worker would not need a SAM.gov API key. It would only relay allowed public SAM.gov website endpoint responses to the GitHub Pages front end.

## Attachment limits

Public resource links can be opened from the details panel when SAM.gov returns them. Controlled attachments still require normal SAM.gov access and authorization.
