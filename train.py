#!/usr/bin/env python3
"""
F1 Predictor — entrenamiento de modelos y generación de predicciones.

Qué hace:
  1. (opcional) Descarga datos históricos de la API Jolpica/Ergast a ./data
  2. Construye features pre-carrera (sin fuga de datos) por piloto y carrera
  3. Entrena 4 modelos: Pole, Top-10 de carrera, Vuelta Rápida, Equipo ganador de Sprint
  4. Evalúa con partición temporal (entrena en el pasado, prueba en lo más reciente)
  5. Genera predicciones del PRÓXIMO Gran Premio -> public/predictions.json
  6. Guarda métricas del modelo -> public/metrics.json

Uso:
  python3 train.py --download         # descarga/actualiza el caché y entrena
  python3 train.py                     # entrena con el caché existente en ./data

Requisitos: pip install scikit-learn pandas numpy
"""
import argparse, json, os, sys, time, urllib.request, warnings
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "public")
BASE = "https://api.jolpi.ca/ergast/f1"
OPENF1 = "https://api.openf1.org/v1"     # pace de prácticas (libre, sin clave)
SEASONS = [2023, 2024, 2025, 2026]
DNF_POS = 20.0          # posición asignada a abandonos para promedios de forma
ROLL = 5                # ventana de forma reciente
os.makedirs(DATA, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

# ───────────────────────── Descarga (opcional) ─────────────────────────
def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "f1-predictor/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def _inner_key(t):
    return {"results": "Results", "qualifying": "QualifyingResults", "sprint": "SprintResults"}[t]

def download():
    for season in SEASONS:
        for t in ["results", "qualifying", "sprint"]:
            key, races, offset, total = _inner_key(t), {}, 0, None
            while True:
                url = f"{BASE}/{season}/{t}.json?limit=100&offset={offset}"
                data = _fetch(url)["MRData"]
                total = int(data["total"])
                for rc in data["RaceTable"]["Races"]:
                    rid = rc["round"]
                    if rid in races:
                        races[rid][key].extend(rc.get(key, []))
                    else:
                        races[rid] = rc
                offset += 100
                if offset >= total:
                    break
                time.sleep(0.3)
            out = {"season": season, "type": t, "races": list(races.values())}
            json.dump(out, open(os.path.join(DATA, f"{season}_{t}.json"), "w"))
            print(f"  guardado {season}_{t}: {len(races)} carreras (total filas {total})")
        sched = _fetch(f"{BASE}/{season}.json")["MRData"]["RaceTable"]["Races"]
        json.dump({"races": sched}, open(os.path.join(DATA, f"{season}_schedule.json"), "w"))
        time.sleep(0.3)
    print("Descarga completa.")

# ───────────────────────── Carga del caché ─────────────────────────
def _load(season, t):
    p = os.path.join(DATA, f"{season}_{t}.json")
    return json.load(open(p))["races"] if os.path.exists(p) else []

def build_frames():
    res_rows, qual_rows, spr_rows = [], [], []
    for s in SEASONS:
        for rc in _load(s, "results"):
            for r in rc.get("Results", []):
                fl = r.get("FastestLap", {})
                pos = r.get("positionText", "")
                res_rows.append(dict(
                    season=s, round=int(rc["round"]), date=rc["date"],
                    circuitId=rc["Circuit"]["circuitId"], raceName=rc["raceName"],
                    driverId=r["Driver"]["driverId"], code=r["Driver"].get("code", r["Driver"]["driverId"][:3].upper()),
                    name=r["Driver"]["givenName"] + " " + r["Driver"]["familyName"],
                    constructorId=r["Constructor"]["constructorId"], team=r["Constructor"]["name"],
                    grid=int(r.get("grid", 0) or 0),
                    finish=float(r["position"]) if pos.isdigit() else np.nan,
                    classified=pos.isdigit(),
                    fl_rank=int(fl.get("rank", 0) or 0),
                    got_fl=1 if str(fl.get("rank", "")) == "1" else 0,
                ))
        for rc in _load(s, "qualifying"):
            for q in rc.get("QualifyingResults", []):
                qual_rows.append(dict(season=s, round=int(rc["round"]),
                                      driverId=q["Driver"]["driverId"], quali=float(q["position"])))
        for rc in _load(s, "sprint"):
            for r in rc.get("SprintResults", []):
                pos = r.get("positionText", "")
                spr_rows.append(dict(season=s, round=int(rc["round"]),
                                     driverId=r["Driver"]["driverId"],
                                     constructorId=r["Constructor"]["constructorId"],
                                     team=r["Constructor"]["name"],
                                     sprint=float(r["position"]) if pos.isdigit() else np.nan))
    res = pd.DataFrame(res_rows)
    qual = pd.DataFrame(qual_rows)
    spr = pd.DataFrame(spr_rows)
    res = res.merge(qual, on=["season", "round", "driverId"], how="left")
    res["date"] = pd.to_datetime(res["date"])
    res = res.sort_values(["date", "round"]).reset_index(drop=True)
    res["top10"] = (res["finish"] <= 10).astype(float)
    res["dnf"] = (~res["classified"]).astype(float)
    # posición "efectiva" para promedios de forma (DNF penaliza)
    res["finish_eff"] = res["finish"].fillna(DNF_POS)
    res["quali_eff"] = res["quali"].fillna(DNF_POS)
    return res, spr

# ───────────────────────── Features pre-carrera ─────────────────────────
def _roll_prev(g, col, w):
    # promedio de las w carreras ANTERIORES (shift(1) evita fuga del resultado actual)
    return g[col].shift(1).rolling(w, min_periods=1).mean()

def add_features(res):
    res = res.sort_values(["driverId", "date"]).copy()
    res["drv_quali_form"] = res.groupby("driverId", group_keys=False).apply(lambda g: _roll_prev(g, "quali_eff", ROLL))
    res["drv_race_form"] = res.groupby("driverId", group_keys=False).apply(lambda g: _roll_prev(g, "finish_eff", ROLL))
    res["drv_dnf_rate"] = res.groupby("driverId", group_keys=False).apply(lambda g: _roll_prev(g, "dnf", 8))
    res["drv_fl_rate"] = res.groupby("driverId", group_keys=False).apply(lambda g: _roll_prev(g, "got_fl", 10))
    # forma del equipo (ambos autos)
    res = res.sort_values(["constructorId", "date"])
    res["team_race_form"] = res.groupby("constructorId", group_keys=False).apply(lambda g: _roll_prev(g, "finish_eff", ROLL))
    res["team_quali_form"] = res.groupby("constructorId", group_keys=False).apply(lambda g: _roll_prev(g, "quali_eff", ROLL))
    # historial del piloto en el circuito (años anteriores)
    res = res.sort_values(["driverId", "circuitId", "date"])
    res["drv_track_quali"] = res.groupby(["driverId", "circuitId"], group_keys=False).apply(lambda g: g["quali_eff"].shift(1).expanding().mean())
    res["drv_track_race"] = res.groupby(["driverId", "circuitId"], group_keys=False).apply(lambda g: g["finish_eff"].shift(1).expanding().mean())
    # ranking de campeonato antes de la carrera (puntos acumulados de la temporada, sin la carrera actual)
    res = res.sort_values(["date", "round"])
    res["pts_race"] = res["finish"].apply(lambda p: 0 if pd.isna(p) else max(0, 26 - p) if p <= 10 else 0)
    res["season_pts_before"] = res.sort_values("round").groupby(["season", "driverId"])["pts_race"].apply(lambda s: s.shift(1).cumsum()).reset_index(level=[0, 1], drop=True).fillna(0)
    res["champ_rank_before"] = res.groupby(["season", "round"])["season_pts_before"].rank(ascending=False, method="min")
    # rellenos sensatos para novatos / primeras carreras
    fill = dict(drv_quali_form=12, drv_race_form=12, drv_dnf_rate=0.15, drv_fl_rate=0.05,
                team_race_form=12, team_quali_form=12, drv_track_quali=12, drv_track_race=12, champ_rank_before=15)
    for k, v in fill.items():
        res[k] = res[k].fillna(v)
    return res.sort_values(["date", "round"]).reset_index(drop=True)

FEATS_QUALI = ["drv_quali_form", "team_quali_form", "drv_track_quali", "champ_rank_before", "drv_race_form"]
FEATS_RACE = ["grid", "drv_race_form", "team_race_form", "drv_track_race", "drv_quali_form", "drv_dnf_rate", "champ_rank_before"]
FEATS_FL = ["drv_race_form", "team_race_form", "grid", "drv_fl_rate", "champ_rank_before"]

# ───────────────────────── Entrenamiento + evaluación ─────────────────────────
def time_split(res, frac=0.8):
    races = res[["season", "round", "date"]].drop_duplicates().sort_values("date").reset_index(drop=True)
    cut = races.iloc[int(len(races) * frac)]["date"]
    return res[res["date"] < cut].copy(), res[res["date"] >= cut].copy()

def fit_core(tr):
    """Entrena los 3 modelos base (pole / carrera / vuelta rápida) con el frame dado.
    Misma configuración en la evaluación temporal y en el backtest histórico, para que
    el historial refleje exactamente el modelo que produce las predicciones."""
    trf = tr.dropna(subset=["finish"])
    mq = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.9, random_state=1).fit(tr[FEATS_QUALI], tr["quali_eff"])
    mr = GradientBoostingRegressor(n_estimators=400, max_depth=3, learning_rate=0.05, subsample=0.9, random_state=1).fit(trf[FEATS_RACE], trf["finish"])
    mfl = GradientBoostingClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.9, random_state=1).fit(trf[FEATS_FL], trf["got_fl"])
    return {"quali": mq, "race": mr, "fl": mfl}


def train_models(res):
    tr, te = time_split(res)
    metrics = {}
    models = fit_core(tr)
    m_quali, m_race, m_fl = models["quali"], models["race"], models["fl"]

    # POLE — acierto de pole en test: ¿el de menor predicción fue el pole real?
    hit = tot = 0
    for (s, r), g in te.groupby(["season", "round"]):
        if g["quali"].notna().sum() == 0:
            continue
        pred_pole = g.iloc[np.argmin(m_quali.predict(g[FEATS_QUALI]))]["driverId"]
        real_pole = g.sort_values("quali").iloc[0]["driverId"]
        hit += int(pred_pole == real_pole); tot += 1
    metrics["pole_top1_acc"] = round(hit / tot, 3) if tot else None
    metrics["pole_races_tested"] = tot

    # TOP-10 / orden de carrera — solapamiento del top-10 predicho vs. real
    overlaps = []
    for (s, r), g in te.groupby(["season", "round"]):
        g2 = g.dropna(subset=["finish"])
        if len(g2) < 10:
            continue
        pred_top10 = set(g2.assign(p=m_race.predict(g2[FEATS_RACE])).sort_values("p").head(10)["driverId"])
        real_top10 = set(g2.sort_values("finish").head(10)["driverId"])
        overlaps.append(len(pred_top10 & real_top10))
    metrics["top10_avg_correct"] = round(float(np.mean(overlaps)), 2) if overlaps else None
    metrics["top10_races_tested"] = len(overlaps)

    # VUELTA RÁPIDA — ¿el de mayor probabilidad logró la vuelta rápida?
    hit = tot = 0
    for (s, r), g in te.groupby(["season", "round"]):
        g2 = g.dropna(subset=["finish"])
        if g2["got_fl"].sum() == 0:
            continue
        p = m_fl.predict_proba(g2[FEATS_FL])[:, 1]
        pred = g2.iloc[int(np.argmax(p))]["driverId"]
        real = g2[g2["got_fl"] == 1].iloc[0]["driverId"]
        hit += int(pred == real); tot += 1
    metrics["fastlap_top1_acc"] = round(hit / tot, 3) if tot else None
    metrics["fastlap_races_tested"] = tot

    metrics["train_rows"] = int(len(tr))
    metrics["test_rows"] = int(len(te))
    metrics["seasons"] = SEASONS
    return models, metrics

# ───────────────────────── Predicción del próximo GP ─────────────────────────
def softmax_neg(x, temp=1.0):
    z = np.exp(-(np.array(x) - np.min(x)) / temp)
    return z / z.sum()

# ───────────────────── Pace de prácticas (OpenF1) ─────────────────────
def fetch_practice_pace(race_date, now=None, cache_path=None):
    """Trae la última práctica YA TERMINADA del GP cuyo domingo es race_date (YYYY-MM-DD).
    Devuelve {'session_name','session_key','pace':{code:{'practice_pos','practice_gap'}}} o None.
    Usa OpenF1 (gratis, sin clave). Cualquier fallo -> None (el pipeline cae a 'forma')."""
    try:
        rd = datetime.fromisoformat(str(race_date)[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        sess = _fetch(f"{OPENF1}/sessions?year={rd.year}&session_type=Practice")
    except Exception as e:
        print("  (aviso) OpenF1 sessions falló:", e); return None
    cand = []
    for s in sess:
        if s.get("is_cancelled"):
            continue
        ds, de = s.get("date_start"), s.get("date_end")
        if not ds or not de:
            continue
        try:
            d0, d1 = datetime.fromisoformat(ds), datetime.fromisoformat(de)
        except Exception:
            continue
        if d0.tzinfo is None: d0 = d0.replace(tzinfo=timezone.utc)
        if d1.tzinfo is None: d1 = d1.replace(tzinfo=timezone.utc)
        # sesión del fin de semana de este GP y ya terminada
        if rd - timedelta(days=4) <= d0 <= rd + timedelta(days=1) and d1 < now:
            cand.append((d1, s.get("session_key"), s.get("session_name", "")))
    if not cand:
        return None
    cand.sort()
    _, skey, sname = cand[-1]            # la práctica más reciente ya terminada (normalmente FP3/FP2)
    try:
        result = _fetch(f"{OPENF1}/session_result?session_key={skey}")
        drivers = _fetch(f"{OPENF1}/drivers?session_key={skey}")
    except Exception as e:
        print("  (aviso) OpenF1 resultado/drivers falló:", e); return None
    code_by_num = {d.get("driver_number"): d.get("name_acronym", "") for d in drivers}
    pace = {}
    for r in result:
        code = code_by_num.get(r.get("driver_number"))
        pos = r.get("position")
        if not code or pos is None:
            continue
        gap = r.get("gap_to_leader")
        pace[code] = {"practice_pos": int(pos),
                      "practice_gap": float(gap) if isinstance(gap, (int, float)) else None}
    if not pace:
        return None
    out = {"session_name": sname, "session_key": skey, "pace": pace}
    if cache_path:
        try:
            json.dump(out, open(cache_path, "w"))
        except Exception:
            pass
    return out

def predict_next(res, spr, models):
    sched = json.load(open(os.path.join(DATA, "2026_schedule.json")))["races"]
    raced = {(2026, int(rc["round"])) for rc in _load(2026, "results")}
    nxt = next((r for r in sched if (2026, int(r["round"])) not in raced), None)
    if nxt is None:
        return None
    rnd, circuit = int(nxt["round"]), nxt["Circuit"]["circuitId"]
    is_sprint = "Sprint" in nxt
    # lista de participantes: última quali del próximo GP si existe; si no, última carrera previa
    qual_next = [rc for rc in _load(2026, "qualifying") if int(rc["round"]) == rnd]
    if qual_next:
        entries = [(q["Driver"]["driverId"], q["Driver"].get("code", ""), q["Driver"]["givenName"] + " " + q["Driver"]["familyName"], None, None, float(q["position"]))
                   for q in qual_next[0]["QualifyingResults"]]
        entries = [(d, c, n, None, None, grid) for (d, c, n, _, _, grid) in entries]
        # equipo desde la última carrera conocida
        last = res[res["season"] == 2026].sort_values("round").groupby("driverId").tail(1).set_index("driverId")
    else:
        last_round = max(int(rc["round"]) for rc in _load(2026, "results"))
        last = res[(res["season"] == 2026) & (res["round"] == last_round)].set_index("driverId")
        entries = [(d, row["code"], row["name"], None, None, np.nan) for d, row in last.iterrows()]

    last2026 = res[res["season"] == 2026].sort_values(["round"]).groupby("driverId").tail(1).set_index("driverId")

    rows = []
    for d, code, name, _, _, grid in entries:
        if d in last2026.index:
            f = last2026.loc[d]
        elif d in res.set_index("driverId").index:
            f = res[res["driverId"] == d].iloc[-1]
        else:
            continue
        team = f["team"]; cid = f["constructorId"]
        # historial del piloto en este circuito
        tr_q = res[(res["driverId"] == d) & (res["circuitId"] == circuit)]["quali_eff"]
        tr_r = res[(res["driverId"] == d) & (res["circuitId"] == circuit)]["finish_eff"]
        rows.append(dict(
            driverId=d, code=code or f["code"], name=name, team=team, constructorId=cid,
            grid=float(grid) if not pd.isna(grid) else np.nan,
            drv_quali_form=f["drv_quali_form"], drv_race_form=f["drv_race_form"],
            team_quali_form=f["team_quali_form"], team_race_form=f["team_race_form"],
            drv_dnf_rate=f["drv_dnf_rate"], drv_fl_rate=f["drv_fl_rate"],
            champ_rank_before=f["champ_rank_before"],
            drv_track_quali=tr_q.mean() if len(tr_q) else f["drv_quali_form"],
            drv_track_race=tr_r.mean() if len(tr_r) else f["drv_race_form"],
        ))
    X = pd.DataFrame(rows)
    if X.empty:
        return None

    # POLE — predicción de forma (base)
    quali_known = bool(qual_next)
    basis = "quali" if quali_known else "form"
    practice_info = None
    pq = models["quali"].predict(X[FEATS_QUALI])
    X["pred_quali"] = pq

    if quali_known:
        X["p_pole"] = softmax_neg(pq, temp=1.2)
        X["grid"] = X["grid"].fillna(X["pred_quali"].rank(method="first"))
    else:
        # ¿hay una práctica ya terminada de este GP? -> PRIMER pronóstico basado en prácticas
        practice_info = fetch_practice_pace(nxt["date"], cache_path=os.path.join(DATA, "2026_practice.json"))
        if practice_info and practice_info.get("pace"):
            basis = "practice"
            pace = practice_info["pace"]
            X["practice_pos"] = X["code"].map(lambda c: (pace.get(c) or {}).get("practice_pos"))
            X["practice_gap"] = X["code"].map(lambda c: (pace.get(c) or {}).get("practice_gap"))
            worst = X["practice_pos"].max()
            pos_f = X["practice_pos"].fillna((worst if pd.notna(worst) else len(X)) + 1)
            form_rank = X["pred_quali"].rank(method="first")
            W = 0.70  # la práctica domina el primer pronóstico; la forma aporta el resto
            X["blend_score"] = W * pos_f + (1 - W) * form_rank
            X["p_pole"] = softmax_neg(X["blend_score"], temp=1.5)
            X["grid"] = X["blend_score"].rank(method="first")     # parrilla estimada desde la práctica
        else:
            practice_info = None
            X["p_pole"] = softmax_neg(pq, temp=1.2)
            X["grid"] = X["grid"].fillna(X["pred_quali"].rank(method="first"))
    # CARRERA
    pr = models["race"].predict(X[FEATS_RACE])
    X["pred_race"] = pr
    # probabilidad top-10 vía softmax sobre posición predicha
    X["p_top10_score"] = softmax_neg(pr, temp=2.5)
    order = X.sort_values("pred_race").reset_index(drop=True)
    # VUELTA RÁPIDA
    pfl = models["fl"].predict_proba(X[FEATS_FL])[:, 1]
    X["p_fl"] = pfl / pfl.sum()

    def drv(row, p):
        return dict(code=row["code"], name=row["name"], team=row["team"], p=round(float(p), 3))

    pole_sorted = X.sort_values("p_pole", ascending=False)
    fl_sorted = X.sort_values("p_fl", ascending=False)

    pred = dict(
        generated_at=datetime.now(timezone.utc).isoformat(),
        season=2026, round=rnd, raceName=nxt["raceName"],
        circuit=nxt["Circuit"]["circuitName"], locality=nxt["Circuit"]["Location"]["locality"],
        date=nxt["date"], is_sprint=is_sprint,
        quali_known=quali_known, basis=basis,
        pole=dict(predicted=drv(pole_sorted.iloc[0], pole_sorted.iloc[0]["p_pole"]),
                  top5=[drv(r, r["p_pole"]) for _, r in pole_sorted.head(5).iterrows()]),
        top10=[dict(pos=i + 1, **drv(r, r["p_top10_score"])) for i, (_, r) in enumerate(order.head(10).iterrows())],
        fastest_lap=dict(predicted=drv(fl_sorted.iloc[0], fl_sorted.iloc[0]["p_fl"]),
                         top5=[drv(r, r["p_fl"]) for _, r in fl_sorted.head(5).iterrows()]),
        sprint_team=None,
    )

    # Detalle de la pace de prácticas (para mostrar en la web cuando basis == "practice")
    if practice_info:
        ps = X[X["practice_pos"].notna()].sort_values("practice_pos")
        pred["practice"] = dict(
            session=practice_info.get("session_name", ""),
            top5=[dict(pos=int(r["practice_pos"]), code=r["code"], name=r["name"], team=r["team"],
                       gap=(round(float(r["practice_gap"]), 3) if pd.notna(r["practice_gap"]) else None))
                  for _, r in ps.head(5).iterrows()],
        )

    # EQUIPO GANADOR DE SPRINT (solo en fines de semana sprint)
    if is_sprint and not spr.empty:
        teamp = X.groupby("team")["p_top10_score"].sum().sort_values(ascending=False)
        teamp = teamp / teamp.sum()
        pred["sprint_team"] = dict(predicted=teamp.index[0],
                                   top3=[dict(team=t, p=round(float(p), 3)) for t, p in teamp.head(3).items()])
    return pred

# ───────────────────── Historial (backtest walk-forward) ─────────────────────
def backtest_history(res, spr, season=2026):
    """Reconstruye, sin fuga de datos, lo que el modelo habría predicho ANTES de cada
    GP ya disputado de la temporada: para cada ronda R se entrena solo con datos
    anteriores a la fecha de R y se predice R. Compara contra el resultado real y
    devuelve el resumen + el detalle por carrera para public/history.json.

    Las features ya son 'pre-carrera' (medias móviles/expanding con shift), así que la
    única precaución de fuga es el entrenamiento: se acota a date < fecha(R)."""
    season_res = res[res["season"] == season]
    spr_season = spr[spr["season"] == season]
    races_out = []
    agg = dict(races=0, pole_hits=0, fl_hits=0, top10_correct=0,
               sprint_races=0, sprint_hits=0)

    for rnd in sorted(int(x) for x in season_res["round"].unique()):
        g = season_res[season_res["round"] == rnd].copy()
        if g["finish"].notna().sum() < 10:          # carrera no disputada/incompleta
            continue
        dR = g["date"].iloc[0]
        tr = res[res["date"] < dR]
        if tr.dropna(subset=["finish"]).shape[0] < 100:   # historial insuficiente
            continue
        models = fit_core(tr)

        # POLE (modelo de clasificación por forma) vs. pole real (mejor posición de quali)
        g["pred_quali"] = models["quali"].predict(g[FEATS_QUALI])
        pred_pole = g.sort_values("pred_quali").iloc[0]["code"]
        qrows = g.dropna(subset=["quali"])
        actual_pole = qrows.sort_values("quali").iloc[0]["code"] if len(qrows) else None
        pole_hit = actual_pole is not None and pred_pole == actual_pole

        # TOP-10 de carrera (usa la parrilla real, conocida antes de la carrera)
        gr = g.dropna(subset=["finish"]).copy()
        gr["pred_race"] = models["race"].predict(gr[FEATS_RACE])
        pred_top10 = list(gr.sort_values("pred_race").head(10)["code"])
        actual_top10 = list(gr.sort_values("finish").head(10)["code"])
        top10_correct = len(set(pred_top10) & set(actual_top10))

        # VUELTA RÁPIDA
        gr["p_fl"] = models["fl"].predict_proba(gr[FEATS_FL])[:, 1]
        pred_fl = gr.sort_values("p_fl", ascending=False).iloc[0]["code"]
        flrows = gr[gr["got_fl"] == 1]
        actual_fl = flrows.iloc[0]["code"] if len(flrows) else None
        fl_hit = actual_fl is not None and pred_fl == actual_fl

        # SPRINT (solo si esa ronda tuvo sprint): equipo con mayor prob. agregada
        sprint_block = None
        sround = spr_season[spr_season["round"] == rnd]
        if len(sround):
            gr["p_top10_score"] = softmax_neg(gr["pred_race"].values, temp=2.5)
            teamp = gr.groupby("team")["p_top10_score"].sum().sort_values(ascending=False)
            pred_team = teamp.index[0] if len(teamp) else None
            sr = sround.dropna(subset=["sprint"]).sort_values("sprint")
            actual_team = sr.iloc[0]["team"] if len(sr) else None
            if actual_team is not None:
                sprint_hit = pred_team == actual_team
                sprint_block = dict(pred=pred_team, actual=actual_team, hit=bool(sprint_hit))
                agg["sprint_races"] += 1
                agg["sprint_hits"] += int(sprint_hit)

        races_out.append(dict(
            round=int(rnd), raceName=g["raceName"].iloc[0], date=str(pd.Timestamp(dR).date()),
            is_sprint=bool(len(sround)),
            pole=dict(pred=pred_pole, actual=actual_pole, hit=bool(pole_hit)),
            top10=dict(correct=int(top10_correct), pred=pred_top10, actual=actual_top10),
            fastlap=dict(pred=pred_fl, actual=actual_fl, hit=bool(fl_hit)),
            sprint=sprint_block,
        ))
        agg["races"] += 1
        agg["pole_hits"] += int(pole_hit)
        agg["fl_hits"] += int(fl_hit)
        agg["top10_correct"] += top10_correct

    n = agg["races"] or 1
    summary = dict(
        races=agg["races"],
        pole_hits=agg["pole_hits"], pole_acc=round(agg["pole_hits"] / n, 3),
        fastlap_hits=agg["fl_hits"], fastlap_acc=round(agg["fl_hits"] / n, 3),
        top10_total_correct=agg["top10_correct"], top10_avg=round(agg["top10_correct"] / n, 2),
        sprint_races=agg["sprint_races"], sprint_hits=agg["sprint_hits"],
        sprint_acc=round(agg["sprint_hits"] / agg["sprint_races"], 3) if agg["sprint_races"] else None,
    )
    return dict(generated_at=datetime.now(timezone.utc).isoformat(),
                season=season, summary=summary, races=races_out)


# ───────────────────────── Main ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="descargar/actualizar datos antes de entrenar")
    args = ap.parse_args()
    if args.download:
        print("Descargando datos de Jolpica/Ergast…")
        download()
    print("Construyendo features…")
    res, spr = build_frames()
    res = add_features(res)
    print(f"  {len(res)} filas piloto-carrera, {res['date'].dt.year.nunique()} temporadas")
    print("Entrenando modelos…")
    models, metrics = train_models(res)
    print("  métricas:", json.dumps(metrics, ensure_ascii=False))
    pred = predict_next(res, spr, models)
    if pred:
        pred["model_metrics"] = metrics
        json.dump(pred, open(os.path.join(OUT, "predictions.json"), "w"), ensure_ascii=False, indent=2)
        json.dump(metrics, open(os.path.join(OUT, "metrics.json"), "w"), ensure_ascii=False, indent=2)
        print(f"  predicción generada para R{pred['round']} {pred['raceName']} -> public/predictions.json")
        print(f"  base: {pred.get('basis')} | POLE pred: {pred['pole']['predicted']['code']} | Vuelta rápida: {pred['fastest_lap']['predicted']['code']}")
    else:
        print("  no hay próximo GP para predecir.")

    # Historial de la temporada: backtest walk-forward (sin fuga) de los GP ya disputados.
    print("Reconstruyendo historial de la temporada…")
    hist = backtest_history(res, spr)
    json.dump(hist, open(os.path.join(OUT, "history.json"), "w"), ensure_ascii=False, indent=2)
    s = hist["summary"]
    print(f"  historial: {s['races']} GP · pole {s['pole_hits']}/{s['races']} · "
          f"top10 {s['top10_avg']}/10 · VR {s['fastlap_hits']}/{s['races']} -> public/history.json")

if __name__ == "__main__":
    main()
