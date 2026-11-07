# AI Voice Generator HQ beta deployment

The application is split into two deployable services:

- **API/web service:** FastAPI, Supabase Auth/Postgres, the credit ledger, and R2 audio storage.
- **GPU worker:** RunPod Serverless running Chatterbox on an NVIDIA GPU.

MilesWeb Premium remains useful for `gurbajsingh.me` and email, but is not part of this
runtime. Point `aivoicegeneratorhq.com` to the API service only after the private beta is
working on its temporary Render URL.

## 1. Create Supabase

1. Create a Supabase project in the closest region to the expected customers.
2. In Authentication, enable email/password and require email confirmation.
3. Copy the Project URL and anon/public key. Do not use the service-role key.
4. Copy the **transaction pooler** database connection string and replace its password.
5. Change its scheme to `postgresql+psycopg://` for `VOICEFORGE_DATABASE_URL`.

The API creates the `users`, `credit_ledger`, and `jobs` tables on first startup. Every
new authenticated account receives `VOICEFORGE_STARTER_CREDITS` exactly once.

## 2. Create private Cloudflare R2 storage

1. Create a private bucket named `ai-voice-generator-hq`.
2. Create an R2 API token with object read/write access to only that bucket.
3. Record the S3 endpoint, access key ID, and secret access key.
4. Leave `VOICEFORGE_R2_PUBLIC_URL` unset so downloads use short-lived signed URLs.

## 3. Build the RunPod worker

Docker is not installed on this PC, so `.github/workflows/worker-image.yml` builds the
image automatically after the repository is pushed to GitHub. In the repository's
**Actions** tab, run **Build GPU worker image**. It publishes:

`ghcr.io/YOUR_GITHUB_USERNAME/ai-voice-worker:latest`

In RunPod Serverless, create an endpoint from that image. Start with one active worker,
one max worker, a 24 GB GPU class, and a 15-minute execution timeout. Add `HF_TOKEN` only
if the model download requires it. If the GitHub package is private, add a RunPod container
registry credential using a GitHub personal access token with `read:packages`. Record the
endpoint ID and API key.

## 4. Deploy the API to Render

Push this directory to a private GitHub repository, create a Render Blueprint from
`render.yaml`, and enter each secret marked `sync: false`. Use:

- `VOICEFORGE_SUPABASE_URL`
- `VOICEFORGE_SUPABASE_ANON_KEY`
- `VOICEFORGE_DATABASE_URL`
- `VOICEFORGE_RUNPOD_ENDPOINT_ID`
- `VOICEFORGE_RUNPOD_API_KEY`
- all five `VOICEFORGE_R2_*` private-bucket values

The first successful deploy should pass `/api/health`. Create a beta account, confirm the
email, and run a short generation before configuring the domain.

## 5. Connect the domain

1. Add `app.aivoicegeneratorhq.com` as the Render custom domain.
2. Put the domain on Cloudflare DNS and add the CNAME Render provides.
3. Keep the root domain available for an SEO-focused marketing site; redirect its primary
   call to action to the app subdomain.
4. Add an R2 CORS rule allowing `GET` and `HEAD` from the final app origin.
5. Enable HTTPS-only and keep the R2 bucket private.

## Credit rules

- One Unicode character submitted equals one credit.
- Credits are reserved in the same database transaction that creates the job.
- A failed or interrupted job receives one idempotent refund.
- The append-only ledger is the source of truth; balance is the sum of ledger entries.
- Payment webhooks should add positive ledger entries only after the payment provider
  reports a captured payment. Never credit from a browser success page.

## Release gate

Before accepting public payments, add payment webhooks, abuse/rate limiting, terms and
privacy pages, a voice-deletion policy, support contact details, monitoring, and a manual
suspension control. Keep the first launch invite-only.
