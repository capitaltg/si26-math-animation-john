# Inline Render Video Design

## Goal

Allow users to watch successfully rendered animation clips directly on the
results page while retaining the existing option to download each MP4.

## Scope

This change is limited to the frontend results view and its documentation. The
backend already serves each registered clip from `/clips/{clip_id}` with the
`video/mp4` media type, so the existing `clip_url` is suitable for both inline
playback and download.

## User Experience

Each result with a non-null `clip_url` displays:

1. A native HTML video player with browser-provided controls.
2. The existing download link beneath the player.

The player does not autoplay. It uses `preload="metadata"` so the browser can
discover duration and dimensions without eagerly downloading the entire clip.
Its width is constrained to the result container while preserving the video's
aspect ratio.

Fallback renders remain playable and continue showing their fallback reason.
Failed renders continue showing the current explicit failure message and do not
display a player or download link.

## Architecture And Data Flow

No API or persistence changes are required:

1. `POST /render` continues returning each completed result's `clip_url`.
2. The React results view passes that URL to the video's `src`.
3. The existing download anchor uses the same URL with its `download`
   attribute.
4. `GET /clips/{clip_id}` continues returning the MP4 response.

The browser decides whether to stream the URL through the video element or save
it through the download anchor.

## Error Handling

The existing render-result branches remain authoritative:

- `status === "error"` shows the failure message.
- A non-null `clip_url` shows playback and download controls.
- A result without either condition keeps the existing generic clip label.

Native video loading failures are left to the browser's player UI. Adding a
custom retry or playback error state is outside this change's scope.

## Testing

Add a frontend component test that completes the existing render workflow and
asserts:

- A video element is present after a successful render.
- The video's source is the returned `clip_url`.
- The download link remains present and uses the same URL.

Existing tests continue covering failed render messaging, fallback messaging,
navigation away from results, and the render workflow. Run the full frontend
test suite and production build after implementation.

## Documentation

Update the README overview and usage instructions so they describe inline
playback as well as downloading rendered clips.
