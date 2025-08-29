Vendored assets
================

This folder holds local copies of third‑party browser assets used by the web UI.

Leaflet
-------

The app is configured to load Leaflet from `vendor/leaflet/leaflet.css` and
`vendor/leaflet/leaflet.js` to avoid CDN/network issues.

Populate these files by manually downloading Leaflet v1.9.4 (or compatible)
from the official distribution and placing assets here:

- `web/vendor/leaflet/leaflet.css`
- `web/vendor/leaflet/leaflet.js`
- `web/vendor/leaflet/images/marker-icon.png`
- `web/vendor/leaflet/images/marker-icon-2x.png`
- `web/vendor/leaflet/images/marker-shadow.png`

Note: The Leaflet CSS expects images relative to the CSS file at
`vendor/leaflet/images/`.
