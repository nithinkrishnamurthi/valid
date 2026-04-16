# Add priority indicators to task cards

Each task has a `priority` field (high, medium, low). Add a visual indicator
to every card:

- **high** — 4px left border, color `#ef4444` (red)
- **medium** — 4px left border, color `#f59e0b` (amber)
- **low** — 4px left border, color `#22c55e` (green)

Also add a small priority label inside the card (below the assignee line)
showing the priority text in the matching color.

Requirements:
- Every card gets the colored left border based on its priority
- Priority label text matches the border color
- Existing card layout (title, assignee) is preserved
- Column layout is unaffected
