# Unified Development Command Design

## Goal

Make `./scripts/run-dev.sh` start every process needed for the normal
application and the dev-only meta-template demo: FastAPI, the Vite frontend,
and the standalone meta-template worker.

## Existing Context

`scripts/run-dev.sh` currently starts `run-backend.sh` in the background and
keeps `run-frontend.sh` in the foreground. Its exit trap kills only the backend.
The meta-template worker is now a complete standalone process, but the README
still requires starting it in a third terminal.

## Chosen Design

Add `scripts/run-meta-worker.sh`, following the existing backend launcher:

- resolve the repository root relative to the script;
- require the repository-root virtualenv and its Python executable;
- add LaTeX and Homebrew tools to `PATH`;
- change into `backend`;
- `exec` `python -m scripts.meta_worker`.

Update `scripts/run-dev.sh` to:

1. start `run-backend.sh` in the background;
2. start `run-meta-worker.sh` in the background;
3. run `run-frontend.sh` in the foreground;
4. on frontend exit, Ctrl-C, or termination, send termination to both
   background processes and wait for them before exiting.

When meta-template flags are disabled, the worker's existing feature gate exits
successfully and normal development continues. `run-dev.sh` will not duplicate
feature-flag checks or worker logic.

The frontend remains the foreground process because it preserves the current
interactive Vite output and exit behavior.

## Alternatives Considered

1. **Run the worker inside FastAPI:** rejected because Uvicorn reloads or
   multiple web workers can create duplicate worker processes and couple slow
   generation lifecycle to HTTP serving.
2. **Add a process manager such as `concurrently`:** rejected because three
   shell-managed local processes do not justify a new dependency.
3. **Inline the worker command in `run-dev.sh`:** workable, but rejected because
   a dedicated launcher keeps environment/path checks reusable and consistent
   with the existing backend/frontend launchers.

## Process Lifecycle and Errors

The cleanup function tolerates a child that already exited. It sends
termination to every recorded background PID, then waits for each PID so the
combined command does not leave orphaned backend or worker processes.

If backend or worker startup fails independently, its own launcher prints the
configuration error. As with the current script, Vite remains the foreground
process until it exits; production-grade process supervision is outside this
local-development scope.

## Tests

A pytest integration test will copy `run-dev.sh` into a temporary directory
beside fake backend, worker, and frontend launchers. The fakes record startup
and termination events. The test will prove:

- all three launchers run;
- frontend completion triggers cleanup;
- both background processes receive termination;
- `run-dev.sh` waits for cleanup before returning.

Shell syntax checks will cover all three real launch scripts. The existing
worker tests, complete backend/frontend suites, and frontend production build
will also run before merge and again on merged `main`.

## Documentation

The README meta-template demo will use `./scripts/run-dev.sh` as the default
startup command. Separate process commands will remain documented as an
optional troubleshooting path.
