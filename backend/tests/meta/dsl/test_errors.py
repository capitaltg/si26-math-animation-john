from app.meta.dsl.errors import DslValidationError


def test_error_carries_code_message_and_path():
    err = DslValidationError("unknown_field", "no such field", path="predicates[0].value")
    assert err.code == "unknown_field"
    assert err.message == "no such field"
    assert err.path == "predicates[0].value"
    assert "unknown_field" in str(err)
    assert "predicates[0].value" in str(err)


def test_error_path_optional():
    err = DslValidationError("overflow", "too big")
    assert err.path == ""
    assert "overflow" in str(err)
