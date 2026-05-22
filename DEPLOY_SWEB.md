# Deploy to sweb VPS

Target domain: `https://wmsefp.site`

Target VPS IP: `77.222.35.157`

## 1. DNS

Create DNS records for the domain:

```text
A     @      77.222.35.157
A     www    77.222.35.157
```

Wait until DNS resolves to the VPS.

## 2. Server packages

Connect to the server:

```bash
ssh root@77.222.35.157
```

Install Docker, Nginx and Certbot:

```bash
apt update
apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx git
systemctl enable --now docker nginx
```

For the 1 GB RAM VPS, add swap:

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 3. Project files

Clone the repository:

```bash
mkdir -p /opt/wms
cd /opt/wms
git clone https://github.com/Korgopolov2006/WMS_EFP.git .
```

Create production env:

```bash
cp .env.production.example .env.production
nano .env.production
```

Change at least:

```env
DJANGO_SECRET_KEY=long-random-secret
POSTGRES_PASSWORD=strong-database-password
DJANGO_SUPERUSER_PASSWORD=strong-admin-password
```

## 4. Start the app

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Check containers:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f web
```

Open locally from the server:

```bash
curl -I http://127.0.0.1:8000/
```

## 5. Nginx

Install the prepared config:

```bash
cp deploy/nginx/wmsefp.site.conf /etc/nginx/sites-available/wmsefp.site
ln -sf /etc/nginx/sites-available/wmsefp.site /etc/nginx/sites-enabled/wmsefp.site
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

## 6. HTTPS

Issue the certificate:

```bash
certbot --nginx -d wmsefp.site -d www.wmsefp.site
```

Check renewal:

```bash
certbot renew --dry-run
```

## 7. Updates

To deploy new commits:

```bash
cd /opt/wms
git pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

## Useful commands

Run migrations manually:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec web python manage.py migrate
```

Collect static files manually:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec web python manage.py collectstatic --noinput
```

Stop the project:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production down
```
