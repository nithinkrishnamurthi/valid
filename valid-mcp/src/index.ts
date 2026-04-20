import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { createReport, getReport, addItem } from "./report.js";
import { processImage } from "./image.js";
import { buildHtml } from "./template.js";
import { renderToImage } from "./renderer.js";
import path from "node:path";
import os from "node:os";

const server = new McpServer({
  name: "valid",
  version: "0.1.0",
});

server.tool(
  "valid_create",
  "Create a new validation report",
  {
    title: z.string().describe("Report title"),
    description: z.string().optional().describe("Optional report description"),
  },
  async ({ title, description }) => {
    const report = createReport(title, description);
    return {
      content: [{ type: "text", text: JSON.stringify({ report_id: report.id }) }],
    };
  }
);

server.tool(
  "valid_add_screenshot",
  "Add a screenshot to the report. Reads the image from disk, resizes to max 1280px width, and stores as base64 JPEG.",
  {
    report_id: z.string().describe("Report ID"),
    path: z.string().describe("Absolute path to image file"),
    label: z.string().optional().describe("Optional caption"),
    section: z.string().optional().describe("Optional group name"),
  },
  async ({ report_id, path: filePath, label, section }) => {
    const report = getReport(report_id);
    if (!report) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: `Report not found: ${report_id}` }) }],
        isError: true,
      };
    }

    const dataUri = await processImage(filePath);
    addItem(report_id, { type: "screenshot", dataUri, label, section });

    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
    };
  }
);

server.tool(
  "valid_add_text",
  "Add a text block to the report. Use format 'prose' for plain narrative text, 'code' for logs/output/terminal content.",
  {
    report_id: z.string().describe("Report ID"),
    content: z.string().describe("Text content"),
    format: z.enum(["prose", "code"]).default("prose").describe("'prose' for plain text, 'code' for logs/output"),
    section: z.string().optional().describe("Optional group name"),
  },
  async ({ report_id, content, format, section }) => {
    const report = getReport(report_id);
    if (!report) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: `Report not found: ${report_id}` }) }],
        isError: true,
      };
    }

    addItem(report_id, { type: "text", content, format, section });

    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
    };
  }
);

server.tool(
  "valid_add_status",
  "Add a status finding to the report (pass/fail/warn). Use this for verdict-bearing observations — not for prose context. Consecutive same-kind statuses in the same section render as one callout.",
  {
    report_id: z.string().describe("Report ID"),
    kind: z.enum(["pass", "fail", "warn"]).describe("Finding kind"),
    message: z.string().describe("Short finding text — one line if possible"),
    section: z.string().optional().describe("Optional group name"),
  },
  async ({ report_id, kind, message, section }) => {
    const report = getReport(report_id);
    if (!report) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: `Report not found: ${report_id}` }) }],
        isError: true,
      };
    }

    addItem(report_id, { type: "status", kind, message, section });

    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true }) }],
    };
  }
);

server.tool(
  "valid_render",
  "Render the report as a PNG image using a headless browser",
  {
    report_id: z.string().describe("Report ID"),
    output_path: z.string().optional().describe("Output path for the PNG (defaults to /tmp/valid-<id>.png)"),
  },
  async ({ report_id, output_path }) => {
    const report = getReport(report_id);
    if (!report) {
      return {
        content: [{ type: "text", text: JSON.stringify({ error: `Report not found: ${report_id}` }) }],
        isError: true,
      };
    }

    const outPath = output_path || path.join(os.tmpdir(), `valid-${report_id}.png`);
    const html = buildHtml(report);
    const resultPath = await renderToImage(html, outPath);

    return {
      content: [{ type: "text", text: JSON.stringify({ path: resultPath }) }],
    };
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
