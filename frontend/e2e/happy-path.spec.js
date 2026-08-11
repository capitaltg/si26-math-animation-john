import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures',
  'known-good.pptx',
)

test('upload known-good deck surfaces candidates in the UI', async ({ page }) => {
  // Discovery invokes Bedrock. The playwright config boots the backend
  // with MATH_ANIM_MOCK_BEDROCK=1, so `call_with_tool` routes to the
  // canned handler in app.pipeline.bedrock_mocks — no AWS creds needed.
  await page.goto('/demo')

  await expect(page.getByLabel(/upload a pptx/i)).toBeVisible()

  await page.setInputFiles('input[type="file"]', FIXTURE)
  await page.getByRole('button', { name: /^upload$/i }).click()

  await expect(
    page.getByRole('heading', { name: /problems found in your deck/i }),
  ).toBeVisible({ timeout: 30_000 })

  await expect(page.locator('.picklist .pick').first()).toBeVisible()
  await expect(page.locator('.upload__error')).toHaveCount(0)
})
