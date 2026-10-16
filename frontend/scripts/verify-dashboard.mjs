/**
 * End-to-end dashboard check in a real browser.
 *
 * Loads the console, loads a demo application, scores it, and asserts the UI
 * actually rendered the score, tier, policy and SHAP panels. Run with the API
 * on :8000 and the dashboard on :3000.
 *
 *   npm install --no-save puppeteer-core      # from frontend/
 *   node ../scripts/verify_dashboard.mjs
 */

import puppeteer from "puppeteer-core";

const CHROME =
  process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const DASHBOARD = process.env.DASHBOARD_URL ?? "http://localhost:3000/";
const DEMO_FILE = process.env.DEMO_FILE ?? "Shopkeeper";

const checks = [];
function check(name, passed, detail = "") {
  checks.push({ name, passed, detail });
  console.log(`${passed ? "PASS" : "FAIL"}  ${name}${detail ? ` -> ${detail}` : ""}`);
}

async function clickByText(page, text) {
  const handle = await page.evaluateHandle((needle) => {
    const nodes = Array.from(document.querySelectorAll("button"));
    return nodes.find((node) => (node.textContent ?? "").includes(needle)) ?? null;
  }, text);
  const element = handle.asElement();
  if (!element) throw new Error(`button containing "${text}" not found`);
  await element.click();
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1500, height: 1000 });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto(DASHBOARD, { waitUntil: "networkidle2", timeout: 30_000 });
  check("dashboard loads", (await page.title()).includes("Credit Scoring"), await page.title());

  await clickByText(page, DEMO_FILE);
  await clickByText(page, "Score application");

  // Wait on an HTML panel rather than the score itself: the score is rendered as
  // SVG <text>, which is not guaranteed to appear in body.innerText.
  try {
    await page.waitForFunction(
      () => document.body.innerText.includes("Recommended facility"),
      { timeout: 30_000 },
    );
  } catch (error) {
    const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 1500));
    console.log("\n--- page text at timeout ---\n" + bodyText);
    console.log("\n--- client errors ---\n" + errors.join("\n"));
    throw error;
  }

  // NOTE: innerText reflects rendered text, so CSS `uppercase` labels come back
  // uppercased. All text assertions are therefore case-insensitive.
  const rawText = await page.evaluate(() => document.body.innerText);
  const text = rawText.toLowerCase();
  const svgCount = await page.evaluate(() => document.querySelectorAll("svg path").length);
  const svgText = await page.evaluate(() =>
    Array.from(document.querySelectorAll("svg text"))
      .map((node) => node.textContent?.trim())
      .filter(Boolean)
      .join(" "),
  );

  // The dial renders four axis labels plus the score itself, so the score is the
  // 3-digit number that is not one of the band boundaries.
  const axisValues = new Set(["300", "580", "680", "900"]);
  const dialNumbers = (svgText.match(/\b\d{3}\b/g) ?? []).filter((value) => !axisValues.has(value));
  const score = dialNumbers[0];
  check(
    "score dial renders a 300-900 score",
    dialNumbers.length === 1 && Number(score) >= 300 && Number(score) <= 900,
    `score=${score} (axis labels excluded)`,
  );
  const readout = text.match(/score band\s*\n?\s*(\d{3})/)?.[1];
  check("dial and score readout agree", readout === score, `dial=${score} readout=${readout}`);
  check("score gauge drawn", svgCount >= 4, `${svgCount} svg paths`);
  check("tier bands drawn on the dial", /680/.test(svgText) && /580/.test(svgText), svgText.replace(/\s+/g, " ").slice(0, 90));
  check(
    "risk tier indicator shown",
    /(pre-approved|manual review|high risk)/.test(text),
  );

  check("recommended facility panel", text.includes("recommended facility"));
  check("binding constraint disclosed", text.includes("binding constraint:"));
  check("rate band shown", text.includes("rate band p.a."));
  check("derived ratios listed", text.includes("proposed debt service") && text.includes("collateral cover"));

  check("feature breakdown (SHAP) rendered", text.includes("feature breakdown") && text.includes("pts"));
  check(
    "explainability summary present",
    text.includes("main strengths") || text.includes("main risk drivers"),
  );
  check("what-if simulator available", text.includes("what-if simulator") && text.includes("quick scenarios"));

  check("no client-side runtime errors", errors.length === 0, errors.slice(0, 2).join(" | "));

  // Exercise the simulator in the browser.
  await clickByText(page, "Clear utility delays");
  await clickByText(page, "Run simulation");
  await page.waitForFunction(() => document.body.innerText.toLowerCase().includes("baseline"), {
    timeout: 30_000,
  });
  const simulated = (await page.evaluate(() => document.body.innerText)).toLowerCase();
  const delta = simulated.match(/score ([+-]\d+) pts/)?.[1];
  check("simulator returns a scored scenario", Boolean(delta), `delta=${delta} pts`);
  check(
    "simulator explains what moved",
    simulated.includes("what moved") || simulated.includes("no explainability factor moved"),
  );

  const snapshot = await page.evaluate(() => {
    const lines = document.body.innerText.split("\n").map((line) => line.trim()).filter(Boolean);
    return lines.slice(0, 34).join(" | ");
  });
  console.log("\n--- rendered summary ---\n" + snapshot);
} finally {
  await browser.close();
}

const failed = checks.filter((item) => !item.passed);
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
process.exit(failed.length === 0 ? 0 : 1);
