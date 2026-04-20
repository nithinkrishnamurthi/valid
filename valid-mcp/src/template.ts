import type { Report, Item, StatusKind } from "./report.js";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(text: string): string {
  // Process block-level elements first, then inline
  const lines = text.split("\n");
  const blocks: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Unordered list
    if (/^[\-\*]\s/.test(line.trim())) {
      const items: string[] = [];
      while (i < lines.length && /^[\-\*]\s/.test(lines[i].trim())) {
        items.push(`<li>${inlineMarkdown(escapeHtml(lines[i].trim().slice(2)))}</li>`);
        i++;
      }
      blocks.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\d+\.\s/.test(line.trim())) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        items.push(`<li>${inlineMarkdown(escapeHtml(lines[i].trim().replace(/^\d+\.\s/, "")))}</li>`);
        i++;
      }
      blocks.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    // Regular paragraph — collect consecutive non-empty, non-special lines
    const paraLines: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^[\-\*]\s/.test(lines[i].trim()) && !/^\d+\.\s/.test(lines[i].trim())) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push(`<p>${inlineMarkdown(escapeHtml(paraLines.join("\n")))}</p>`);
  }

  return blocks.join("\n");
}

function inlineMarkdown(html: string): string {
  return html
    // Bold: **text** or __text__
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    // Italic: *text* or _text_
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/(?<!\w)_(.+?)_(?!\w)/g, "<em>$1</em>")
    // Inline code: `text`
    .replace(/`(.+?)`/g, "<code>$1</code>")
    // Line breaks
    .replace(/\n/g, "<br>");
}

function formatDate(date: Date): string {
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderStatusGroup(entries: { kind: StatusKind; message: string }[]): string {
  const rows = entries
    .map(
      (e) => `
      <div class="callout-row callout-row-${e.kind}">
        <span class="callout-label">${e.kind.toUpperCase()}</span>
        <span class="callout-text">${inlineMarkdown(escapeHtml(e.message))}</span>
      </div>`
    )
    .join("");
  return `<div class="callout">${rows}</div>`;
}

function renderItem(item: Item): string {
  if (item.type === "status") {
    // Single-item fallback; grouped rendering happens in buildHtml.
    return renderStatusGroup([{ kind: (item.kind ?? "warn") as StatusKind, message: item.message ?? "" }]);
  }
  if (item.type === "screenshot") {
    return `
      <div class="item screenshot-item">
        <div class="screenshot-frame">
          <img src="${item.dataUri}" alt="${escapeHtml(item.label || "Screenshot")}" />
        </div>
        ${item.label ? `<p class="caption">${escapeHtml(item.label)}</p>` : ""}
      </div>`;
  }

  const content = escapeHtml(item.content || "");

  if (item.format === "code") {
    const lineCount = (item.content || "").split("\n").length;
    return `
      <div class="item text-item">
        <div class="code-block">
          <div class="code-block-header">
            <span class="code-block-meta">${lineCount} line${lineCount !== 1 ? "s" : ""}</span>
          </div>
          <pre>${content}</pre>
        </div>
      </div>`;
  }

  const rendered = renderMarkdown(item.content || "");
  return `
    <div class="item prose-item">
      ${rendered}
    </div>`;
}

function groupBySections(items: Item[]): { section: string | null; items: Item[] }[] {
  const groups: { section: string | null; items: Item[] }[] = [];
  let current: { section: string | null; items: Item[] } | null = null;

  for (const item of items) {
    const section = item.section ?? null;
    if (!current || current.section !== section) {
      current = { section, items: [] };
      groups.push(current);
    }
    current.items.push(item);
  }

  return groups;
}

function renderSectionItems(items: Item[]): string {
  // Collapse runs of consecutive status items with the same kind into a single
  // callout. Non-status items render as-is.
  const parts: string[] = [];
  let i = 0;
  while (i < items.length) {
    const item = items[i];
    if (item.type === "status") {
      const entries: { kind: StatusKind; message: string }[] = [
        { kind: (item.kind ?? "warn") as StatusKind, message: item.message ?? "" },
      ];
      let j = i + 1;
      while (j < items.length && items[j].type === "status") {
        entries.push({
          kind: (items[j].kind ?? "warn") as StatusKind,
          message: items[j].message ?? "",
        });
        j++;
      }
      parts.push(renderStatusGroup(entries));
      i = j;
      continue;
    }
    parts.push(renderItem(item));
    i++;
  }
  return parts.join("\n");
}

export function buildHtml(report: Report): string {
  const groups = groupBySections(report.items);

  const body = groups
    .map((group, index) => {
      const heading = group.section
        ? `<div class="section-label"><span>${escapeHtml(group.section)}</span></div>`
        : "";
      const items = renderSectionItems(group.items);
      const divider = index > 0 ? `<div class="section-divider"></div>` : "";
      return `
        ${divider}
        ${heading}
        ${items}`;
    })
    .join("\n");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=1200" />
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f0f0f0;
    color: #1a1a1a;
    line-height: 1.6;
    padding: 40px;
  }

  .page {
    max-width: 1120px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.04);
    overflow: hidden;
  }

  /* Header */
  .header {
    padding: 44px 56px 40px;
    background: #111111;
    color: #ffffff;
  }

  .header h1 {
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: #ffffff;
    line-height: 1.3;
  }

  .header .description {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    color: rgba(255,255,255,0.7);
    line-height: 1.7;
    margin-top: 12px;
  }

  /* Content area */
  .content {
    padding: 36px 56px 44px;
  }

  /* Sections */
  .section-divider {
    height: 1px;
    background: #e5e7eb;
    margin: 32px 0 28px;
  }

  .section-label {
    margin-bottom: 16px;
  }

  .section-label span {
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    background: #f3f4f6;
    padding: 4px 12px;
    border-radius: 4px;
  }

  /* Items */
  .item {
    margin-bottom: 20px;
  }

  /* Screenshots */
  .screenshot-frame {
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
  }

  .screenshot-frame img {
    width: 100%;
    display: block;
  }

  .caption {
    font-size: 12px;
    color: #9ca3af;
    margin-top: 8px;
  }

  /* Prose text */
  .prose-item p {
    font-size: 14px;
    color: #374151;
    line-height: 1.7;
    margin-bottom: 8px;
  }

  .prose-item p:last-child {
    margin-bottom: 0;
  }

  .prose-item strong {
    font-weight: 600;
    color: #1f2937;
  }

  .prose-item em {
    font-style: italic;
  }

  .prose-item code {
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 12px;
    background: #f3f4f6;
    padding: 2px 6px;
    border-radius: 3px;
    color: #1f2937;
  }

  .prose-item ul, .prose-item ol {
    font-size: 14px;
    color: #374151;
    line-height: 1.7;
    margin-bottom: 8px;
    padding-left: 24px;
  }

  .prose-item li {
    margin-bottom: 2px;
  }

  /* Status callouts */
  .callout {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 4px 16px;
    margin-bottom: 20px;
    background: #ffffff;
  }

  .callout-row {
    display: flex;
    gap: 14px;
    align-items: center;
    padding: 10px 0;
  }

  .callout-row + .callout-row {
    border-top: 1px solid #f1f3f5;
  }

  .callout-label {
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 3px 8px;
    border-radius: 4px;
    flex-shrink: 0;
    line-height: 1.4;
    min-width: 48px;
    text-align: center;
    color: #ffffff;
  }

  .callout-text {
    flex: 1;
    font-size: 14px;
    line-height: 1.5;
    color: #1f2937;
  }

  .callout-row-fail .callout-label { background: #dc2626; }
  .callout-row-pass .callout-label { background: #16a34a; }
  .callout-row-warn .callout-label { background: #d97706; }

  /* Code/text blocks */
  .code-block {
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e5e7eb;
  }

  .code-block-header {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    padding: 6px 16px;
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }

  .code-block-meta {
    font-family: 'JetBrains Mono', 'SF Mono', monospace;
    font-size: 10px;
    color: #9ca3af;
  }

  .code-block pre {
    font-family: 'JetBrains Mono', 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 12px;
    line-height: 1.7;
    color: #374151;
    background: #fafafa;
    padding: 14px 20px;
    white-space: pre-wrap;
    word-wrap: break-word;
  }

  /* Footer */
  .footer {
    padding: 16px 56px;
    border-top: 1px solid #eaeaea;
    background: #fafafa;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .footer-text {
    font-size: 11px;
    color: #b0b0b0;
  }

  .footer-brand {
    font-size: 11px;
    font-weight: 600;
    color: #d1d5db;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
</style>
</head>
<body>
  <div class="page">
    <div class="header">
      <h1>${escapeHtml(report.title)}</h1>
      ${report.description ? `<p class="description">${escapeHtml(report.description)}</p>` : ""}
    </div>
    <div class="content">
      ${body}
    </div>
    <div class="footer">
      <span class="footer-text">${formatDate(report.createdAt)}</span>
      <span class="footer-brand">valid</span>
    </div>
  </div>
</body>
</html>`;
}
