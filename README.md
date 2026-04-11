# valid

MCP server that composites screenshots, text, and other artifacts into a single rendered PNG image. Uses a headless browser (Playwright) to render an HTML template and screenshot it.

## Install

```bash
npx valid
```

First run downloads the Chromium binary (~300MB) into the npm cache.

## MCP config

```json
{
  "mcpServers": {
    "valid": {
      "command": "npx",
      "args": ["valid"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `valid_create` | Create a new report (returns `report_id`) |
| `valid_add_screenshot` | Add a screenshot from disk (auto-resized, JPEG encoded) |
| `valid_add_text` | Add a text block |
| `valid_render` | Render the report to a PNG file |
