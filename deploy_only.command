#!/bin/bash
# ─────────────────────────────────────────────────────────────
# F1 Predictor — REDEPLOY rápido (sin reentrenar).
# Sube el build actual de public/ al sitio de Netlify. Doble clic.
# ─────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"
SITE="calm-malasada-0d2d78"                        # nombre → https://calm-malasada-0d2d78.netlify.app
SITE_ID="c57fc590-43ad-4093-ab92-82b820812fc8"     # ID del sitio (cuenta LT Consulting) — se despliega por ID
echo "📁 Proyecto: $(pwd)"
echo "🌐 Sitio Netlify: https://$SITE.netlify.app"
echo ""

# Netlify CLI
if ! command -v netlify >/dev/null 2>&1; then
  echo "⬇️  Instalando Netlify CLI…"
  npm install -g netlify-cli || sudo npm install -g netlify-cli
fi

echo "🔐 Verificando sesión de Netlify…"
netlify status >/dev/null 2>&1 || netlify login
echo "🔗 Vinculando el sitio $SITE…"
netlify unlink >/dev/null 2>&1 || true
netlify link --id "$SITE_ID" || true
echo ""
echo "🚀 Desplegando build actual (public/) a producción…"
netlify deploy --prod --dir=public --site "$SITE_ID"

echo ""
echo "✅ Listo. App: https://$SITE.netlify.app"
read -p "Enter para cerrar."
