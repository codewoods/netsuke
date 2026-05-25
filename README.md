# netsuke — RGB PDF → CMYK PDF

Small web service that converts an RGB PDF (typically a Chrome "Save as PDF"
of an HTML mock-up) into a CMYK PDF tagged with a chosen ICC output profile.

Deploys to a Cloudflare Container behind Cloudflare Zero Trust Access, so
the upload endpoint is reachable only from your allow-listed accounts.

## Workflow

1. Open your design HTML in **Chrome 128+** and print to PDF locally
   (Cmd/Ctrl+P → Save as PDF). This step uses Chrome's native renderer
   so `w3.css`, custom fonts, and CSS layout match the on-screen preview.
2. Visit the deployed app, pick paper type and ICC profile, upload the PDF.
3. Download the CMYK-converted PDF.

The server-side conversion is done by **Ghostscript** with the chosen ICC
profile as `-sOutputICCProfile`. Vectors and embedded fonts are preserved;
no rasterisation.

## Paper type → ICC mapping

Default selection follows Adobe InDesign zh-TW / ja-JP region presets.

| Paper       | Default ICC                          | Vendor                 |
|-------------|--------------------------------------|------------------------|
| Coated      | Japan Color 2011 Coated              | JPMA / X-Rite          |
| Uncoated    | Uncoated FOGRA47L (VIGC, TAC 300%)   | VIGC / X-Rite          |

Five more coated profiles are bundled for EU/US workflows
(FOGRA39L VIGC, GRACoL 2006, SWOP 2006 Grade 3 / 5). See
[`icc/NOTICE.md`](icc/NOTICE.md) for licensing.

## Local dev

```bash
mise install              # python 3.12, node 24, bun 1.3, go 1.26
uv sync                   # install Python deps
uv run pytest
uv run uvicorn app.main:app --reload
```

Then `open http://127.0.0.1:8000` and upload your Chrome-exported PDF.

## Deploy to Cloudflare Containers

```bash
bun install               # @cloudflare/containers, wrangler
bun run test
bun run typecheck
bunx wrangler login
bunx wrangler deploy      # builds Dockerfile, pushes to CF registry
```

Then in the [Zero Trust dashboard](https://dash.cloudflare.com/?to=/:account/access):

1. Create a Self-hosted Access application for the Worker's route.
2. Add an Allow policy with your email(s).
3. Copy the Access app audience (`AUD`) and your team domain
   (`<team>.cloudflareaccess.com`).
4. Identity provider: One-time PIN (no extra IdP needed).

`ENFORCE_ACCESS=1` is enabled in `wrangler.jsonc`. Set these non-secret
Worker vars before deploying:

```bash
bunx wrangler deploy --var ACCESS_TEAM_DOMAIN:<team>.cloudflareaccess.com \
  --var ACCESS_AUD:<aud-from-access-app>
```

For local `wrangler dev`, put `ENFORCE_ACCESS=0` in `.dev.vars` if you want
to bypass Access while testing the Worker locally.

## Stack

- **Backend**: Python 3.12 + FastAPI + Ghostscript (subprocess; AGPL is
  isolated at the binary boundary). Pure-functional ICC catalog.
- **Edge**: Cloudflare Worker (TypeScript) + Durable Object–backed
  Container running the FastAPI image.
- **Auth**: Cloudflare Zero Trust Access, email allow-list.

## License

Code: Mozilla Public License 2.0 (MPL-2.0).
ICC profiles bundled under `icc/`: see [`icc/NOTICE.md`](icc/NOTICE.md).
