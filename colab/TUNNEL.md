# HTTPS tunnel to the Colab NeMo worker

The Colab notebook binds `nemo_server` on port **8000** inside the runtime. Your local PC
needs a **public HTTPS** base URL for `RVA_STT_URL`, `RVA_TTS_URL`, and `RVA_COLAB_URL`.

**Never commit tunnel tokens or authtokens.** Store them in Colab **Secrets** or your local
`.env` (gitignored), not in this repository.

## Option A: ngrok (notebook-assisted)

1. Create a free [ngrok](https://ngrok.com/) account and copy an authtoken.
2. In Colab: **Secrets** → add `NGROK_AUTHTOKEN` (not in git).
3. Run [`notebooks/colab_nemo_es.ipynb`](../notebooks/colab_nemo_es.ipynb); it prints
   `RVA_COLAB_URL (HTTPS base)` when the token is set.
4. On the PC, set `.env`:

   - `RVA_COLAB_URL` / `RVA_STT_URL` / `RVA_TTS_URL` → that HTTPS base (no trailing slash)
   - `RVA_COLAB_TOKEN` / `RVA_STT_TOKEN` / `RVA_TTS_TOKEN` → the notebook Bearer
   - `RVA_STT_BACKEND=http`, `RVA_TTS_BACKEND=http`

5. Run `rva colab status` to confirm health, RTT, and backoff.

Manual ngrok (any host with the agent) is equivalent: `ngrok http 8000` after SSH port-forward;
paste the `https://…` URL into `RVA_*_URL`.

## Option B: Cloudflare Tunnel (quick tunnel)

Use [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) when you
prefer Cloudflare over ngrok. The Colab runtime cannot expose port 8000 by itself, so run the
tunnel **inside the same Colab session** (extra cell below) or use Option A.

**Inside Colab** (after the FastAPI thread is listening on port **8000**):

```python
# One-time per runtime (Linux amd64 Colab VM):
# !wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O /usr/local/bin/cloudflared
# !chmod +x /usr/local/bin/cloudflared
import re
import subprocess

proc = subprocess.Popen(
    ["/usr/local/bin/cloudflared", "tunnel", "--url", "http://127.0.0.1:8000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)
url = None
for _ in range(120):
    line = proc.stdout.readline()
    if not line:
        break
    m = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
    if m:
        url = m.group(0)
        break
if url:
    print("RVA_COLAB_URL (HTTPS base):", url)
else:
    print("cloudflared did not print a trycloudflare URL yet")
```

Point local `RVA_STT_URL` / `RVA_TTS_URL` at `{url}/v1/audio/transcriptions` and
`{url}/v1/audio/speech` bases (same HTTPS host, OpenAI-shaped paths on `nemo_server`).

Copy the printed URL to your local `.env` as in step 4 above. **Do not** save the tunnel URL
in git; it changes when the tunnel restarts.

For a named Cloudflare Tunnel, create the tunnel in the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com/) and set `CLOUDFLARE_TUNNEL_TOKEN` in Colab Secrets only (not in repo).

## Security

- Bearer token from the notebook is required (`INFERENCE_TOKEN` / `RVA_COLAB_TOKEN`).
- Prefer loopback-only telephony (`127.0.0.1` SIP) on the PC; only STT/TTS cross the tunnel.
- Rotate Bearer if a tunnel URL was exposed.

## Out of scope

Automating tunnel bring-up in CI, production SLA, or an always-on hosted inference endpoint.
