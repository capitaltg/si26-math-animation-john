from types import SimpleNamespace
from unittest.mock import Mock

from scripts import meta_worker


def test_worker_immediately_checks_again_after_producing_a_draft():
    process_one = Mock(side_effect=[SimpleNamespace(id="draft-1"), KeyboardInterrupt])
    wait = Mock()

    try:
        meta_worker.run_worker(
            owner="demo-worker",
            process_one=process_one,
            wait=wait,
            poll_interval=0.25,
        )
    except KeyboardInterrupt:
        pass

    assert process_one.call_count == 2
    wait.assert_not_called()


def test_worker_waits_after_an_idle_iteration():
    process_one = Mock(side_effect=[None, KeyboardInterrupt])
    wait = Mock()

    try:
        meta_worker.run_worker(
            owner="demo-worker",
            process_one=process_one,
            wait=wait,
            poll_interval=0.25,
        )
    except KeyboardInterrupt:
        pass

    wait.assert_called_once_with(0.25)


def test_worker_contains_unexpected_errors_and_waits(caplog, monkeypatch):
    process_one = Mock(side_effect=[RuntimeError("boom"), KeyboardInterrupt])
    wait = Mock()
    # Manim's in-process logging setup disables pre-existing non-Manim loggers.
    # Keep this assertion independent of whether a Manim test ran before it.
    monkeypatch.setattr(meta_worker.logger, "disabled", False)

    try:
        meta_worker.run_worker(
            owner="demo-worker",
            process_one=process_one,
            wait=wait,
            poll_interval=0.25,
        )
    except KeyboardInterrupt:
        pass

    wait.assert_called_once_with(0.25)
    assert "Unexpected meta worker iteration failure" in caplog.text


def test_main_exits_without_polling_when_feature_is_disabled(monkeypatch):
    run_worker = Mock()
    monkeypatch.setattr(
        meta_worker,
        "get_settings",
        lambda: SimpleNamespace(
            meta_templates_enabled=False,
            meta_codegen_enabled=True,
        ),
    )
    monkeypatch.setattr(meta_worker, "run_worker", run_worker)

    assert meta_worker.main() == 0
    run_worker.assert_not_called()


def test_main_exits_without_polling_when_codegen_is_disabled(monkeypatch):
    run_worker = Mock()
    monkeypatch.setattr(
        meta_worker,
        "get_settings",
        lambda: SimpleNamespace(
            meta_templates_enabled=True,
            meta_codegen_enabled=False,
        ),
    )
    monkeypatch.setattr(meta_worker, "run_worker", run_worker)

    assert meta_worker.main() == 0
    run_worker.assert_not_called()


def test_main_turns_keyboard_interrupt_into_clean_exit(monkeypatch):
    monkeypatch.setattr(
        meta_worker,
        "get_settings",
        lambda: SimpleNamespace(
            meta_templates_enabled=True,
            meta_codegen_enabled=True,
        ),
    )
    monkeypatch.setattr(
        meta_worker,
        "run_worker",
        Mock(side_effect=KeyboardInterrupt),
    )

    assert meta_worker.main() == 0
