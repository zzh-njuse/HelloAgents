import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

// Worker/MCP browser specs: one consistent per-test total timeout (packet §6),
// greater than any internal terminal-state wait (max 40s).
test.beforeEach(() => { test.setTimeout(90_000); });

// Slice 2B Batch B — Practice tool browser paths (packet §8.1/§8.2).
// Drives the real UI/API/worker/MCP against the controlled fakes. The fakes'
// reset/counters are reached via the host-published control ports (scenario +
// count only; never bodies). Chromium only.

const STUB = process.env.SYSTEM_TEST_STUB_URL ?? "http://127.0.0.1:18091";
const FAKE_EXEC = process.env.SYSTEM_TEST_FAKE_EXEC_URL ?? "http://127.0.0.1:18092";
const FAKE_WOLFRAM = process.env.SYSTEM_TEST_FAKE_WOLFRAM_URL ?? "http://127.0.0.1:18093";

const CORRECT_JAVA = "class Solution { static String solve(String input) { return input; } }";
const CORRECT_CPP = 'std::string solve(const std::string& input){ return input; }';

async function resetAll(request: APIRequestContext, stub: string, exec = "default", wolfram = "success") {
  await request.post(`${STUB}/__reset`, { data: { scenario: stub } });
  await request.post(`${FAKE_EXEC}/__reset`, { data: { scenario: exec } });
  await request.post(`${FAKE_WOLFRAM}/__reset`, { data: { scenario: wolfram } });
}

async function wolframCalls(request: APIRequestContext, scenario = "success"): Promise<number> {
  const r = await request.get(`${FAKE_WOLFRAM}/__calls/${scenario}`);
  return (await r.json()).count as number;
}

async function openPracticeForLesson(page: Page, lessonName: RegExp): Promise<Locator> {
  await page.goto("/");
  await page.getByRole("button", { name: /Stage5 2B Browser/ }).first().click();
  const course = page.getByRole("button", { name: /Stage5 2B Tools/ });
  await expect(course).toBeVisible({ timeout: 20_000 });
  await course.click();
  await expect(page.getByRole("heading", { name: /Stage5 2B Tools/ })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "阅读", exact: true }).click();
  await page.getByRole("tablist", { name: "中间视图" }).getByRole("tab", { name: "练习" }).click();
  const panel = page.getByRole("region", { name: "课节练习" });
  await expect(panel).toBeVisible({ timeout: 20_000 });
  await selectPracticeLesson(panel, lessonName);
  await clearExistingPracticeSets(page, panel);
  return panel;
}

// Slice 2B Batch B: every practice spec shares ONE seeded workspace/course, so
// a generation that succeeds in an earlier test leaves an ACTIVE PracticeSet for
// the lesson. When a later test opens that same lesson the panel renders the
// existing set (not the generate form) — so the 题数 input is absent and the
// form fill times out — and even via "新建练习" the product's novelty dedup
// (practice_generation.py: `PracticeSet.lifecycle_status != "deleted"`) would
// reject an identical re-generated item. Clear pre-existing sets through the
// real UI (删除集合 + confirm dialog, exactly what a user does to regenerate a
// lesson) so each test starts from a clean generate form. No API bypass, no
// force click; bounded loop covers an unexpected leftover from a prior retry.
async function clearExistingPracticeSets(page: Page, panel: Locator) {
  // The 练习集合 set-picker renders ONLY when at least one PracticeSet exists
  // for the lesson (PracticePanel: `sets.length || selectedSet`). After a
  // lesson switch the panel briefly shows the generate form while the set list
  // is still loading (selectedSet=null), so checking the form first would race.
  // Waiting for the picker (bounded window; the fetch is a fast local call) is
  // the load-settled signal: picker present => a set exists => delete it;
  // picker absent after the window => no sets => the visible form is stable.
  const setPicker = panel.getByLabel("练习集合");
  const deleteButton = panel.getByRole("button", { name: "删除集合" });
  const formInput = panel.getByLabel("题数");
  for (let guard = 0; guard < 8; guard += 1) {
    const hasSets = await setPicker.isVisible({ timeout: guard === 0 ? 3_000 : 750 }).catch(() => false);
    if (!hasSets) {
      await expect(formInput).toBeVisible({ timeout: 10_000 });
      return;
    }
    await expect(deleteButton).toBeVisible({ timeout: 10_000 });
    // Each deletion's confirm dialog is awaited in sync with its click and
    // asserted to appear; the wait is consumed per iteration so no dialog handler
    // leaks into the next loop turn or the next action (packet Fix 7).
    await Promise.all([
      page.waitForEvent("dialog", { timeout: 10_000 }).then(async (dialog) => {
        expect(dialog.type()).toBe("confirm");
        await dialog.accept();
      }),
      deleteButton.click(),
    ]);
    await expect(setPicker).toBeHidden({ timeout: 10_000 });
  }
}

// Select the practice-lesson dropdown option whose visible text matches the
// pattern. Seed lesson titles carry a random suffix (e.g. "Coding Tools b27f54"),
// so selectOption({ label }) — an exact-string match — can never hit. Read the
// real options, match by regex (must match exactly one), then select by the
// matched option's value attribute. No hardcoded suffix, no index guessing.
async function selectPracticeLesson(panel: Locator, pattern: RegExp): Promise<void> {
  const select = panel.getByLabel("练习课节");
  const options = await select.locator("option").evaluateAll((elements) =>
    elements.map((element) => ({
      value: (element as HTMLOptionElement).value,
      label: (element.textContent ?? "").trim(),
    })),
  );
  const matches = options.filter((option) => pattern.test(option.label));
  if (matches.length !== 1) {
    const candidates = options.map((option) => option.label).join(" | ");
    throw new Error(
      `练习课节 selector for /${pattern.source}/ matched ${matches.length} option(s); candidates: ${candidates}`,
    );
  }
  await select.selectOption({ value: matches[0].value });
}

// Slice 2B Batch B packet §5: the practice language selector defaults to
// ["python"], so merely checking Java/C++ leaves Python selected and the
// generator may emit a Python coding item. Drive each language checkbox to the
// exact desired state so ONLY the target language is selected, independent of
// the component default. Real UI interaction only — no force click / JS click.
async function selectOnlyCodingLanguage(panel: Locator, language: "Java" | "C++") {
  const languages = ["Python", "Java", "C++"] as const;
  for (const candidate of languages) {
    const checkbox = panel.getByRole("checkbox", { name: candidate, exact: true });
    const shouldBeChecked = candidate === language;
    if (shouldBeChecked === (await checkbox.isChecked())) continue;
    await (shouldBeChecked ? checkbox.check() : checkbox.uncheck());
  }
}

async function generateCodingSet(panel: Locator, language: "Java" | "C++") {
  await panel.getByLabel("题数").fill("1");
  await panel.getByLabel("题型").selectOption({ label: "要求编程题" });
  await panel.getByRole("checkbox", { name: /允许使用自托管代码执行工具验证编程题/ }).check();
  await selectOnlyCodingLanguage(panel, language);
  await panel.getByRole("checkbox", { name: /我同意将本课节相关资料发送给外部 AI 模型/ }).check();
  await panel.getByRole("button", { name: /生成练习/ }).click();
}

async function fillCodeEditor(page: Page, text: string) {
  const editor = page.locator(".practice-code-editor .cm-content").first();
  await editor.click();
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Delete");
  await page.keyboard.type(text);
}

// Full Java/C++ path: generate -> answer -> grade -> run record (packet §8.1).
async function fullCodingPath(page: Page, request: APIRequestContext, stub: string,
                              lesson: RegExp, language: "Java" | "C++", correct: string) {
  await resetAll(request, stub);
  const panel = await openPracticeForLesson(page, lesson);
  await generateCodingSet(panel, language);
  // The code toolbar (practice-code-toolbar > strong) renders only after the
  // set is generated, and names the emitted item's language. Asserting it
  // verifies the artifact language matches the target exactly (packet §5) and
  // also waits for generation to complete before filling the editor.
  await expect(panel.locator(".practice-code-toolbar").getByText(language, { exact: true })).toBeVisible({ timeout: 40_000 });

  await fillCodeEditor(page, correct);
  const consent = page.getByRole("checkbox", { name: /我同意将本次答卷和必要的评分资料发送给配置的外部模型/ });
  if (await consent.isVisible({ timeout: 3_000 }).catch(() => false)) await consent.check();
  await panel.getByRole("button", { name: /交卷/ }).click();

  await expect(panel.getByText(/100\s*分/)).toBeVisible({ timeout: 40_000 });
  await page.getByRole("tab", { name: "运行记录" }).click();
  await expect(page.getByRole("button", { name: /练习生成.*成功/ })).toBeVisible({ timeout: 20_000 });
}

test("Java practice: generate, answer, grade and run record", async ({ page, request }) => {
  await fullCodingPath(page, request, "practice_java_success", /Coding Tools/, "Java", CORRECT_JAVA);
});

test("C++ practice: generate, answer, grade and run record", async ({ page, request }) => {
  await fullCodingPath(page, request, "practice_cpp_success", /Coding Tools/, "C++", CORRECT_CPP);
});

test("scientific practice Wolfram required: tool is called and the set publishes", async ({ page, request }) => {
  await resetAll(request, "practice_science_wolfram_required");
  expect(await wolframCalls(request)).toBe(0);
  const panel = await openPracticeForLesson(page, /Science Tools/);
  await panel.getByLabel("题数").fill("1");
  await panel.getByLabel("题型").selectOption({ label: "要求科学计算题" });
  await panel.getByRole("checkbox", { name: /允许将必要的科学计算表达式发送给 Wolfram 验证/ }).check();
  await panel.getByRole("checkbox", { name: /我同意将本课节相关资料发送给外部 AI 模型/ }).check();
  await panel.getByRole("button", { name: /生成练习/ }).click();
  await expect(panel.getByPlaceholder(/写出完整解答过程/)).toBeVisible({ timeout: 40_000 });
  expect(await wolframCalls(request)).toBeGreaterThanOrEqual(1);
});

test("scientific practice negative: zero Wolfram calls even when authorized", async ({ page, request }) => {
  await resetAll(request, "practice_science_negative");
  expect(await wolframCalls(request)).toBe(0);
  const panel = await openPracticeForLesson(page, /Science Tools/);
  await panel.getByLabel("题数").fill("1");
  await panel.getByLabel("题型").selectOption({ label: "要求科学计算题" });
  await panel.getByRole("checkbox", { name: /允许将必要的科学计算表达式发送给 Wolfram 验证/ }).check();
  await panel.getByRole("checkbox", { name: /我同意将本课节相关资料发送给外部 AI 模型/ }).check();
  await panel.getByRole("button", { name: /生成练习/ }).click();
  await expect(panel.getByPlaceholder(/写出完整解答过程/)).toBeVisible({ timeout: 40_000 });
  expect(await wolframCalls(request)).toBe(0);
});
