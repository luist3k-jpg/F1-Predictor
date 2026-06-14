#!/bin/bash
# ─────────────────────────────────────────────────────────────
# F1 Predictor — refresca predicciones y publica en Netlify (doble clic)
# 1) descarga datos nuevos de Jolpica  2) reentrena el modelo
# 3) genera predicciones del próximo GP  4) despliega a producción
# ─────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"
SITE="calm-malasada-0d2d78"                        # nombre → https://calm-malasada-0d2d78.netlify.app
SITE_ID="c57fc590-43ad-4093-ab92-82b820812fc8"     # ID del sitio (cuenta LT Consulting) — se despliega por ID
echo "📁 Proyecto: $(pwd)"
echo "🌐 Sitio Netlify: https://$SITE.netlify.app"
echo ""

# 1. Python + dependencias
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ No encontré python3. Instálalo desde https://python.org y reabre este archivo."
  read -p "Enter para cerrar."; exit 1
fi
echo "🐍 Verificando dependencias de Python…"
python3 -c "import sklearn, pandas, numpy" 2>/dev/null || {
  echo "   Instalando scikit-learn y pandas (solo la primera vez)…"
  python3 -m pip install --user --quiet scikit-learn pandas numpy || python3 -m pip install --break-system-packages --quiet scikit-learn pandas numpy
}

# 2. Descargar datos + entrenar + predecir
echo ""
echo "📥 Descargando datos y entrenando el modelo…"
python3 train.py --download

# 3. Netlify CLI
if ! command -v netlify >/dev/null 2>&1; then
  echo "⬇️  Instalando Netlify CLI…"
  npm install -g netlify-cli || sudo npm install -g netlify-cli
fi

# 4. Sesión + vínculo + deploy
echo ""
echo "🔐 Verificando sesión de Netlify…"
netlify status >/dev/null 2>&1 || netlify login
echo "🔗 Vinculando el sitio $SITE…"
netlify unlink >/dev/null 2>&1 || true
netlify link --id "$SITE_ID" || true
echo ""
echo "🚀 Desplegando a producción en $SITE…"
netlify deploy --prod --dir=public --site "$SITE_ID"

echo ""
echo "✅ Listo."
echo "   App: https://$SITE.netlify.app"
echo "   Resultados en vivo: https://$SITE.netlify.app/.netlify/functions/f1live?round=<n>"
read -p "Enter para cerrar."
