import { expect, test } from "@playwright/test";

test("Tutor flow reaches an answer and its run record", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("HelloAgents Learn")).toBeVisible();

  await page.getByRole("button", { name: /System Tutor Browser/ }).click();
  const course = page.getByRole("button", { name: /Algorithms/ });
  await expect(course).toBeVisible({ timeout: 20_000 });
  const [courseResponse] = await Promise.all([
    page.waitForResponse((response) =>
      /\/api\/v1\/workspaces\/[^/]+\/courses\/[^/?]+$/.test(
        new URL(response.url()).pathname,
      ),
    ),
    course.click(),
  ]);
  expect(
    courseResponse.ok(),
    `course request failed: ${courseResponse.status()} ${await courseResponse.text()}`,
  ).toBeTruthy();
  await expect(page.getByRole("heading", { name: "Algorithms" })).toBeVisible({
    timeout: 20_000,
  });
  const [readerResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/reader")),
    page.getByRole("button", { name: "阅读", exact: true }).click(),
  ]);
  expect(
    readerResponse.ok(),
    `reader request failed: ${readerResponse.status()} ${await readerResponse.text()}`,
  ).toBeTruthy();

  const tutor = page.getByRole("complementary", { name: "课程 Tutor" });
  await expect(tutor).toBeVisible({ timeout: 20_000 });
  await tutor.getByPlaceholder("输入问题").fill(
    "Why can binary search discard half of a sorted interval?",
  );
  // The first submit must open the external-model confirmation dialog. Wait for
  // it in sync with the click and assert it really appeared — a once-listener
  // that never fires would let a missing dialog pass silently. The wait is
  // consumed by this click, so no dialog handler leaks past the action
  // (packet Fix 7).
  await Promise.all([
    page.waitForEvent("dialog", { timeout: 10_000 }).then(async (dialog) => {
      expect(dialog.type()).toBe("confirm");
      await dialog.accept();
    }),
    tutor.getByRole("button", { name: "发送" }).click(),
  ]);

  await expect(
    tutor.getByText("Binary search halves the remaining sorted interval."),
  ).toBeVisible({ timeout: 30_000 });
  await expect(tutor.getByText("succeeded")).toBeVisible();

  await page.getByRole("tab", { name: "运行记录" }).click();
  await expect(
    page.getByRole("button", { name: /本课辅导.*成功/ }),
  ).toBeVisible();
});
