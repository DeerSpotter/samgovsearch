# Local Result Filter Syntax

The filter fields are local only. They search the results already loaded in the table and do not call SAM.gov again.

## Show results containing

The **Show results containing** field uses AND logic when multiple terms are entered. Every term must match the row.

Examples:

```text
patriot
```

Plain text is a case-insensitive contains match.

```text
"patriot missile"
```

Quotes keep the words together as one exact phrase.

```text
W31P4Q*
```

`*` matches any text and `?` matches one character.

```text
re:\bPatriot\b
```

`re:` starts a regular expression match.

```text
/Patriot.*Spares/
```

Slash-wrapped text is also treated as a regular expression.

## Hide results containing

The **Hide results containing any of these comma-separated terms** field uses OR logic. If any comma-separated term matches, the row is hidden.

Examples:

```text
amendment, award, cancelled
```

```text
"sources sought", draft, re:\bcancelled\b
```

## What is searched

The filters check row data, attachment names, cached description, solicitation number, notice ID, organization, NAICS, PSC, SAM links, and resource links when available.

Clearing the field restores the loaded rows without re-running the SAM.gov search.
