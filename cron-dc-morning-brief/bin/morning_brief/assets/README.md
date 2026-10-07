# Packaged rendering assets

`bursawatch.svg` is the user-supplied Bursawatch brand mark, retained unchanged
from the supplied Downloads logo directory. It is used solely for this branded
renderer. The supplied mark does not establish rights to provider chart data.

`HankenGrotesk-400.ttf` and `HankenGrotesk-700.ttf` are static weight instances
retained from the approved local preview's Hanken Grotesk variable-font source.
The bundled `OFL.txt` is the official Hanken Grotesk SIL Open Font License 1.1,
retrieved from the Google Fonts source at
<https://github.com/google/fonts/blob/main/ofl/hankengrotesk/OFL.txt>.
Copyright belongs to the Hanken Grotesk Project Authors. The fonts may be
redistributed with this license, which must stay with the packaged assets.

The renderer records the exact SHA-256 of both fonts, the supplied SVG and the
license in every artifact manifest. These resources stay under `bin/` so the
package's ordinary source deployment can carry them together. No system font,
network asset resolver or guild operation is needed during composition.
