import { defineConfig, devices } from '@playwright/test'

const CI = !!process.env.CI

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: CI ? 1 : 0,
  reporter: CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: CI ? 'retain-on-failure' : 'off',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: [
    {
      command: '.venv/bin/python -m uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://localhost:8000/docs',
      reuseExistingServer: !CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: {
        // Route Bedrock calls to the canned-response stub in
        // app.pipeline.bedrock_mocks so the E2E smoke does not need
        // AWS credentials. Any tool call the stub does not know about
        // raises NotImplementedError, so silent drift is impossible.
        MATH_ANIM_MOCK_BEDROCK: '1',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
      url: 'http://localhost:5173',
      reuseExistingServer: !CI,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
