# Expression DSL
MAX_EXPRESSION_DEPTH = 6
MAX_EXPRESSION_OPERATIONS = 20
MAX_NUMERIC_MAGNITUDE = 10**12

# Guard DSL
MAX_GUARD_PREDICATES = 20
MAX_PREDICATE_TERMS = 6
# `ordered` constrains a whole displayed collection, so it needs a term per item.
# `OrderedValuesVisual.values` accepts up to 15 and `pair_elimination` depends on
# that collection being sorted; capping this at MAX_PREDICATE_TERMS (a bound meant
# for arithmetic predicates) left a median of seven unable to state its own
# precondition, and the tool schema rejected the whole draft.
MAX_ORDERED_TERMS = 15

# Params DSL
MAX_PARAMS_FIELDS = 20
MAX_ARRAY_ITEMS = 12
MAX_STRING_LENGTH = 200
MAX_ENUM_CHOICES = 16

# Animation DSL
MAX_ANIMATION_NODES = 60
MAX_ANIMATION_DEPTH = 8
MAX_LABEL_TEXT_LENGTH = 80
MAX_ANIMATION_STEPS = 40
MAX_TOTAL_DURATION_SECONDS = 30.0

# v3 teaching-plan contracts
MIN_PLAN_BEATS = 3
MAX_PLAN_BEATS = 5
MIN_SCENE_SECONDS = 6.0
MAX_SCENE_SECONDS = 12.0
MIN_ACTION_SECONDS = 0.15
MAX_ACTION_SECONDS = 2.0
MAX_SIMPLE_STAGGER_SECONDS = 0.15
MIN_CONCLUSION_HOLD_SECONDS = 1.5
