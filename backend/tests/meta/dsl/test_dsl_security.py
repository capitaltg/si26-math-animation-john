import ast
import inspect

import pytest
from pydantic import BaseModel
from pydantic import ValidationError

from app.meta import dynamic_scene as dynamic_scene_module
from app.meta.dsl import animation as animation_module
from app.meta.dsl import expression as expression_module
from app.meta.dsl import guard as guard_module
from app.meta.dsl import params as params_module
from app.meta.dsl import scene_program as scene_program_module
from app.meta.dsl import teaching_plan as teaching_plan_module
from app.meta.manim_primitives import layout as layout_module
from app.meta.manim_primitives import motions as motions_module
from app.meta.manim_primitives import style as style_module
from app.meta.manim_primitives import visuals as visuals_module
from app.meta.dsl.animation import AnimationDocument, LabelNode, WaitNode, compile_animation_document
from app.meta.dsl.errors import DslValidationError
from app.meta.dsl.expression import AddNode, FieldRefNode, LiteralNode, compile_expression
from app.meta.dsl.guard import GuardDocument, PositivePredicate
from app.meta.dsl.params import IntegerFieldSpec, ParamsDocument


DANGEROUS_STRINGS = ["__import__('os')", "os.system('rm -rf /')", "eval('1+1')", "../../etc/passwd", "https://evil.example.com"]


@pytest.mark.parametrize(
    "module",
    [
        animation_module,
        expression_module,
        guard_module,
        params_module,
        teaching_plan_module,
        scene_program_module,
        dynamic_scene_module,
        style_module,
        layout_module,
        visuals_module,
        motions_module,
    ],
)
def test_no_eval_exec_or_dynamic_import_in_dsl_modules(module):
    source = inspect.getsource(module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("eval", "exec", "compile", "__import__")
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            pytest.fail(f"{module.__name__} imports importlib")


@pytest.mark.parametrize("module", [teaching_plan_module, scene_program_module])
def test_v3_contract_models_forbid_extra_fields(module):
    models = [
        model for _, model in inspect.getmembers(module, inspect.isclass)
        if issubclass(model, BaseModel) and model.__module__ == module.__name__
    ]
    assert models
    assert all(model.model_config.get("extra") == "forbid" for model in models)


@pytest.mark.parametrize("dangerous", DANGEROUS_STRINGS)
def test_label_text_accepts_but_never_executes_dangerous_strings(dangerous):
    node = LabelNode(text=dangerous[:80])
    assert node.text == dangerous[:80]  # stored as inert text, never interpreted


def test_unknown_top_level_key_rejected_in_every_document():
    with pytest.raises(ValidationError):
        ParamsDocument.model_validate({"params_version": 1, "fields": [], "sneaky": True})
    with pytest.raises(ValidationError):
        GuardDocument.model_validate({"guard_version": 1, "predicates": [], "sneaky": True})
    with pytest.raises(ValidationError):
        AnimationDocument.model_validate({"animation_version": 1, "root": {"kind": "wait", "seconds": 1}, "sneaky": True})


def test_empty_fields_or_predicates_rejected():
    with pytest.raises(ValidationError):
        ParamsDocument(params_version=1, fields=[])
    with pytest.raises(ValidationError):
        GuardDocument(guard_version=1, predicates=[])


def test_expression_depth_bomb_rejected_not_stack_overflow():
    node = LiteralNode(value=1)
    for _ in range(1000):
        node = AddNode(operands=[node, LiteralNode(value=1)])
    with pytest.raises(DslValidationError):
        compile_expression(node, known_fields=frozenset())


def test_animation_node_count_bomb_rejected():
    from app.meta.dsl.animation import RowNode

    # 8 children max per row/column per schema; nest rows to build a large-but-schema-valid tree
    # and confirm the compiler's node-count walk (not just per-node schema limits) catches it.
    inner = WaitNode(seconds=0.1)
    for _ in range(20):
        inner = RowNode(children=[inner] + [LabelNode(text="x") for _ in range(7)])
    document = AnimationDocument(animation_version=1, root=inner)
    with pytest.raises(DslValidationError) as exc:
        compile_animation_document(document, known_fields=frozenset())
    assert exc.value.code in ("too_many_nodes", "animation_too_deep")


def test_guard_predicate_field_ref_cannot_name_arbitrary_python_attribute():
    with pytest.raises(ValidationError):
        FieldRefNode(field="__class__")
    with pytest.raises(ValidationError):
        FieldRefNode(field="os.system")
