// Vite dev-server proxy. Loaded by vite.config.js in Node during config
// evaluation, so `process.env` is available.
//
// VITE_BACKEND_URL overrides the target so the same file works for both:
//   * bare-metal dev — backend runs on the host at http://localhost:8000
//     (the default)
//   * docker-compose dev overlay — backend is the sibling service
//     `backend:8000` on the internal network; docker-compose.dev.yml sets
//     VITE_BACKEND_URL=http://backend:8000 in the frontend-dev container.
const target = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

export const developmentProxy = {
  '/upload': target,
  '/options': target,
  '/storyboard': target,
  '/render': target,
  '/clips': target,
  '/thumbnails': target,
  '/meta': target,
}
