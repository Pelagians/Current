# Native welcome OCR controls

Unmodified OCR outputs from the fixed 1280×800 disposable UEFI VM evidence:

- `repaired-alma9.tsv`: `40012807977`, `source-first-run-0.png`; the repaired
  900×650 window exposes Additional scale options and native navigation.
- `clipped-fedora.tsv`: `40012823902`, `source-first-run-0.png`; the original
  native 1.11 window clips those controls while Next remains clickable.

These fixtures check that the harness rejects the observed clipping. They do
not replace visual review, test arbitrary scaling, or establish rendering/GPU
compatibility. The original screenshots remain in their respective run artifacts.

`timezone-authentication.tsv` is the unmodified `40012807977` first-run frame 5
OCR. It includes the precise native timezone request and a uniquely recognized
Password placeholder scored 58.2. The harness requires the high-confidence
request text and observed authentication title, permits that specific field at
confidence 45, then verifies the actual timezone change before taking further
screenshots. It never uses an unrecognized or ambiguous field.

`timezone-authentication-fedora.tsv` is the unmodified `40030245690` frame 5
OCR. The same visually verified native password placeholder scores 48.2 with
this background, while the exact timezone request and Authenticate button have
high confidence. The narrow field threshold is 45; the prompt, unique field,
unique submission control and actual resulting timezone are all still required.

`portal-consent-alma10.tsv` is the unmodified `40030259820`
`source-before-portal-consent-1.png` OCR. Small text behind the modal interleaves
between its two heading lines in the reading order. The matcher retains the
exact high-confidence screenshot-request phrase within its heading column and
font size, and still requires a unique visible Allow button. Wrong requests or
a displaced heading word fail the regression test.

`timezone-authentication-focused-fedora.tsv` is the unmodified `40038316592`
frame 6 OCR. Its focused placeholder scores only 32.4 and must remain rejected.
When the exact timezone request and a unique weak field are recognized, the
harness also OCRs a grayscale, three-times-enlarged crop of that field's observed
bounds, padded by four pixels. It does not depend on the cyan submission label
being recognized before its own crop runs. An isolated Ubuntu 24.04 Tesseract
5.3.4 reproduction of run `40043111760` scored the raw field 32.4 and the plain
grayscale crop 96.8; enlarging the full frame still missed it. No thresholding or
inversion is needed. The field and submission button must still meet their
existing confidence/uniqueness checks; originals remain unchanged. This ARM64
tool reproduction does not replace the complete x86_64 VM retry.
