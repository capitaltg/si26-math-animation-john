import { test, expect } from '@playwright/test'

test('uploading a non-pptx file surfaces the backend rejection copy', async ({ page }) => {
  await page.goto('/demo')

  await page.setInputFiles('input[type="file"]', {
    name: 'not-a-deck.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('this is not a pptx'),
  })
  await page.getByRole('button', { name: /^upload$/i }).click()

  const alert = page.locator('.upload__error')
  await expect(alert).toBeVisible({ timeout: 15_000 })
  await expect(alert).toContainText(/\.pptx/i)

  await expect(
    page.getByRole('heading', { name: /problems found in your deck/i }),
  ).toHaveCount(0)
})
