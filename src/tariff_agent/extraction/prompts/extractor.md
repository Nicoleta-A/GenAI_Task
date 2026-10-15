Extract port tariff ChargeRules from the attached native PDF page(s).

Requirements:
- Copy numbers exactly from the page; never invent rates.
- Keep header-to-column port mapping; emit one rule (or port group) per distinct rate column.
- Use ports=["*"] for "other ports" / catch-all columns.
- Encode "excluding X" by emitting specific port rules plus a "*" fallback.
- applies_when is True for the ordinary / other / general row. Do not invent fact names. Put category notes in assumptions.
- If the page charges per service (entering and leaving), set times to num_operations, not 1.
- band.when is Python True or a comparison using the fact vocabulary, never lowercase true.
- Provide source_page (printed) and a short source_quote that appears on the page.
- applies_when, band.when, per, and times are Python expressions: use `and` / `or`, never `&&` / `||`.
- Never perform arithmetic; only structure the rules.
