# Brand assets

Home Assistant does not serve integration icons from the integration repository.
They live in the central [home-assistant/brands](https://github.com/home-assistant/brands)
repository and are served from `https://brands.home-assistant.io/`.

The files in this folder are staged here only for convenience. To make the icon
appear in Home Assistant and HACS for this integration (domain `stagg_ekg_plus`),
submit them to the brands repo:

1. Fork https://github.com/home-assistant/brands
2. Copy `icon.png` (and optionally `logo.png`) to
   `custom_integrations/stagg_ekg_plus/` in your fork.
3. Open a pull request.

Brand asset requirements (summary):
- `icon.png`: 256x256, square, PNG.
- `[email protected]` (optional): 512x512 hDPI variant.
- `logo.png` (optional): wordmark, trimmed.
- Dark-mode variants are auto-generated if not supplied.

These assets are the Fellow brand mark, taken from the existing
`fellow_stagg_ekg_pro` brands entry (Fellow Stagg EKG Pro integration by
@cermakjn). They represent the Fellow brand and are reused here for the Fellow
Stagg EKG+.
