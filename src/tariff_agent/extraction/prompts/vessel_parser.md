Parse free-text vessel descriptions into structured facts.

- Never invent gt, num_operations, or days_alongside.
- If a required fact is absent, omit it (the caller will raise MissingFacts).
- Map synonyms: gross tonnage → gt, LOA → loa, days alongside → days_alongside.
- num_operations defaults only if the text clearly implies entering and leaving (2).
