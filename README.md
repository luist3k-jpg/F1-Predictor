# F1 Predictor · Predicción de Fórmula 1 con comparación en vivo

🌐 **En vivo:** https://calm-malasada-0d2d78.netlify.app

Modelo de machine learning que predice, para el próximo Gran Premio:

- **Pole position** (clasificación)
- **Top 10 de carrera** (orden de llegada)
- **Vuelta rápida**
- **Equipo ganador del Sprint** (solo en fines de semana sprint)

La web compara cada predicción contra el **resultado real en vivo** y muestra la precisión histórica del modelo.

## Cómo funciona

- `train.py` — descarga históricos de la API gratuita **Jolpica/Ergast**, construye features pre-sesión (forma reciente de piloto y equipo, historial en el circuito, posición de campeonato), entrena 4 modelos (gradient boosting), los evalúa con partición temporal y genera `public/predictions.json` + `public/metrics.json`.
- `netlify/functions/f1live.mjs` — función serverless que trae los resultados reales del GP desde Jolpica (sin clave).
- `public/index.html` — la app: muestra predicción vs realidad y la precisión del modelo. Se sincroniza sola cada 2 min.

## Datos

Fuente: **Jolpica-F1** (sucesor de Ergast), gratuita y sin clave. El caché vive en `./data`.
No se necesita ninguna API key ni variable de entorno.

## Uso

### Refrescar predicciones y publicar (un clic)
Doble clic en **`update.command`**: descarga datos nuevos, reentrena, genera la predicción del próximo GP y despliega a Netlify.

### Manual
```
pip install scikit-learn pandas numpy
python3 train.py --download      # descarga + entrena + predice
netlify deploy --prod --dir=public --site c57fc590-43ad-4093-ab92-82b820812fc8   # calm-malasada-0d2d78
```
`train.py` sin `--download` reentrena con el caché existente en `./data`.

## Métricas (partición temporal, datos 2023–2026)

Se guardan en `public/metrics.json` y se muestran en la cabecera de la web:
acierto de pole (top-1), aciertos promedio de top-10, acierto de vuelta rápida.
El automovilismo tiene alta varianza; las salidas son **probabilísticas**.

## Cuándo reentrenar

Idealmente después de cada clasificación o carrera (corre `update.command`), para que las
features de forma reciente incorporen el último resultado y la predicción del siguiente GP
quede al día. También puede programarse.
