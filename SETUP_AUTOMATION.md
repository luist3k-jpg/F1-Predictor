# Automatización en la nube — reentrenar y desplegar solo

Con esto, **GitHub Actions** reentrena el modelo y vuelve a desplegar la web tras cada
sesión del fin de semana (prácticas → clasificación → sprint → carrera), **sin depender
de tu Mac**. El primer pronóstico de cada GP sale de la **pace de prácticas** (OpenF1) y
se va refinando solo con cada resultado.

El workflow ya está en el repo: `.github/workflows/retrain-deploy.yml`.
Solo faltan estos 4 pasos, que requieren tu cuenta (yo no puedo introducir credenciales por ti).

---

## Paso 1 · Generar un token de Netlify

1. Entra a https://app.netlify.com/user/applications#personal-access-tokens
   (avatar → **User settings** → **Applications** → **Personal access tokens**).
2. **New access token** → ponle un nombre (p. ej. `github-actions-f1`) → **Generate token**.
3. **Copia el token** (solo se muestra una vez).

## Paso 2 · Crear el repositorio en GitHub y subir el proyecto

1. Crea un repo **vacío** en https://github.com/new (sin README, sin .gitignore).
   Nómbralo p. ej. `F1-Predictor`.
2. En una Terminal, dentro de la carpeta del proyecto, ejecuta (cambia `TU-USUARIO`):

   ```bash
   cd "/Users/luismb16/Documents/Claude/Projects/F1-Predictor"
   git remote add origin https://github.com/TU-USUARIO/F1-Predictor.git
   git push -u origin main
   ```

   (El repo ya está inicializado y con un commit en la rama `main`.)

## Paso 3 · Guardar el token como secreto del repo

1. En GitHub: repo → **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret**:
   - **Name:** `NETLIFY_AUTH_TOKEN`
   - **Secret:** *(pega el token del Paso 1)*
3. **Add secret**.

> El ID del sitio de Netlify (`c57fc590-43ad-4093-ab92-82b820812fc8`, que es
> `calm-malasada-0d2d78.netlify.app`) ya va escrito en el workflow; no es secreto.

## Paso 4 · Probar

1. En GitHub: pestaña **Actions** → workflow **“Reentrenar y desplegar F1 Predictor”**.
2. **Run workflow** (botón de ejecución manual) y observa los pasos en verde.
3. Comprueba que la web se actualizó: https://calm-malasada-0d2d78.netlify.app

---

## Cómo funciona

- **Cuándo corre:** automáticamente cada 2 horas los **jueves, viernes, sábado, domingo y
  lunes** (UTC) — cubre todas las sesiones de un fin de semana de GP. Recoge los resultados
  poco después de que cada sesión termina y redespliega.
- **Qué hace cada ejecución:** instala dependencias → `python3 train.py --download`
  (descarga datos de Jolpica, trae la pace de prácticas de OpenF1, reentrena y genera la
  predicción) → despliega `public/` a Netlify por *site ID*.
- **Base del pronóstico:** la web muestra una etiqueta con el origen del pronóstico
  (**prácticas**, **clasificación** o **preliminar/forma**) y la pace de la última práctica.

## Ajustar la frecuencia

Edita la línea `cron` en `.github/workflows/retrain-deploy.yml`:

- Más a menudo (cada hora, vie–lun): `0 * * * 5,6,0,1`
- Solo sábados y domingos: `0 */2 * * 6,0`

Sintaxis: `min hora día-mes mes día-semana` (0 = domingo). La hora es **UTC**.

## Notas

- Los workflows programados solo corren desde la rama por defecto (`main`) y pueden
  retrasarse unos minutos si GitHub está cargado.
- En repos **privados**, Actions consume minutos del plan gratuito (2.000/mes); la cadencia
  por defecto queda muy por debajo. En repos **públicos** es ilimitado.
- **Respaldo manual** (sin nube): doble clic en `update.command` (descarga + reentrena +
  despliega) o `deploy_only.command` (solo redepliega el build actual).
