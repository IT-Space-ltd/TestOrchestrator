# Reports export dependency proposal (2.8.0)

Date: 2026-11-28  
Status: **proposal only — no dependency has been added to the product**

This document is the approval package for report-export dependencies. It
covers the owner-selected stack:

- PDF: `fpdf2`
- DOCX: `python-docx`
- XLSX: `openpyxl` with native workbook charts
- optional scheduled-report rendering: Kaleido plus a separately installed
  Chrome browser

ReportLab is intentionally excluded.

## Recommendation

Approve the export work as three separable dependency slices, in this order:

1. **XLSX**: `openpyxl` + `et-xmlfile`.
   Smallest and lowest-risk slice; native charts need no browser image.
2. **DOCX**: `python-docx` + `lxml` (`typing_extensions` is already present).
   Uses a validated browser-captured PNG for charts.
3. **PDF**: `fpdf2` + `Pillow` + `fonttools`, plus the vendored DejaVu font
   assets proposed below. Uses the same validated browser-captured PNG.

Defer **Kaleido/Chrome** until saved/scheduled reports are implemented. It is
not needed for on-demand PDF/DOCX because the browser can export the already
rendered Plotly chart to PNG and submit it with the export request.

No dependency should be added to `requirements.txt`, vendored wheels, or the
Windows payload until the owner explicitly approves the corresponding slice.

## Existing Plotly state

Plotly is already part of the product:

- Python package: `plotly==7.1.0` in `requirements.txt` (MIT license).
- Python figures are built in `testorchestrator/charts.py` and serialized to
  JSON; aggregation remains outside figures.
- Browser renderer: vendored `testorchestrator/static/vendor/plotly.min.js`,
  currently plotly.js **v3.3.0**, MIT license, approximately 4.7 MiB.
- CSP-safe loader: `testorchestrator/static/vendor/plot-init.js`.
- Templates load those local files; charts are not loaded from a CDN.

The Python `plotly` package version and the browser plotly.js version are not
the same artifact and do not need matching version numbers: Python produces
plain figure JSON and the vendored browser library renders it.

## Core dependency pins and hashes

Hashes below are SHA-256. For platform-specific wheels, the Linux target is
`cp312`/`x86_64` and the Windows target is `cp312`/`amd64`. Universal wheels
are preferred where available. Source-archive hashes are included for offline
provenance and license/source-bundle use, not because installation from source
is proposed.

### XLSX slice

| Package | Pin | License | Wheel size / hash | Source hash | Notes |
|---|---:|---|---|---|---|
| openpyxl | 3.1.5 | MIT | 250,910 bytes — `5282c12b107bffeef825f4617dc029afaf41d0ea60823bbb665ef3079dc79de2` | `cf0e3cf56142039133628b5acffe8ef0c12bc902d2aadd3e0fe5878dc08d1050` | pure Python; native XLSX charts |
| et-xmlfile | 2.0.0 | MIT | 18,059 bytes — `7a91720bc756843502c3b7504c77b8fe44217c85c537d85037f0f536151b2caa` | `dab3f4764309081ce75662649be815c4c9081e88f0837825f90fd28317d4da54` | pure Python; openpyxl transitive dependency |

### DOCX slice

| Package | Pin | License | Wheel size / hash | Source hash | Notes |
|---|---:|---|---|---|---|
| python-docx | 1.2.0 | MIT | 252,987 bytes — `3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7` | `7bc9d7b7d8a69c9c02ca09216118c86552704edc23bac179283f2e38f86220ce` | pure Python |
| lxml | 6.1.3 | BSD-3-Clause | Linux manylinux_2_28: 5,244,675 bytes — `909f4e927bb051f7740d6367285fc60cdcfdaf0258c2dba4ff5ba7eadadc250c`; alternate Linux manylinux_2_17: 5,105,247 bytes — `379f8a75cf6eb7eef0af074b55f49ab73b868388a98de14646abcdfa4564bb11`; Windows amd64: 4,005,999 bytes — `3e9a00d1c2c30936f7add097c41afc5da6556c580909104aafd382cac92a855c` | `45222d94ddd511536f3b2f7d9deae3b2339b4ce0f075f1ca25703b07cad9dd21` | native XML library; use trusted binary wheels only |
| typing_extensions | 4.16.0 | PSF-2.0 | 45,571 bytes — `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` | `dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5` | already pinned in the product, so not an incremental dependency |

### PDF slice

| Package | Pin | License | Wheel size / hash | Source hash | Notes |
|---|---:|---|---|---|---|
| fpdf2 | 2.9.0 | LGPL-3.0-only | 360,586 bytes — `e57f9eb183a61bbfc1a16ccb3eb68654f9ef3de0d9a78e37015a0df2eb29ab89` | `af2e7e06a5a2f9e32e24b146b56f58166142dfff45f55370ab03bfac9c8e3e21` | pure Python; see LGPL obligations below |
| Pillow | 13.0.0 | MIT-CMU | Linux manylinux_2_28: 7,144,542 bytes — `42d63be3af4f9b951b199b0a9d23365d37ab14687e6d77b74940432c8515c4ca`; Windows amd64: 7,272,166 bytes — `ff3fe9eb621fbb9db4c4be33ab946f6bac5f98ab50ca8d3260503653656c961b` | `cdcd1ba258178f7356d74170c9a81ba4eab6a5d55748bc402a5a2a6fe6be3510` | native image library; required by fpdf2 and used for validation/re-encoding |
| fonttools | 4.68.0 | MIT | universal wheel: 1,248,357 bytes — `d76f8fdcb6936f5e1045a0c9dd721a4bf11112e60d1e243bfa1d39f06a8b3104` | `73294e233070f71e2b3653b6bd8564af676d57f26d075761fb06d1ab2e4a7a5d` | used by fpdf2 for TTF subsetting/embedding; universal wheel avoids extra native code |

### Unicode font assets for PDF

fpdf2's core PDF fonts are not adequate for arbitrary user/project/test names
because they are not Unicode fonts. Proposal: vendor DejaVu Sans regular and
bold, version 2.37, as data assets. This is not a Python package, but it is a
new distributed third-party asset and therefore needs explicit approval.

| Asset | Version | License | Size / SHA-256 |
|---|---:|---|---|
| `DejaVuSans.ttf` | 2.37 | Bitstream Vera license | 757,076 bytes — `7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954` |
| `DejaVuSans-Bold.ttf` | 2.37 | Bitstream Vera license | 705,684 bytes — `e6476c1b80502924294eed40894c5b18e06c181444ca953e5334262df9c27724` |

The license requires the copyright/trademark notice and permission notice to
accompany the fonts. The font files may be distributed as part of the product,
but may not be sold by themselves. The two files add about 1.40 MiB uncompressed
and about 0.70 MiB compressed. They are byte-for-byte files from the
official upstream `dejavu-fonts-ttf-2.37.zip` archive (5,522,795 bytes,
SHA-256
`7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a`).

Alternative rejected for production: relying on OS font paths. That is not
deterministic across offline Linux/Windows installs and makes output depend on
host fonts.

## Optional Kaleido/Chrome evaluation pins

Kaleido is **not required for on-demand exports**. If approved later for
scheduled reports, use the following isolated dependency set:

| Package | Pin | License | Wheel size / hash | Notes |
|---|---:|---|---|---|
| kaleido | 1.5.2 | MIT | 56,288 bytes — `758ae0712881f3ecfa7bac10fdd4eff9597f6561d34b4802d6225191cca1bb17` | requires an external Chrome/Chromium executable |
| choreographer | 1.4.0 | MIT | 57,999 bytes — `8acba7ce8e912e1193628eea5bbfd76ac3d63328e3195b2527c04675f16780f7` | browser process orchestration |
| logistro | 2.0.1 | MIT | 8,555 bytes — `06ffa127b9fb4ac8b1972ae6b2a9d7fde57598bf5939cd708f43ec5bba2d31eb` | logging/support package |
| platformdirs | 4.14.5 | MIT | 35,402 bytes — `8e778c6fa421516f4d3369449f8df3b0e1b72c0e0005fe88e3ec772d0a14e750` | pure Python |
| simplejson | 4.3.0 | MIT OR AFL-2.1 | universal wheel: 80,711 bytes — `48d5d79d723300b49f18bbd88d786c0410cc58b869c121024a132e2e49f9cf35` | universal wheel preferred over platform-specific accelerated wheels |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | 129,956 bytes — `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c` | already present transitively through Plotly, but should become an explicit pin if Kaleido is approved |

`packaging==26.3` is deliberately proposed instead of the newer 26.4 because
26.4 was published on 2026-11-23, inside the seven-day supply-chain cooling-off
window at the time of this proposal. The Windows payload currently contains an
unpinned transitive `packaging-26.4`; making the pin explicit would also remove
that cross-platform version drift.

Python-side Kaleido dependencies are small: approximately 0.35 MiB of wheel
input and 2.52 MiB uncompressed. The pinned packages were hash-installed and
imported successfully in the isolated proof environment. No rendering test was
performed because this host has no Chrome/Chromium executable and installing
Chrome is outside the current approval scope.

The real cost and risk is Chrome. Chrome must be a separately installed
operator prerequisite; it must not be silently downloaded or bundled without a
separate owner decision. Depending on platform and distribution channel,
Chrome/Chromium commonly adds on the order of hundreds of megabytes of
installed files. Exact installer impact cannot be stated honestly until the
owner chooses the supported Chrome provisioning model. Unlike the Python
packages, a system Chrome installation cannot be pinned by a PyPI wheel hash,
so the scheduled-report design must record the detected browser executable
path and version in job diagnostics.

## Installer and disk impact

Measured in an isolated Python 3.12 virtual environment on Linux, the core
Python dependencies occupy:

| Package | Uncompressed installed size |
|---|---:|
| fpdf2 | 3.07 MiB |
| Pillow | 6.80 MiB |
| fonttools | 9.79 MiB |
| python-docx | 2.21 MiB |
| lxml | 11.51 MiB |
| typing_extensions | 0.17 MiB (already present in product) |
| openpyxl | 1.86 MiB |
| et-xmlfile | 0.09 MiB |
| **Total core** | **35.50 MiB uncompressed** |

Excluding already-present `typing_extensions`, incremental wheel input is:

- Linux: **14,520,116 bytes / 13.85 MiB**
- Windows: **13,409,064 bytes / 12.79 MiB**

A gzip-9 measurement of the uncompressed Linux site-packages payload was
12.46 MiB. Adding the two font files raises the expected compressed artifact
impact to roughly **13.1–14.6 MiB**, depending on installer compression and
whether wheels or installed files are packaged.

Expected release-artifact impact, to be verified after implementation:

- Linux 2.7.0 `.tar.gz`/`.run`: 236,644,904/236,646,908 bytes. Estimated
  increase is about **6–7%** for the frozen Linux artifact because it
  packages installed files rather than separate wheel archives.
- Windows 2.7.0 unsigned installer: 133,219,335 bytes. Estimated increase is
  about **10–11%** because the Windows payload carries unpacked site-packages.
- Installed disk footprint increases by roughly **36.9 MiB** including fonts,
  before installer/runtime compression or filesystem effects.

These are estimates, not release commitments. Each implementation slice must
record before/after artifact sizes in its commit evidence.

## License obligations and installer contents

The installers and source/offline provenance bundle must include:

1. License text and copyright notices for every new direct and transitive
   package in `3rdparty/licenses` and the corresponding Windows payload.
2. Exact package names, versions, SHA-256 hashes, upstream project URLs, and
   license identifiers in the dependency manifest.
3. For **fpdf2 (LGPL-3.0-only)** specifically:
   - the complete LGPL-3.0 license text;
   - fpdf2's copyright/license notice;
   - a clear notice that fpdf2 is distributed unmodified;
   - exact version and hash;
   - offline-accessible corresponding source for fpdf2, preferably the exact
     source archive in the release source/provenance bundle rather than only
     an internet URL;
   - no patch or vendored modification of fpdf2 unless the owner separately
     approves a stricter compliance process.
   - packaging review for the frozen PyInstaller build: fpdf2 must remain an
     unmodified, inspectable library component, and any technical barrier to
     replacing that component in a frozen onedir layout must be reviewed before
     release rather than assumed compliant.
4. DejaVu font license notices if the Unicode font assets are approved.

The product uses fpdf2 as an unmodified Python library. No copyleft-licensed
code should be copied into TestOrchestrator source. Owner/legal approval should
explicitly accept this LGPL-3.0 distribution posture before the PDF slice is
implemented.

## Security notes

A PyPI/OSV vulnerability query on 2026-11-28 for the exact proposed versions
returned zero known vulnerabilities for all listed packages. That is point-in-time
evidence only, not a guarantee.

Important risk controls:

- **Pillow and lxml contain native parser code.** Use trusted binary wheels,
  pin hashes, and do not expose them as general-purpose parsers of arbitrary
  user files.
- Browser-submitted chart images must be treated as untrusted input even
  though they are normally generated by our own JavaScript.
- Re-encode accepted PNGs with Pillow before embedding; do not embed the
  original byte stream or metadata.
- Never accept SVG for export embedding. SVG can carry scripts and external
  references; rejection is safer than sanitization.
- Do not accept user-provided fonts. Use only the vendored DejaVu font files.
- XLSX/DOCX/PDF text export must preserve the existing spreadsheet-injection
  policy: prefix text beginning with `=`, `+`, `-`, or `@` where a spreadsheet
  cell could interpret it as a formula.
- Generated DOCX/XLSX files must not contain macros, embedded objects,
  external relationships, or remote image references.
- Export generation must remain bounded by the existing report row caps and
  image-count/byte caps below.
- Kaleido/Chrome, if ever approved, is the largest new attack surface: run it
  only for server-scheduled reports, with a dedicated temporary profile,
  network disabled where possible, strict timeout, output-size cap, no
  `--no-sandbox` unless the owner explicitly accepts a platform-specific
  exception, and an actionable failure when Chrome is absent.

## Proof of concept

An isolated proof of concept was run in `/tmp/report-export-poc` using Python
3.12 and hash-checked installation of the proposed packages. Nothing was added
to the repository or product requirements.

One shared figure definition drove all three formats:

```python
{
  "title": "Logical-run outcomes by day",
  "x": ["2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"],
  "series": [
    {"name": "Passed", "values": [18, 22, 20, 25]},
    {"name": "Failed", "values": [3, 4, 5, 2]},
    {"name": "Incomplete", "values": [1, 2, 1, 1]},
  ],
}
```

For PDF/DOCX, a deterministic PNG representation of that shared definition
stood in for the browser-captured Plotly PNG. This proves the server-side
image validation/embedding path; it does not replace the real browser rendering
path. XLSX used a native openpyxl chart from the same data rather than an
image. The PDF additionally embedded DejaVu Sans and rendered non-ASCII text
(`täst ✓`) successfully.

Generated artifact evidence:

| Artifact | Bytes | SHA-256 | Validation |
|---|---:|---|---|
| `shared-figure.png` | 5,499 | `71231b026db1a4226ce9131fd12249b0ba76f3b90c28f5c4716a830751d04f2e` | Pillow `verify()` passed |
| `report-poc.xlsx` | 6,688 | `4104371f1e18a9ad5de87516a33f85dd66ad78ff97a5e858eb30605f8a2d1d65` | reopened by openpyxl; one worksheet, one native chart; ZIP integrity passed |
| `report-poc.docx` | 41,276 | `17f057a37e8ba70c98a3316591e0a08c1ee6ddaf2ca40a1376b46021e46ee1fa` | reopened by python-docx; one inline image and one table; ZIP integrity passed |
| `report-poc.pdf` | 25,432 | `cd2989e02940775786f4cee14aefb50d3c4e28e8140f2a538247078bcdef7cc7` | `pdfinfo` reported one page |

The ZIP-based DOCX/XLSX containers embed creation timestamps, so these hashes
identify this particular proof run rather than promising byte-reproducible
exports. The proof validates feasibility only. It does not approve visual design, page
layout, accessibility, or large-report performance; those are implementation
acceptance criteria.

## On-demand browser-image path

For on-demand PDF/DOCX export:

1. The existing page renders charts with vendored plotly.js.
2. When the user requests export, browser JavaScript calls
   `Plotly.toImage(plotElement, {format: "png", width: 1200, height: 675, scale: 2})`
   for each selected chart.
3. The resulting PNG bytes are submitted with the export request in the same
   authenticated, CSRF-protected browser session.
4. The server validates and normalizes the PNGs, generates the requested file
   in memory or a bounded temporary workspace, and returns it as a download.
5. The export audit event records report type, format, filters, row counts,
   truncation state, image count, image byte totals, and failure/success. It
   must not record image contents.

No persistent public upload endpoint is needed for the initial implementation.
If a separate endpoint proves necessary for large exports, it must require the
same authentication, project scope, CSRF protection, rate limiting, and audit
events as export generation.

### Image validation plan

Treat every submitted image as hostile input:

- Accept **PNG only** initially. Reject SVG unconditionally, including SVG
  without obvious script tags. JPEG can be considered later only if file size
  requires it.
- Do not trust `Content-Type`, file extension, or the data-URL prefix.
- Enforce a binary PNG magic header and Pillow decode/verify.
- Maximum encoded submission size: **6 MiB per image** including the data-URL
  envelope; maximum decoded size: **4 MiB per image**.
- Maximum image count: **8 per report export**.
- Maximum total decoded image bytes: **20 MiB per export**.
- Maximum dimensions: **4000 × 3000 pixels**; maximum total pixels:
  **12,000,000**. This comfortably allows a 2× export of a 1200×675 chart.
- Set/use Pillow decompression-bomb limits consistently with those caps.
- Re-open after `verify()`, convert to a safe RGB/RGBA representation as
  needed, and re-encode to PNG before embedding. Strip metadata.
- Reject truncated, corrupt, multi-frame/animated, zero-dimension, or
  dimension-mismatched images.
- Do not write user-controlled filenames or paths. If temporary storage is
  required, use server-generated names in a private temporary directory and
  delete them in a `finally` path.
- Errors must not leak parser internals or image bytes; return a generic
  validation failure and audit the rejection category.

## Implementation and validation sequence

After approval, implement exactly one format per commit:

1. **XLSX**
   - Add approved requirements and vendored wheels.
   - Export filtered report tables and native charts.
   - Tests: workbook opens with openpyxl; sheet names/rows/cells match;
     formulas are escaped; native chart exists; truncation metadata present;
     project scope enforced; audit event emitted; no macros/external links.
2. **DOCX**
   - Add approved requirements and browser PNG submission path.
   - Tests: document opens with python-docx; image count/table content match;
     invalid PNG/SVG/oversized/dimension-bomb inputs rejected; no external
     relationships; audit event emitted.
3. **PDF**
   - Add approved requirements and font assets after explicit LGPL/font
     approval.
   - Tests: generated PDF parses with `pdfinfo` or an approved parser; page
     count nonzero; Unicode text renders through embedded font; invalid image
     inputs rejected; deterministic metadata policy documented; audit event
     emitted.
4. **Cross-format regression**
   - Same filtered dataset produces equivalent row content in CSV/XLSX/DOCX/PDF.
   - Export size/time capped; large reports disclose truncation consistently.
   - Linux and Windows package builds record before/after sizes and hashes.
5. **Kaleido scheduled rendering, only after separate approval**
   - Chrome absent: actionable failure, no silent chartless report unless the
     owner chooses that behavior.
   - Chrome present: isolated scheduled render test, timeout test, output-size
     test, and no-network/temporary-profile verification.

## Approval questions

Please approve or reject each item explicitly:

1. XLSX slice: `openpyxl==3.1.5`, `et-xmlfile==2.0.0`.
2. DOCX slice: `python-docx==1.2.0`, `lxml==6.1.3` (`typing_extensions` already
   present).
3. PDF slice: `fpdf2==2.9.0`, `Pillow==13.0.0`, `fonttools==4.68.0`.
4. PDF Unicode font assets: DejaVu Sans regular/bold 2.37 under the Bitstream
   Vera license.
5. LGPL-3.0 distribution posture for unmodified fpdf2, including offline
   corresponding source in the release provenance bundle.
6. Kaleido/Chrome: defer for now, reject, or approve only as a later scheduled
   report slice.
