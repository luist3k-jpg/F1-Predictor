// Netlify Function: resultados reales en vivo de F1 desde Jolpica/Ergast (API pública, sin clave).
// Normaliza quali / carrera / sprint / vuelta rápida del GP indicado para comparar contra la predicción.
// Uso: /.netlify/functions/f1live?season=2026&round=7   (round opcional: por defecto el "next")
const BASE = "https://api.jolpi.ca/ergast/f1";

export default async (req) => {
  const url = new URL(req.url);
  const season = url.searchParams.get("season") || "2026";
  let round = url.searchParams.get("round");

  const json = (b, s = 200) =>
    new Response(JSON.stringify(b), {
      status: s,
      headers: { "content-type": "application/json", "cache-control": "public, max-age=60" },
    });

  const get = async (path) => {
    const r = await fetch(`${BASE}/${path}`, { headers: { "User-Agent": "f1-predictor/1.0" } });
    if (!r.ok) throw new Error(`Jolpica HTTP ${r.status} en ${path}`);
    return (await r.json()).MRData;
  };

  try {
    // Si no se especifica ronda, usa la última carrera disputada + 1 (el "próximo" GP).
    if (!round) {
      const last = await get(`${season}/last/results.json?limit=1`);
      const lastRound = parseInt(last?.RaceTable?.round || "0", 10);
      round = String(lastRound + 1);
    }

    const [qD, rD, sD] = await Promise.all([
      get(`${season}/${round}/qualifying.json?limit=100`).catch(() => null),
      get(`${season}/${round}/results.json?limit=100`).catch(() => null),
      get(`${season}/${round}/sprint.json?limit=100`).catch(() => null),
    ]);

    const qRace = qD?.RaceTable?.Races?.[0];
    const rRace = rD?.RaceTable?.Races?.[0];
    const sRace = sD?.RaceTable?.Races?.[0];

    const drv = (d) => ({ code: d.code || d.driverId?.slice(0, 3).toUpperCase(), name: `${d.givenName} ${d.familyName}` });

    const quali = (qRace?.QualifyingResults || []).map((q) => ({ pos: +q.position, ...drv(q.Driver), team: q.Constructor?.name }));
    const race = (rRace?.Results || []).map((r) => ({
      pos: r.positionText && /^\d+$/.test(r.positionText) ? +r.position : null,
      status: r.status, ...drv(r.Driver), team: r.Constructor?.name,
      fastlap: String(r.FastestLap?.rank || "") === "1",
    }));
    const sprint = (sRace?.SprintResults || []).map((r) => ({
      pos: r.positionText && /^\d+$/.test(r.positionText) ? +r.position : null,
      ...drv(r.Driver), team: r.Constructor?.name,
    }));

    const pole = quali.find((q) => q.pos === 1) || null;
    const fastlap = race.find((r) => r.fastlap) || null;
    const sprintWinner = sprint.find((s) => s.pos === 1) || null;

    return json({
      season: +season, round: +round,
      raceName: rRace?.raceName || qRace?.raceName || sRace?.raceName || null,
      hasQuali: quali.length > 0, hasRace: race.some((r) => r.pos != null), hasSprint: sprint.length > 0,
      pole, fastlap, sprintWinner,
      sprintWinnerTeam: sprintWinner?.team || null,
      quali, race, sprint,
      fetched: new Date().toISOString(),
    });
  } catch (e) {
    return json({ error: "No se pudo consultar Jolpica: " + e.message }, 502);
  }
};
