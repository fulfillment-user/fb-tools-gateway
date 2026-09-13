# Running the gateway day-to-day

Everything below is done by editing files in this repo and pushing to git.
The pipeline your devops team sets up (see `docs/DEVOPS_HANDOFF.md`) rebuilds
and redeploys automatically on every push -- there is no server to log into
for any of this.

## Give someone a login

1. Pick a password for them (or generate one).
2. Hash it:
   ```
   cd auth-service
   pip install -r requirements.txt   # once
   python3 hash_password.py "their-password"
   ```
3. Open `config/config.yaml`, add them under `users:`:
   ```yaml
   users:
     sami:
       display_name: "Sami"
       password_hash: "<paste the hash from step 2>"
       is_admin: false
       apps: ["quotation-tool"]     # only the tools they should see
   ```
4. Commit and push. Give the person their username + the *plaintext*
   password you chose in step 1 (never write the plaintext anywhere in this
   repo -- only the hash).

To remove someone's access, delete their block from `users:` (or just remove
the app slug from their `apps:` list to narrow it), commit, push.

## Switch a tool on or off ("host app A")

Find it under `apps:` in `config/config.yaml` and flip `public`:

```yaml
apps:
  quotation-tool:
    public: true    # was false
```

Commit, push. `public: false` takes it down for everyone immediately
(including admins) -- useful for taking something offline without deleting
its config.

## See who's used what

Log in as an admin user (`is_admin: true`) at
`https://tools.fulfillmentbridge.com/admin` -- shows the last 200 logins and
tool-open attempts, who, when, and whether they were let in.

## Onboard a brand new app

1. In that app's own repo, add a `Dockerfile` (copy `Dockerfile.quotation-tool`
   from the fb-rate-engine repo as a starting point) so it builds into a
   container listening on some port.
2. In this repo's `Caddyfile`, copy one of the `handle /quotation-tool/*`
   blocks, change the slug and the backend service name/port.
3. In `docker-compose.yml`, add a new service block for it (copy the
   `quotation-tool` one), pointing `image:` at an env var for that app's
   built image tag; add that var to `.env.example`.
4. In `config/config.yaml`, add it under `apps:` (start with `public: false`
   until you're ready).
5. Commit, push.
