// Copied from App.legacy.jsx: templates are stored as snake_case machine
// names ("number_line"); teachers should see plain words.
export function templateLabel(template) {
  return template.replace(/_/g, ' ')
}
