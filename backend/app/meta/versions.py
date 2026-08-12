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
#    `CoordinatePlaneVisual` also gains an optional `grid` field, so a plan
#    that requests grid lines cannot be validated against a version-7
#    compiler that would reject the extra field.
# 9: `dsl/teaching_plan.py` gains the `data_display` visual kind (one kind with
#    a `display_style` variant selector for bar_graph / line_plot / dot_plot /
#    histogram / box_plot) and the matching `DataDisplayProgramVisual` in
#    `dsl/scene_program.py`. A version-8 compiler cannot deserialize the new
#    kind, so a report stamped 8 that references a data_display draft must not
#    be trusted as current.
# 10: `dsl/teaching_plan.py` gains two strategies for MCAP 6.EE / 7.EE
#    archetypes: `inverse_operation` on `bar` (one-/two-step equation solving
#    on a tape-diagram bar), and `ray_shade` on `number_line` (an inequality's
#    boundary + shaded ray). A version-9 compiler rejects the new strategy
#    literals as unknown enum values, so a plan authored against version 10
#    cannot be re-validated by a stale runtime.
# 11: `BarVisual` gains optional `constant` and `coefficient` fields and
#    `NumberLineVisual` gains `boundary`, `boundary_kind`, `ray_direction` --
#    all required by `inverse_operation` and `ray_shade` respectively. The
#    compiler now stages the equation partition (constant_region + x_region
#    + x_parts) and the inequality's boundary circle + shaded ray on the
#    beats naming primary; a version-10 compiler rejects the new fields as
#    unknown, so a plan authored against version 11 cannot be re-validated.
# 12: `signed_hop` and `distance_from_zero` strategies join `number_line` (M6).
#    magnitude_comparison now refuses a number_line whose minimum is negative
#    or whose markers include negatives, so a report stamped 11 that accepted
#    such a plan misrepresents the current gate; a version-11 compiler also
#    rejects the two new strategy literals outright.
# 13: `dsl/teaching_plan.py` gains `equivalence_align` and
#    `common_denominator_bridge` strategies on `partition`. The compiler
#    requires the matching supporting partition(s) (one for equivalence,
#    two for the bridge) and the quality gate rejects a plan whose
#    supporting partitions never reveal -- a version-12 compiler would
#    reject the new strategy literals, and a version-12 report on a plan
#    that uses them cannot be trusted as current.
# 14: `dsl/teaching_plan.py` and `app/meta/v3/compiler.py` gain the
#    `percent_of_whole` and `percent_change` strategies on `bar` (M9). A
#    version-13 compiler rejects the new strategy literals; and its
#    `magnitude_comparison` on a percent-semantic bar (`maximum == 100`)
#    would be accepted where a version-14 compiler now refuses it, so a
#    report stamped 13 for a plan that is percent-semantic must not be
#    trusted as current.
# 15: `dsl/teaching_plan.py` gains the `rotation` strategy on `coordinate_plane`
#    (M22). `CoordinatePlaneVisual` gains optional `polygons`, `pivot`,
#    `rotation_angle_deg`, `rotation_iterations` fields; `CoordinatePlane
#    ProgramVisual` gains a frozen `rotation_frames` payload; a new
#    `RotateAction` joins `ProgramAction`. A version-14 compiler rejects the
#    new strategy literal and unknown fields, so a plan authored against
#    version 15 cannot be re-validated by a stale runtime.
DSL_COMPILER_VERSION = 15
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
# 8: `coordinate_plane` draws optional grid lines, honours per-point
#    `label_dx`/`label_dy` quadrant offsets, and skips tick labels the
#    measurer suppressed to avoid a collision -- a version-7 renderer paints
#    every point label above its dot and every tick label unconditionally,
#    which would put glyphs on top of each other for the payloads a
#    version-8 measurer emits.
# 9: `data_display` renders as a new visual kind. A version-8 renderer cannot
#    build any of its five display styles, so an artifact stamped 8 that
#    carries a data_display must not be replayed.
# 10: `bar` draws partition dividers between the x_region and the constant_region
#    (plus per-x_part dividers when coefficient > 1) for `inverse_operation`
#    plans, and `number_line` builds an open/closed boundary circle and a
#    thick shaded ray for `ray_shade` plans. A version-9 renderer draws
#    neither primitive, so an artifact stamped 9 that references the new
#    payload keys must not be replayed.
# 11: `coordinate_plane` renders declared polygons, a pivot mark, and
#    one-step-per-iteration rotations against a persistent ghost trail. A
#    version-10 renderer cannot deserialize `RotateAction` or the
#    `rotation_frames` payload, so an artifact stamped 10 that references
#    either must not be replayed.
# 12: `coordinate_plane` axis tick numbers render at the smaller
#    `polygon_label` role (24pt) instead of `label` (36pt), and the
#    measurer sizes tick payloads at the same role. Tick label widths and
#    heights therefore shrink, which shifts the collision-driven thinning
#    stride and the point-label quadrant search, changing both the pixel
#    geometry a version-11 renderer would have produced and the layout
#    bounds a version-11 measurer would have reported. Approving a
#    version-11 report against a version-12 render would let a draft ship
#    with a preview and quality report that no longer describe the frame.
DYNAMIC_RENDERER_VERSION = 12
