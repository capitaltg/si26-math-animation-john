import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures',
  'known-good.pptx',
)

test('upload known-good deck surfaces candidates in the UI', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /upload a deck/i })).toBeVisible()

  await page.setInputFiles('input[type="file"]', FIXTURE)
  await page.getByRole('button', { name: /^upload$/i }).click()

  await expect(
    page.getByRole('heading', { name: /problems found in your deck/i }),
  ).toBeVisible({ timeout: 30_000 })

  await expect(page.locator('.picklist .pick').first()).toBeVisible()
  await expect(page.locator('[role="alert"].notice--danger')).toHaveCount(0)
})
