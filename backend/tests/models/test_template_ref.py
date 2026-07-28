import pytest
from pydantic import ValidationError


def test_template_ref_round_trips_through_json():
    from app.models.scene import TemplateName, TemplateRef

    ref = TemplateRef(
        name=TemplateName.NUMBER_LINE, version_id="1", artifact_hash="sha256:abc"
    )
    restored = TemplateRef.model_validate_json(ref.model_dump_json())
    assert restored == ref


def test_template_ref_rejects_an_unknown_template_name():
    from app.models.scene import TemplateRef

    with pytest.raises(ValidationError):
        TemplateRef(name="hologram", version_id="1", artifact_hash="sha256:abc")


def test_template_ref_equality_is_by_value():
    from app.models.scene import TemplateName, TemplateRef

    a = TemplateRef(name=TemplateName.NUMBER_LINE, version_id="1", artifact_hash="sha256:abc")
    b = TemplateRef(name=TemplateName.NUMBER_LINE, version_id="1", artifact_hash="sha256:abc")
    c = TemplateRef(name=TemplateName.NUMBER_LINE, version_id="2", artifact_hash="sha256:abc")
    assert a == b
    assert a != c


def test_template_ref_cannot_be_mutated_after_validation():
    from app.models.scene import TemplateName, TemplateRef

    ref = TemplateRef(
        name=TemplateName.NUMBER_LINE, version_id="1", artifact_hash="sha256:abc"
    )
    with pytest.raises(ValidationError):
        ref.version_id = "2"


def test_template_artifact_mismatch_error_is_an_exception():
    from app.models.scene import TemplateArtifactMismatchError, TemplateVersionMismatchError

    assert issubclass(TemplateArtifactMismatchError, Exception)
    assert issubclass(TemplateVersionMismatchError, Exception)
