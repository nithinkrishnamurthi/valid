import crypto from "node:crypto";

export interface Item {
  type: "screenshot" | "text";
  section?: string;
  label?: string;
  dataUri?: string;
  content?: string;
  format?: "prose" | "code";
}

export interface Report {
  id: string;
  title: string;
  description?: string;
  items: Item[];
  createdAt: Date;
}

const reports = new Map<string, Report>();

export function createReport(title: string, description?: string): Report {
  const id = crypto.randomUUID().slice(0, 8);
  const report: Report = {
    id,
    title,
    description,
    items: [],
    createdAt: new Date(),
  };
  reports.set(id, report);
  return report;
}

export function getReport(id: string): Report | undefined {
  return reports.get(id);
}

export function addItem(reportId: string, item: Item): void {
  const report = reports.get(reportId);
  if (!report) throw new Error(`Report not found: ${reportId}`);
  report.items.push(item);
}

export function deleteReport(id: string): void {
  reports.delete(id);
}
