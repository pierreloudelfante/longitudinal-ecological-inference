import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:[A-Za-z]:)/, (m) => m.slice(1))), "..");
const htmlPath = process.argv[2] || path.join(root, "work", "longitudinal_2000_release_professeur_candidate", "01_RAPPORT", "RAPPORT_LONGITUDINAL.html");
const pdfPath = process.argv[3] || path.join(root, "work", "longitudinal_2000_release_professeur_candidate", "01_RAPPORT", "RAPPORT_LONGITUDINAL.pdf");
const chrome = process.env.CHROME_PATH;

if (!fs.existsSync(htmlPath)) throw new Error(`Missing HTML source: ${htmlPath}`);
if (!chrome || !fs.existsSync(chrome)) throw new Error("Set CHROME_PATH to a Chromium or Chrome executable.");
const browser = await chromium.launch({
  executablePath: chrome,
  headless: true,
  args: ["--disable-gpu", "--disable-crash-reporter", "--disable-breakpad", "--allow-file-access-from-files"],
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
  await page.waitForFunction(
    () => document.documentElement.dataset.dataAnalyticsPortableReader === "ready",
    null,
    { timeout: 20000 },
  );
  await page.waitForTimeout(1500);
  const qa = await page.evaluate(() => ({
    state: document.documentElement.dataset.dataAnalyticsPortableReader,
    fallbackHidden: document.getElementById("data-analytics-portable-fallback")?.classList.contains("portable-enhanced-hidden"),
    readerVisible: !document.getElementById("data-analytics-portable-reader")?.hasAttribute("aria-hidden"),
    svgs: document.querySelectorAll("#data-analytics-portable-reader svg").length,
    charts: document.querySelectorAll("#data-analytics-portable-reader [data-chart-id], #data-analytics-portable-reader [data-artifact-chart-id]").length,
    blocks: document.querySelectorAll("#data-analytics-portable-reader section, #data-analytics-portable-reader article").length,
    tables: document.querySelectorAll("#data-analytics-portable-reader table").length,
    canvases: document.querySelectorAll("#data-analytics-portable-reader canvas").length,
    sectionClasses: Array.from(new Set(Array.from(document.querySelectorAll("#data-analytics-portable-reader section")).map((node) => node.className))).slice(0, 20),
    chartPanelSvgs: document.querySelectorAll("#data-analytics-portable-reader .chart-panel svg").length,
    firstSvgAncestors: (() => {
      const svg = document.querySelector("#data-analytics-portable-reader svg");
      const values = [];
      let node = svg;
      for (let index = 0; node && index < 5; index += 1, node = node.parentElement) {
        values.push({ tag: node.tagName, className: String(node.className?.baseVal ?? node.className ?? ""), role: node.getAttribute?.("role") });
      }
      return values;
    })(),
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (qa.state !== "ready" || !qa.fallbackHidden || !qa.readerVisible || qa.svgs < 10) {
    throw new Error(`Enhanced reader QA failed: ${JSON.stringify(qa)}`);
  }
  if (errors.length) throw new Error(`Browser errors: ${JSON.stringify(errors)}`);
  await page.emulateMedia({ media: "print", colorScheme: "light" });
  await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete), null, { timeout: 30000 });
  const printQa = await page.evaluate(() => ({
    fallbackDisplay: getComputedStyle(document.getElementById("data-analytics-portable-fallback")).display,
    readerDisplay: getComputedStyle(document.getElementById("data-analytics-portable-reader")).display,
    fallbackImages: document.querySelectorAll("#data-analytics-portable-fallback img").length,
    incompleteImages: Array.from(document.images).filter((image) => !image.complete || image.naturalWidth === 0).length,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (printQa.fallbackDisplay === "none" || printQa.fallbackImages < 7 || printQa.incompleteImages !== 0) {
    throw new Error(`Print fallback QA failed: ${JSON.stringify(printQa)}`);
  }
  await page.pdf({
    path: pdfPath,
    format: "A4",
    printBackground: true,
    displayHeaderFooter: false,
    margin: { top: "12mm", right: "10mm", bottom: "12mm", left: "10mm" },
  });
  console.log(JSON.stringify({ status: "complete", html: htmlPath, pdf: pdfPath, bytes: fs.statSync(pdfPath).size, qa, printQa }));
} finally {
  await browser.close();
}
