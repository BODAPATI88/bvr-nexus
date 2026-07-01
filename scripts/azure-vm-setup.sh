#!/usr/bin/env bash
# Run once on the Azure VM (9.205.154.113) as root or with sudo.
# Sets up nginx to serve the BVR public site static files.
set -euo pipefail

DOMAIN="bvrinfra.in"
WEBROOT="/var/www/bvrinfra"

echo "==> Installing nginx and certbot..."
apt-get update -q
apt-get install -y -q nginx certbot python3-certbot-nginx

echo "==> Creating web root..."
mkdir -p "$WEBROOT"
chown -R www-data:www-data "$WEBROOT"

echo "==> Writing nginx site config..."
cat > /etc/nginx/sites-available/bvrinfra << EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;
    root $WEBROOT;
    index index.html;

    # React SPA routing
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Long-lived cache for hashed assets
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # 30-day cache for images
    location /images/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # No cache for index.html (ensures new deploys are picked up)
    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # Health check endpoint for Azure load balancer probes
    location = /health {
        return 200 'ok';
        add_header Content-Type text/plain;
    }

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;
}
EOF

ln -sf /etc/nginx/sites-available/bvrinfra /etc/nginx/sites-enabled/bvrinfra
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "==> nginx is running. Site root: $WEBROOT"
echo ""
echo "Next steps:"
echo "  1. Point Cloudflare DNS:  bvrinfra.in  A  9.205.154.113  (proxy OFF for cert issuance)"
echo "  2. Once DNS propagates, run:"
echo "       sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos -m admin@bvrinfra.in"
echo "  3. Re-enable Cloudflare proxy (orange cloud) after cert is issued"
echo "  4. From k8s-master, run: bash scripts/deploy-public-site.sh"
