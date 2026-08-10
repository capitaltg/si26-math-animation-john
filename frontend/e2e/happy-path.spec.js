import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures',
  'known-good.pptx',
)

test('upload known-good deck surfaces candidates in the UI', async ({ page }) => {
  // Discovery invokes Bedrock. Enable this test by setting either
  // MATH_ANIM_MOCK_BEDROCK=1 (once the backend hook lands — Phase B) or by
  // providing live AWS credentials to the backend the playwright config boots.
  test.skip(
    !process.env.MATH_ANIM_MOCK_BEDROCK && !process.env.AWS_ACCESS_KEY_ID,
    'happy-path calls Bedrock; enable when MATH_ANIM_MOCK_BEDROCK is set or AWS creds are configured',
  )
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
