import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

// Focus + render + toast are covered by unit + component tests
// (Focus.test.jsx, RenderToast.test.jsx). E2E stops at "candidates
// surfaced" because backend/app/pipeline/bedrock_mocks.py only mocks
// discovery; classify_problem/extract_params are needed for /options
// and would be a separate follow-up.

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures', 'known-good.pptx',
)

test('landing routes to demo, upload surfaces candidates', async ({ page }) => {
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: /verified animation for every math slide/i }),
  ).toBeVisible()

  await page.getByRole('link', { name: /try the demo/i }).first().click()
  await expect(page).toHaveURL(/\/demo$/)
  await expect(page.getByLabel(/upload a pptx/i)).toBeVisible()

  await page.setInputFiles('input[type="file"]', FIXTURE)
  await page.getByRole('button', { name: /^upload$/i }).click()

  await expect(
    page.getByRole('heading', { name: /problems found in your deck/i }),
  ).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.picklist .pick').first()).toBeVisible()
})
