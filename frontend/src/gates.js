export const GATES = {
  'Values extracted':           "The LLM read the problem text and pulled out the numbers and roles this template needs.",
  'Schema check':               "Every extracted value matches its expected type and range declared by the template's schema.",
  'Semantic check':             "Values are internally consistent: totals add up, ordering makes sense, references resolve — recomputed in Python, never the LLM.",
  'Compiled deterministically': "Scene program compiled from parameters with zero LLM involvement — same input, same output.",
  'Preview rendered':           "A first-frame preview rendered successfully with Manim + ffmpeg.",
  'Full render':                "The full clip rendered end-to-end and is ready to download.",
}
