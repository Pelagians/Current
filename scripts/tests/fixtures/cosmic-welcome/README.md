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
confidence 50, then verifies the actual timezone change before taking further
screenshots. It never uses an unrecognized or ambiguous field.
