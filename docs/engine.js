// In-browser port of the robot-vitals core, so the demos can generate a fresh
// fleet client-side (GitHub Pages cannot run Python). The RNG (mulberry32) is
// deliberately not Python's, so an in-browser fleet is a fresh random realization,
// not a byte-for-byte copy of the baked reference (docs/data.js). The fixed scenes
// read data.js for the canonical numbers; this engine drives reroll and the sandbox.
//
// Single source of truth: this engine reads every constant and the fleet config
// from window.RV_CONFIG, which docs/config.js sets from config.json (the same
// file the Python core reads via src/config.py). A constant changed in
// config.json changes both at once. Only the formula bodies are written in both
// languages; keep them in step with src/. The sections below mirror the Python
// modules in pipeline order: gate (quality_score.py) -> maintenance
// (maintenance.py, cusum.py) -> simulator (simulator.py) -> assemble
// (generate_dataset.py).

(function (root) {
  "use strict";

  var CFG = root.RV_CONFIG;
  if (!CFG) { return; }  // no config: engine stays unavailable, dashboard shows the reference fleet

  // ---- seeded RNG (mulberry32) and a gaussian draw (Box-Muller) ----
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(rng, mean, sigma) {
    var u1 = 0, u2 = 0;
    while (u1 === 0) u1 = rng();
    u2 = rng();
    return mean + sigma * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  }

  // ---- constants, all from config.json via window.RV_CONFIG ----
  var SIM = CFG.simulator;
  var JOINTS = SIM.joints;
  var JOINT_NAMES = JOINTS.map(function (j) { return j.name; });
  var LIMIT = CFG.servo_temperature_limit_c;
  var JOINT_LIMIT_C = {};
  JOINTS.forEach(function (j) { JOINT_LIMIT_C[j.name] = LIMIT[j.model]; });
  var BASE_TEMP_C = SIM.base_temp_c;
  var BASE_CURRENT_A = SIM.base_current_a;
  var RUNS_PER_DAY = SIM.runs_per_day;
  var INTRA_DAY_WARMUP_C = SIM.intra_day_warmup_c;
  var RUN_NOISE_SIGMA_C = SIM.run_noise_sigma_c;
  var CURRENT_NOISE_SIGMA_A = SIM.current_noise_sigma_a;
  var FLEET = SIM.fleet;

  var HEALTHY_BAND_C = CFG.gate.healthy_band_c;
  var DATA_AT_RISK_OFFSET_C = CFG.gate.data_at_risk_offset_c;   // rest line = limit - offset (and the trend's quarantine line)
  var CORRUPTION_OFFSET_C = CFG.gate.corruption_offset_c;       // corruption = limit - offset; resting keeps collected runs below it
  var DEFAULT_LIMIT = LIMIT["XM430-W350"];

  var BASELINE_DAYS = CFG.cusum.baseline_days;
  var CUSUM_K_SIGMA = CFG.cusum.k_sigma;
  var CUSUM_H_SIGMA = CFG.cusum.h_sigma;
  var THERMAL_ACTION_CAP_SCORE = CFG.maintenance.thermal_action_cap_score;
  var DRIFT_WATCH_SCORE = CFG.maintenance.drift_watch_score;
  var EFFORT_ZERO_SCALE_PCT = CFG.maintenance.effort_zero_scale_pct;
  var EFFORT_ACTION_CAP_PCT = CFG.maintenance.effort_action_cap_pct;
  var EFFORT_ACTION_CAP_SCORE = 100.0 * (1.0 - EFFORT_ACTION_CAP_PCT / EFFORT_ZERO_SCALE_PCT);
  var START_DATE = CFG.start_date;

  // ---- gate scoring (mirror src/quality_score.py) ----
  function thermalHeadroomScore(t, limit) {
    limit = limit || DEFAULT_LIMIT;
    var ceiling = limit - HEALTHY_BAND_C;
    if (t <= ceiling) return 100.0;
    if (t >= limit) return 0.0;
    return 100.0 * (limit - t) / HEALTHY_BAND_C;
  }
  function thermalVerdict(t, limit) {
    limit = limit || DEFAULT_LIMIT;
    // collect below the data-at-risk line, otherwise rest the actuator before recording
    return (t < limit - DATA_AT_RISK_OFFSET_C) ? "COLLECT" : "REST";
  }
  var SEVERITY = { COLLECT: 0, REST: 1 };
  function evaluateRun(temps, limits) {
    var per = {}, weakest = null, weakestScore = Infinity, worst = "COLLECT";
    JOINT_NAMES.forEach(function (j) {
      if (!(j in temps)) return;
      var limit = limits[j];
      var score = thermalHeadroomScore(temps[j], limit);
      var verdict = thermalVerdict(temps[j], limit);
      per[j] = { temp_c: temps[j], limit_c: limit, score: score, verdict: verdict };
      if (score < weakestScore) { weakestScore = score; weakest = j; }
      if (SEVERITY[verdict] > SEVERITY[worst]) worst = verdict;
    });
    return { per_joint: per, gate_score: weakestScore, weakest_joint: weakest, verdict: worst };
  }

  // ---- maintenance engine (mirror src/maintenance.py, src/cusum.py) ----
  function mean(a) { return a.reduce(function (s, x) { return s + x; }, 0) / a.length; }
  function sampleStd(a) {
    var m = mean(a), v = a.reduce(function (s, x) { return s + (x - m) * (x - m); }, 0) / (a.length - 1);
    return Math.sqrt(v);
  }
  function pooledSigma(groups) {
    var residuals = [];
    groups.forEach(function (g) {
      if (g.length < 2) return;
      var m = mean(g);
      g.forEach(function (x) { residuals.push(x - m); });
    });
    return sampleStd(residuals);
  }
  function effortPerformanceScore(current, baseline) {
    var rise = (current - baseline) / baseline;
    return Math.max(0.0, Math.min(100.0, 100.0 * (1.0 - rise / EFFORT_ZERO_SCALE_PCT)));
  }
  function runCusum(series, target, sigma) {
    sigma = Math.max(sigma, 1e-9);
    var k = CUSUM_K_SIGMA * sigma, h = CUSUM_H_SIGMA * sigma, sHi = 0, sLo = 0, firstHigh = null;
    for (var i = 0; i < series.length; i++) {
      sHi = Math.max(0, sHi + (series[i] - target) - k);
      sLo = Math.max(0, sLo + (target - series[i]) - k);
      if (firstHigh === null && sHi > h) firstHigh = i;
    }
    return firstHigh;
  }
  function analyzeChannel(series, scoreFn, capScore, channel, provenance, noiseSigma, baselineDays) {
    baselineDays = baselineDays || BASELINE_DAYS;
    var baseline = series.slice(0, baselineDays);
    var m = mean(baseline);
    var sigma = (noiseSigma == null) ? sampleStd(baseline) : noiseSigma;
    var firstHigh = runCusum(series, m, Math.max(sigma, 1e-9));
    var scores = series.map(function (x) { return scoreFn(x, m); });
    var capCross = null;
    for (var i = 0; i < scores.length; i++) { if (scores[i] <= capScore) { capCross = i; break; } }
    var statusByDay = [], quarantined = false;
    scores.forEach(function (sc, idx) {
      if (sc <= capScore) quarantined = true;            // latched: once pulled, it stays pulled
      if (quarantined) statusByDay.push("quarantine");
      else if (firstHigh != null && idx >= firstHigh && sc <= DRIFT_WATCH_SCORE) statusByDay.push("drifting");
      else statusByDay.push("stable");
    });
    return {
      channel: channel, provenance: provenance,
      raw: series.map(round4), performance_score: scores.map(round1),
      baseline_mean: round4(m), baseline_sigma: round4(sigma),
      cusum_detected_day: firstHigh, cap_cross_day: capCross,
      action_cap_score: round1(capScore), status_by_day: statusByDay,
      status: statusByDay[statusByDay.length - 1],
    };
  }
  function analyzeThermal(series, noiseSigma, limit) {
    limit = limit || DEFAULT_LIMIT;
    return analyzeChannel(series, function (x) { return thermalHeadroomScore(x, limit); },
      THERMAL_ACTION_CAP_SCORE, "thermal", "proven: cap anchored to the servo datasheet limit", noiseSigma);
  }
  function analyzeEffort(series, noiseSigma) {
    return analyzeChannel(series, effortPerformanceScore, EFFORT_ACTION_CAP_SCORE, "effort",
      "candidate: occurrence certain, rate unvalidated for these gears", noiseSigma);
  }

  // ---- simulator (mirror src/simulator.py) ----
  // the gate rests an actuator at this temperature so a run never reaches corruption
  var REST_LINE = {};
  JOINT_NAMES.forEach(function (j) { REST_LINE[j] = JOINT_LIMIT_C[j] - DATA_AT_RISK_OFFSET_C; });
  // heat added per run of use; the thermal-fault joint heats faster as it degrades
  function warmupOf(cfg, joint, day) {
    var base = INTRA_DAY_WARMUP_C;
    if (cfg.profile === "thermal-creep" && joint === cfg.creep_joint && day >= cfg.creep_onset_day) {
      base += (day - cfg.creep_onset_day) * cfg.fault_heat_c_per_day;
    }
    return base;
  }
  function effortRise(cfg, joint, day) {
    if (cfg.profile !== "effort-rise" || joint !== cfg.effort_joint || day < cfg.effort_onset_day) return 0.0;
    return (day - cfg.effort_onset_day) * cfg.effort_rate_a_per_day;
  }
  function acuteSpike(cfg, joint, day, runIndex) {
    if (cfg.profile !== "acute-hot-start") return 0.0;
    if (day === cfg.acute_day && runIndex === cfg.acute_run && joint === cfg.acute_joint) return cfg.acute_spike_c;
    return 0.0;
  }
  function simArm(cfg, rng, days) {
    var runs = [], dailyTemp = [], dailyCurrent = [], dailyRests = [];
    for (var day = 0; day < days; day++) {
      var warmup = {}, temp = {};
      JOINT_NAMES.forEach(function (j) { warmup[j] = warmupOf(cfg, j, day); temp[j] = BASE_TEMP_C[j]; });
      var rests = 0, dayRuns = [];
      for (var ri = 0; ri < RUNS_PER_DAY; ri++) {
        // the gate: if continuing would push any joint into its data-at-risk band, rest
        // (cool all joints to baseline) so the run is never recorded too hot
        var rested = JOINT_NAMES.some(function (j) { return temp[j] + warmup[j] >= REST_LINE[j]; });
        if (rested) { JOINT_NAMES.forEach(function (j) { temp[j] = BASE_TEMP_C[j]; }); rests += 1; }
        var temps = {};
        JOINT_NAMES.forEach(function (j) {
          temp[j] += warmup[j];   // the actuator heats during the run
          temps[j] = temp[j] + acuteSpike(cfg, j, day, ri) + gauss(rng, 0, RUN_NOISE_SIGMA_C);
        });
        dayRuns.push(temps);
        runs.push({ day: day, run_index: ri, temps: temps, rested: rested });
      }
      var n = dayRuns.length, tmean = {};
      JOINT_NAMES.forEach(function (j) { tmean[j] = dayRuns.reduce(function (s, r) { return s + r[j]; }, 0) / n; });
      dailyTemp.push(tmean); dailyRests.push(rests);
      // the effort channel reads the current once per run and takes the daily mean,
      // in step with the temperature channel (a single daily sample is too noisy)
      var curSamples = [];
      for (var s = 0; s < RUNS_PER_DAY; s++) {
        var cs = {};
        JOINT_NAMES.forEach(function (j) { cs[j] = BASE_CURRENT_A[j] + effortRise(cfg, j, day) + gauss(rng, 0, CURRENT_NOISE_SIGMA_A); });
        curSamples.push(cs);
      }
      var cur = {};
      JOINT_NAMES.forEach(function (j) { cur[j] = Math.max(0.0, curSamples.reduce(function (a, c) { return a + c[j]; }, 0) / RUNS_PER_DAY); });
      dailyCurrent.push(cur);
    }
    return { robot_id: cfg.robot_id, profile: cfg.profile, runs: runs,
      daily_temp_c: dailyTemp, daily_rests: dailyRests, daily_current_a: dailyCurrent };
  }
  function simulateFleet(seed, days) {
    days = days || 30;
    var rng = mulberry32(seed >>> 0);
    var arms = FLEET.map(function (cfg) { return simArm(cfg, rng, days); });
    return { days: days, seed: seed, runs_per_day: RUNS_PER_DAY, joints: JOINT_NAMES.slice(), arms: arms };
  }
  // simulate a single arm with an arbitrary profile and its own seed (used by the sandbox)
  function simulateArm(cfg, seed, days) { return simArm(cfg, mulberry32((seed >>> 0) || 1), days || 30); }

  function series(arm, key, j, n) { return range(n).map(function (d) { return arm[key][d][j]; }); }

  function analyzeFleet(arms, joints, days) {
    var tg = [], cg = [];
    arms.forEach(function (a) {
      joints.forEach(function (j) {
        tg.push(series(a, "daily_temp_c", j, BASELINE_DAYS));
        cg.push(series(a, "daily_current_a", j, BASELINE_DAYS));
      });
    });
    var tempSigma = pooledSigma(tg), curSigma = pooledSigma(cg), out = {};
    arms.forEach(function (a) {
      var per = {};
      joints.forEach(function (j) {
        per[j] = {
          thermal: analyzeThermal(series(a, "daily_temp_c", j, days), tempSigma, JOINT_LIMIT_C[j]),
          effort: analyzeEffort(series(a, "daily_current_a", j, days), curSigma),
        };
      });
      out[a.robot_id] = { joints: per };
    });
    return out;
  }

  // ---- assemble the dataset (mirror src/generate_dataset.py) ----
  function buildDataset(seed, days) {
    days = days || 30;
    var fleet = simulateFleet(seed, days);
    var joints = fleet.joints;
    var dates = range(days).map(function (d) { return addDays(START_DATE, d); });
    var maint = analyzeFleet(fleet.arms, joints, days);
    var counts = { COLLECT: 0, REST: 0 };

    var robots = fleet.arms.map(function (arm) {
      var runsOut = arm.runs.map(function (r) {
        var hour = 9 + r.run_index * 2;
        var rep = evaluateRun(r.temps, JOINT_LIMIT_C);
        counts[rep.verdict] += 1;
        var temps_c = {};
        joints.forEach(function (j) { temps_c[j] = round1(r.temps[j]); });
        return {
          run_id: arm.robot_id + "-d" + pad2(r.day) + "-r" + r.run_index,
          day: r.day, run_index: r.run_index, date: dates[r.day],
          timestamp: dates[r.day] + "T" + pad2(hour) + ":00:00",
          temps_c: temps_c, gate_score: round1(rep.gate_score),
          verdict: rep.verdict, weakest_joint: rep.weakest_joint, rested: r.rested,
        };
      });
      var jm = maint[arm.robot_id].joints, flags = [];
      joints.forEach(function (j) {
        ["thermal", "effort"].forEach(function (chan) {
          if (jm[j][chan].status !== "stable") {
            flags.push({ joint: j, channel: chan, status: jm[j][chan].status,
              detected_day: jm[j][chan].cusum_detected_day, cap_cross_day: jm[j][chan].cap_cross_day });
          }
        });
      });
      return { robot_id: arm.robot_id, profile: arm.profile, runs: runsOut,
        daily_rests: arm.daily_rests, maintenance: jm, flags: flags };
    });

    var jointDefs = JOINTS.map(function (j) {
      return { name: j.name, model: j.model, limit_c: JOINT_LIMIT_C[j.name], servos: j.servos || 1 };
    });
    return {
      meta: {
        generated_note: "Generated in your browser by docs/engine.js (a port of the Python core).",
        fleet_size: robots.length, days: days, runs_per_day: fleet.runs_per_day,
        start_date: dates[0], end_date: dates[days - 1], dates: dates, joints: jointDefs,
        verdict_counts: counts,
        thresholds: {
          servo_temp_limit_c: LIMIT, healthy_band_c: HEALTHY_BAND_C, data_at_risk_offset_c: DATA_AT_RISK_OFFSET_C,
          corruption_offset_c: CORRUPTION_OFFSET_C, thermal_action_cap_score: THERMAL_ACTION_CAP_SCORE,
          drift_watch_score: DRIFT_WATCH_SCORE, effort_action_cap_score: EFFORT_ACTION_CAP_SCORE,
          effort_action_cap_pct: EFFORT_ACTION_CAP_PCT, cusum_k_sigma: CUSUM_K_SIGMA,
          cusum_h_sigma: CUSUM_H_SIGMA, baseline_days: BASELINE_DAYS,
        },
      },
      robots: robots,
    };
  }

  // ---- helpers ----
  function range(n) { var a = []; for (var i = 0; i < n; i++) a.push(i); return a; }
  function round1(x) { return Math.round(x * 10) / 10; }
  function round4(x) { return Math.round(x * 10000) / 10000; }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function addDays(iso, d) {
    var p = iso.split("-"), dt = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2]));
    dt.setUTCDate(dt.getUTCDate() + d);
    return dt.toISOString().slice(0, 10);
  }

  root.RVEngine = {
    // pipeline (used by the grid dashboard)
    buildDataset: buildDataset, simulateFleet: simulateFleet,
    // primitives reused by the guided experience, so the page does no sim/scoring math itself
    simulateArm: simulateArm,
    analyzeThermal: analyzeThermal, analyzeEffort: analyzeEffort,
    pooledSigma: pooledSigma, evaluateRun: evaluateRun,
    thermalHeadroomScore: thermalHeadroomScore, thermalVerdict: thermalVerdict,
    // config-derived lookups (single source of truth lives in window.RV_CONFIG)
    cfg: CFG, jointLimit: JOINT_LIMIT_C, jointNames: JOINT_NAMES.slice(),
    baselineDays: BASELINE_DAYS, runsPerDay: RUNS_PER_DAY, startDate: START_DATE,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = root.RVEngine;
})(typeof window !== "undefined" ? window : globalThis);
