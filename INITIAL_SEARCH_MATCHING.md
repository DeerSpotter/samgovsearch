# Initial Search Matching

The launcher now opens `samgovsearch_pro_initial_match.py`.

The app keeps the same single UI and validates returned rows against the entered batch keyword syntax before they are shown in the result table.

Plain terms use AND logic. Quoted text is treated as one exact phrase. Wildcards use `*` and `?`. Regex tokens follow the same local filter syntax.

The initial match filter checks title, solicitation number, notice ID, type, dates, organization, NAICS, PSC, links, attachment names, cached description, and agency path when available.
