// Runs on the HOST before VS Code / Cursor's Dev Containers extension
// starts compose. Its only job: make sure `.env` exists so Postgres has a
// non-empty POSTGRES_PASSWORD (Postgres refuses to boot otherwise) and
// backend/meta-worker have their DATABASE_URL/AWS_* etc. interpolated
// values.
//
// Node is used instead of shell one-liners because devcontainer's
// `initializeCommand` runs against the host's native shell — POSIX `test`
// and `cp` are absent on Windows PowerShell / cmd.exe, and PowerShell
// cmdlets don't exist on macOS/Linux. Node is required by the project
// anyway (the frontend needs it), so this adds no extra prerequisite.
//
// Idempotent: does nothing when .env already exists.

import { copyFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const envPath = resolve(repoRoot, '.env')
const examplePath = resolve(repoRoot, '.env.docker.example')

if (existsSync(envPath)) {
  console.log('[devcontainer/init] .env already present — leaving alone')
  process.exit(0)
}

if (!existsSync(examplePath)) {
  console.error(`[devcontainer/init] missing ${examplePath}; cannot bootstrap .env`)
  process.exit(1)
}

copyFileSync(examplePath, envPath)
console.log('[devcontainer/init] created .env from .env.docker.example')
console.log('[devcontainer/init] this uses the shipped dev default password; rotate before going public (see docs/DEPLOY.md)')
