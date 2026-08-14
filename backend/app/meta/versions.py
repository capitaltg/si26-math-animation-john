# Bump when a stored plan's schema or compiled program can change, especially
# after edits in app/meta/dsl/* or app/meta/v3 compiler/expansion code. Existing
# validation reports must become stale when the current compiler would produce
# or accept a different program.
DSL_COMPILER_VERSION = 15

# Bump when measured bounds or rendered pixels can change, especially after
# edits in dynamic_scene.py, manim_primitives/*, or v3 renderer, layout,
# visual-registry, and measurement code. Existing previews and quality reports
# must become stale when they no longer describe the frame that will render.
DYNAMIC_RENDERER_VERSION = 14
