# Bumped by hand whenever a human changes the DSL compilers (app/meta/dsl/*)
# or the dynamic renderer (app/meta/dynamic_scene.py, app/meta/manim_primitives/*).
# Included in every draft's artifact hash (spec §4) so a compiler/renderer
# change invalidates previously-computed hashes rather than silently reusing
# stale validation results.
DSL_COMPILER_VERSION = 1
DYNAMIC_RENDERER_VERSION = 1
