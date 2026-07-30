import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

// Worker/MCP browser specs: one consistent per-test total timeout (packet §6),
// greater than any internal terminal-state wait (max 40s).
test.beforeEach(() => { test.setTimeout(90_000); });

// Slice 2B Batch B — Tutor code + Wolfram browser paths (packet §8.3).
// Drives the real UI/API/worker/MCP against the controlled fakes. Chromium only.

const STUB = process.env.SYSTEM_TEST_STUB_URL ?? "http://127.0.0.1:18091";
const FAKE_EXEC = process.env.SYSTEM_TEST_FAKE_EXEC_URL ?? "http://127.0.0.1:18092";
const FAKE_WOLFRAM = process.env.SYSTEM_TEST_FAKE_WOLFRAM_URL ?? "http://127.0.0.1:18093";

async function resetAll(request: APIRequestContext, stub: string, exec = "default", wolfram = "success") {
  await request.post(`${STUB}/__reset`, { data: { scenario: stub } });
  await request.post(`${FAKE_EXEC}/__reset`, { data: { scenario: exec } });
  await request.post(`${FAKE_WOLFRAM}/__reset`, { data: { scenario: wolfram } });
}

async function wolframCalls(request: APIRequestContext, scenario = "success"): Promise<number> {
  const r = await request.get(`${FAKE_WOLFRAM}/__calls/${scenario}`);
  return (await r.json()).count as number;
}

async function execCalls(request: APIRequestContext, scenario = "default"): Promise<number> {
  const r = await request.get(`${FAKE_EXEC}/__calls/${scenario}`);
  return (await r.json()).count as number;
}

async function openTutor(page: Page): Promise<Locator> {
  await page.goto("/");
  await page.getByRole("button", { name: /Stage5 2B Browser/ }).first().click();
  const course = page.getByRole("button", { name: /Stage5 2B Tools/ });
  await expect(course).toBeVisible({ timeout: 20_000 });
  await course.click();
  await expect(page.getByRole("heading", { name: /Stage5 2B Tools/ })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "阅读", exact: true }).click();
  await page.getByRole("tab", { name: "Tutor" }).click();
  const tutor = page.getByRole("complementary", { name: "课程 Tutor" });
  await expect(tutor).toBeVisible({ timeout: 20_000 });
  // Use course scope so no lesson selection is required.
  await tutor.getByRole("button", { name: "整门课程" }).click();
  return tutor;
}

async function ask(page: Page, tutor: Locator, question: string) {
  await tutor.getByPlaceholder("输入问题").fill(question);
  page.once("dialog", async (dialog) => { await dialog.accept(); });
  await tutor.getByRole("button", { name: "发送" }).click();
}

// Slice 2B Batch B packet §6: assert only the controlled, grounding-legal
// observation/counter facts. The stub's direct_answer cites a forged "e1" that
// the course-scope ledger never admits, so product grounding correctly drops
// that factual block — we must NOT wait for "Binary search halves".
// "Turn succeeded" is asserted via the per-Turn tool-usage summary
// (代码/科学 N 次): TutorPanel renders that line ONLY when the latest visible
// Turn reached status "succeeded", so its visibility is both the terminal-state
// assertion and the count contract. (A literal getByText("succeeded") is
// ambiguous because earlier tests accumulate succeeded Turns in the shared
// session.) Each test also checks the controlled observation block (required
// scenarios only) and the fake backend counter matching the scenario contract.

test("Tutor code required: authorizes and runs code", async ({ page, request }) => {
  await resetAll(request, "tutor_code_required");
  const tutor = await openTutor(page);
  await tutor.getByRole("checkbox", { name: /允许本次运行代码/ }).check();
  await ask(page, tutor, "Run a small program and tell me the output.");
  await expect(tutor.getByText(/代码\s*1\s*次/)).toBeVisible({ timeout: 40_000 });
  await expect(tutor.getByText(/Running the small program confirmed the observed behaviour/)).toBeVisible({ timeout: 10_000 });
  expect(await execCalls(request)).toBe(1);
});

test("Tutor code negative: authorized but zero code calls", async ({ page, request }) => {
  await resetAll(request, "tutor_code_negative");
  const tutor = await openTutor(page);
  await tutor.getByRole("checkbox", { name: /允许本次运行代码/ }).check();
  await ask(page, tutor, "Explain the concept in plain terms.");
  await expect(tutor.getByText(/代码\s*0\s*次/)).toBeVisible({ timeout: 40_000 });
  expect(await execCalls(request)).toBe(0);
});

test("Tutor Wolfram required: calls the allowlisted tool", async ({ page, request }) => {
  await resetAll(request, "tutor_wolfram_required");
  expect(await wolframCalls(request)).toBe(0);
  const tutor = await openTutor(page);
  await tutor.getByRole("checkbox", { name: /允许本次使用科学工具/ }).check();
  await ask(page, tutor, "Compute the symbolic result and verify it.");
  await expect(tutor.getByText(/科学\s*1\s*次/)).toBeVisible({ timeout: 40_000 });
  await expect(tutor.getByText(/The symbolic result was verified by the computation tool/)).toBeVisible({ timeout: 10_000 });
  expect(await wolframCalls(request)).toBeGreaterThanOrEqual(1);
});

test("Tutor Wolfram negative: authorized but zero science calls", async ({ page, request }) => {
  await resetAll(request, "tutor_wolfram_negative");
  expect(await wolframCalls(request)).toBe(0);
  const tutor = await openTutor(page);
  await tutor.getByRole("checkbox", { name: /允许本次使用科学工具/ }).check();
  await ask(page, tutor, "Define the term in your own words.");
  await expect(tutor.getByText(/科学\s*0\s*次/)).toBeVisible({ timeout: 40_000 });
  expect(await wolframCalls(request)).toBe(0);
});
