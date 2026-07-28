# Full Card Hover Previews

## Summary

Add a full printed-card preview whenever any card link is hovered or keyboard-focused. Images load lazily from Scryfall, clicks continue opening Card Detail, and no tracker or database changes are required.

## Implementation

- Add `@floating-ui/react` and build a reusable preview around `CardLink` using hover, focus, viewport collision handling, and a portal so previews are not clipped by tables or sections. These interaction and positioning primitives are provided by [Floating UI's React APIs](https://floating-ui.com/docs/react).
- Display Scryfall's full `normal` card image rather than the current `art_crop`, using the clean card name already supplied to each link.
- Delay opening approximately 180 ms so moving across a table does not request every image. Close shortly after pointer exit and immediately on blur or Escape.
- Position the preview beside the link, automatically flipping left/right and shifting vertically to remain inside the viewport.
- Use a responsive card-sized panel around 260-300px wide, with light/dark-compatible border, shadow, loading state, and image-failure fallback.
- Extend `CardLink` to accept normal anchor properties so card-search results can reuse it without losing `role="option"`, selection state, click handlers, or existing CSS.
- Apply previews to Timeline references, opening hands, drawn/played-card tables, deck analytics, dashboard card tables, and card-search results.
- Preserve return-aware Timeline links exactly as they work now.
- Do not preview on touch-only hover events; tapping continues directly to Card Detail.

## Image Loading

- Generate the Scryfall image URL client-side from the clean card name and use `format=image&version=normal`.
- Mount the image only after the hover/focus delay; rely on browser caching for repeat previews.
- Remember failed URLs for the current session to avoid repeated failed requests.
- Do not add persistent files, image proxying, bulk downloads, or schema fields.
- Lazy loading and the hover delay keep normal usage below Scryfall's published request guidance; Scryfall asks API users to remain under ten requests per second. [Scryfall API guidance](https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17)

## Test Plan

- Verify hovering and keyboard focus display the full card preview.
- Verify pointer exit, blur, and Escape dismiss it.
- Verify no image is requested or mounted before interaction.
- Verify names containing spaces, punctuation, apostrophes, and split-card separators produce valid URLs.
- Verify clicking still navigates to Card Detail and Timeline return parameters remain intact.
- Verify card-search options retain their ARIA roles and click behavior.
- Verify failed images show the fallback and are not repeatedly requested.
- Run frontend tests, lint, production build, and inspect desktop/mobile positioning in both themes.

## Assumptions

- "Actual card" means the complete printed card image, including rules text and frame.
- Every existing card link receives the preview.
- Scryfall access is acceptable; offline previews are out of scope for this version.
- No Python API, tracker process, database migration, or historical-data update is needed.
