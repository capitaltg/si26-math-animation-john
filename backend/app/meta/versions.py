# Bumped by hand whenever a human changes the DSL compilers (app/meta/dsl/*)
# or the dynamic renderer (app/meta/dynamic_scene.py, app/meta/manim_primitives/*).
# Included in every draft's artifact hash (spec §4) so a compiler/renderer
# change invalidates previously-computed hashes rather than silently reusing
# stale validation results.
# 4: `FieldRefNode.item_field` addresses a scalar inside an array item, and
#    compilation receives field shapes (`FieldContract`) rather than bare names,
#    so an array reference missing an index or item field is rejected at compile
#    time instead of failing as `unsupported_type: <class 'dict'>` at evaluation.
DSL_COMPILER_VERSION = 4
# 4: `rectangle_measurement` draws its length and width; vertex anchors and
#    `object_set` render at all; label text carries the layout scale; a
#    supporting visual too wide to sit beside the primary takes its own row.
DYNAMIC_RENDERER_VERSION = 4
