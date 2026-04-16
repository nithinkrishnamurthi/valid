import { chromium } from "playwright-core";

export async function renderToImage(html: string, outputPath: string): Promise<string> {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1200, height: 800 },
      deviceScaleFactor: 2,
    });
    await page.setContent(html, { waitUntil: "networkidle" });
    await page.screenshot({ path: outputPath, fullPage: true, type: "png" });
    return outputPath;
  } finally {
    await browser.close();
  }
}
