# Bumped by hand whenever a human changes the DSL compilers (app/meta/dsl/*)
# or the dynamic renderer (app/meta/dynamic_scene.py, app/meta/manim_primitives/*).
# Included in every draft's artifact hash (spec §4) so a compiler/renderer
# change invalidates previously-computed hashes rather than silently reusing
# stale validation results.
# 4: `FieldRefNode.item_field` addresses a scalar inside an array item, and
#    compilation receives field shapes (`FieldContract`) rather than bare names,
#    so an array reference missing an index or item field is rejected at compile
#    time instead of failing as `unsupported_type: <class 'dict'>` at evaluation.
# 5: a `pair_elimination` plan's primary collection is born `structure` and its
#    organize beat dims outside-in pairs to `neutral`, one timeline slot per
#    pair, paced at `min(1.3 x pairs, 6.0)` seconds; the plan carries no
#    `evaluated_answer` visual, and `answer_anchor` names the middle item that
#    the conclude beat's callout points at instead.
# 6: `dsl/teaching_plan.py` gains the `unit_tape` visual kind and the
#    `unit_substitution` strategy, and `dsl/scene_program.py` gains
#    `UnitTapeProgramVisual` -- a new frozen visual kind and strategy pairing
#    that did not previously compile.
# 7: `unit_rate` strategy joins `unit_tape`. The compiler stages a per-one
#    emphasis on box[0] on the reveal beat (preserving generic role changes
#    for other targets), rejects a plan whose tape value cannot be guaranteed
#    >= 1, and the quality gate rejects any active whole-tape focus through
#    the reveal so every column does not read as equally salient.
# 8: `dsl/teaching_plan.py` gains the `coordinate_plane` visual kind and the
#    matching `CoordinatePlaneProgramVisual` in `dsl/scene_program.py`; a
#    version-7 compiler does not know the new kind, so a report stamped 7 that
#    references a coordinate_plane draft must not be trusted as current.
DSL_COMPILER_VERSION = 8
# 4: `rectangle_measurement` draws its length and width; vertex anchors and
#    `object_set` render at all; label text carries the layout scale; a
#    supporting visual too wide to sit beside the primary takes its own row.
# 5: a visual is built in its declared `initial_role` rather than always
#    `neutral`, so a collection born `structure` renders blue and visibly
#    leaves that colour when it is dimmed.
# 6: `number_line` labels each marker with its value and reserves a strip
#    below the line for that label, so its measured height grows; and the
#    line itself is now drawn at its markers' y rather than at its
#    label-padded bounds' center, so it passes through its own dots again.
# 7: `coordinate_plane` renders as a new visual kind (axes through the
#    projected zero, plotted points with labels, whole-number ticks); a
#    version-6 dynamic renderer cannot deserialize the new frozen visual, so
#    an artifact stamped 6 that carries a coordinate_plane must not be
#    replayed.
DYNAMIC_RENDERER_VERSION = 7
