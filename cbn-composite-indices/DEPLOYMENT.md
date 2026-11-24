# Deployment

## Current state

This host is deployed for **IP + port** access while DNS is pending:

- URL: `http://<server-ip>:8010`
- Nginx listens on `8010` and proxies to `127.0.0.1:8000`
- Gunicorn serves the Flask app on `127.0.0.1:8000` (not public)
- systemd unit: `cbn-composite-indices.service`
- Deployed source: `/var/www/cbn-composite-indices`
- QA sample datasets: `/var/www/cbn-reference`, mounted read-only at `/reference` in the web/worker containers
- Postgres, Redis, uploads, and results live in named Docker volumes

The existing Nginx default site and the other production vhosts are untouched.

## Deploy / redeploy

From the source checkout:

```sh
sudo ./deploy.sh
```

Useful overrides:

```sh
sudo PUBLIC_PORT=8010 ./deploy.sh
sudo APP_HOST_PORT=8000 ./deploy.sh
sudo DEPLOY_DIR=/var/www/cbn-composite-indices ./deploy.sh
```

`deploy.sh` is idempotent. It:

1. Syncs the checkout into `/var/www/cbn-composite-indices` without copying `.git` or overwriting `.env`.
2. Copies the five QA CSVs into `/var/www/cbn-reference`.
3. Creates a production `.env` with generated `SECRET_KEY` and `POSTGRES_PASSWORD`, mode `600`.
4. Installs `/etc/systemd/system/cbn-composite-indices.service`.
5. Builds images and starts the Compose stack via systemd.
6. Waits for `http://127.0.0.1:8000/health`.
7. Installs `/etc/nginx/sites-enabled/cbn-composite-indices` and reloads Nginx.

## DNS / TLS TODO

Not done yet. The app is reachable by IP and port only.

- [ ] Add DNS: `cbn.hudson10data.com A 172.239.103.176` (and AAAA `2600:3c13::2000:34ff:fecf:6447` if desired).
- [ ] Verify DNS: `getent ahosts cbn.hudson10data.com`.
- [ ] Issue a certificate:

  ```sh
  sudo mkdir -p /var/www/certbot
  sudo certbot certonly --webroot \
    -w /var/www/certbot \
    -d cbn.hudson10data.com \
    --non-interactive --agree-tos -m admin@example.com
  ```

- [ ] Replace the port-8010 server in `/etc/nginx/sites-available/cbn-composite-indices` with a TLS server:

  ```nginx
  server {
      listen 443 ssl;
      listen [::]:443 ssl;
      server_name cbn.hudson10data.com;

      ssl_certificate /etc/letsencrypt/live/cbn.hudson10data.com/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/cbn.hudson10data.com/privkey.pem;
      include /etc/letsencrypt/options-ssl-nginx.conf;
      ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

      client_max_body_size 50M;

      location / {
          proxy_pass http://127.0.0.1:8000;
          proxy_http_version 1.1;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_buffering off;
      }
  }

  server {
      listen 80;
      server_name cbn.hudson10data.com;
      return 301 https://$host$request_uri;
  }
  ```

- [ ] `sudo nginx -t && sudo systemctl reload nginx`.
- [ ] Verify `curl -fsS https://cbn.hudson10data.com/health`.
- [ ] Enable `SESSION_COOKIE_SECURE = True` in `app/config.py` only after HTTPS is live.
- [ ] Decide whether to keep port `8010` open or retire it.

## Verification

```sh
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8010/health
systemctl status cbn-composite-indices.service
docker compose -f /var/www/cbn-composite-indices/docker-compose.yml ps
docker compose -f /var/www/cbn-composite-indices/docker-compose.yml logs --tail=100 web worker
```

Full QA:

```sh
cd /var/www/cbn-composite-indices
docker compose exec web python qa_verify.py --datasets-dir /reference --base-url http://web:8000
```

Then follow `MANUAL_QA_CHECKLIST.md` for signup/login, an upload, Celery completion, and CSV/Excel/JSON exports.

## Rollback

```sh
sudo systemctl stop cbn-composite-indices.service
sudo rm -f /etc/nginx/sites-enabled/cbn-composite-indices
sudo nginx -t && sudo systemctl reload nginx
```

Docker volumes are not removed by the service stop, so the database, uploads, and results persist.

## Notes

- `deploy.sh` no longer clones the placeholder `YOUR_ORG` repo, installs Docker on every run, or deletes the default Nginx site.
- The web container publishes only to `127.0.0.1`; Nginx is the only public entrypoint.
- `.env` is never synced from the source checkout and is mode `600`.
- Upload templates are generated from `app/indices/configs.py` and served at `/indices/template/<code>?fmt=csv|xlsx`, so they stay in sync with the calculator definitions.
