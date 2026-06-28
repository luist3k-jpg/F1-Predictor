// Netlify Function: fuerza un reentrenamiento+despliegue ANTES del cron de 2 h.
// Dispara el workflow "retrain-deploy" de GitHub Actions vía workflow_dispatch.
//
// Seguridad:
//   · El token de GitHub NUNCA llega al navegador: vive como variable de entorno
//     en Netlify (server-side) y solo se usa aquí dentro.
//   · El endpoint es público (el sitio lo es), así que se protege con un PIN.
//
// Variables de entorno requeridas en Netlify (Site configuration → Environment variables):
//   · GH_DISPATCH_TOKEN : PAT de GitHub con permiso para lanzar Actions
//                         (fine-grained: Actions = Read and write sobre este repo;
//                          o classic con scope "repo").
//   · REFRESH_PIN       : el PIN que tú eliges (úsalo en el botón de la web).
//
// Uso desde la web:  POST /.netlify/functions/refresh   body: {"pin":"<tu_pin>"}

const OWNER = "luist3k-jpg";
const REPO = "F1-Predictor";
const WORKFLOW = "retrain-deploy.yml"; // archivo del workflow a disparar
const BRANCH = "main";

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

// Comparación de PIN en tiempo (casi) constante, para no filtrarlo por timing.
const safeEqual = (a, b) => {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
};

export default async (req) => {
  if (req.method !== "POST") return json({ error: "Usa POST." }, 405);

  const PIN = process.env.REFRESH_PIN;
  const TOKEN = process.env.GH_DISPATCH_TOKEN;
  if (!PIN || !TOKEN)
    return json({ error: "Falta configurar REFRESH_PIN y/o GH_DISPATCH_TOKEN en Netlify." }, 500);

  let pin = "";
  try {
    pin = String((await req.json())?.pin ?? "");
  } catch {
    /* cuerpo inválido → se trata como PIN vacío */
  }

  if (!safeEqual(pin, PIN)) {
    await new Promise((r) => setTimeout(r, 700)); // pequeño freno anti fuerza bruta
    return json({ error: "PIN incorrecto." }, 401);
  }

  try {
    const r = await fetch(
      `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${TOKEN}`,
          accept: "application/vnd.github+json",
          "x-github-api-version": "2022-11-28",
          "content-type": "application/json",
          "user-agent": "f1-predictor-refresh",
        },
        body: JSON.stringify({ ref: BRANCH }),
      }
    );

    if (r.status === 204)
      return json({ ok: true, message: "Reentrenamiento lanzado. Se publica en ~2 min (recarga la página)." });

    const detail = (await r.text()).slice(0, 300);
    return json({ error: `GitHub respondió ${r.status}.`, detail }, 502);
  } catch (e) {
    return json({ error: "No se pudo contactar a GitHub: " + e.message }, 502);
  }
};
