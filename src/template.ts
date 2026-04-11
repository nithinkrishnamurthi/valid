import type { Report, Item } from "./report.js";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

function renderItem(item: Item): string {
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

  return `
    <div class="item prose-item">
      <p>${content}</p>
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

export function buildHtml(report: Report): string {
  const groups = groupBySections(report.items);

  const body = groups
    .map((group, index) => {
      const heading = group.section
        ? `<div class="section-label"><span>${escapeHtml(group.section)}</span></div>`
        : "";
      const items = group.items.map(renderItem).join("\n");
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
    white-space: pre-wrap;
  }

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
