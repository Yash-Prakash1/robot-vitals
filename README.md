# robot-vitals

**A pre-flight data-integrity and predictive-maintenance layer for robot-learning fleets.** By Yash Prakash.

### Live demo: https://yash-prakash1.github.io/robot-vitals/

It runs entirely in your browser. No install, no backend, no sign-in.

It answers one question that the field's own evaluation research leaves open: is the robot healthy enough to trust the data it is producing? The same servo registers answer it on two timescales. A per-run gate blocks a session whose data would be silently corrupted. A longitudinal layer trends each robot's health and catches slow drift weeks before any single run would fail.

The intellectual core is not the code; it is a principled filter for deciding what is even worth testing on a closed-loop visuomotor robot, which leaves a deliberately small, rigorously justified set. This repository is a working artifact: a tested Python core, a synthetic 8-arm fleet, and a static, interactive dashboard.

## Try it in 60 seconds

Open the live demo: **https://yash-prakash1.github.io/robot-vitals/**

What you are looking at, top to bottom:

- **How the check works.** The page opens by computing, on the worst run in the dataset, the metadata a real check would stamp onto an episode: all seven joints read, each scored against its own datasheet limit, the weakest joint setting the run's score, and the resulting JSON stamp.
- **Pick an arm.** Eight simulated robot arms. Five are healthy; three each carry one planted fault. Click between them.
- **Per-run gate.** Every cell is one test run (four runs per day; columns are the 30 days), colored by its verdict (collect, flag, or pull). Hover a run for all seven joint temperatures; click it for the full breakdown, including a bar chart of each joint against its limit and the metadata stamp.
- **Predictive maintenance, per joint.** For each of the seven joints, a temperature trend and an effort trend, with two markers: where maintenance was called (slow drift detected) and where the joint became too degraded to operate (an action threshold).
- **The payoff.** A joint that passes its per-run gate every single run, while the longitudinal layer flagged it days earlier. Same sensors, two timescales.

Click **New simulation** to generate a fresh fleet in your browser, or type a seed to reproduce one. The data is synthetic, but the scoring, the drift detection, and the gate are the real logic, running live.

To run it locally instead: clone the repo and open `docs/index.html` in a browser (it needs no server), or `cd docs && python3 -m http.server` and visit the printed address.

## The problem, grounded in published research

Physical Intelligence (PI) and the wider robot-learning field train foundation models on real robots. The robots are not the product; they are the measurement instrument that generates training data and runs policy evaluations. An uncalibrated instrument produces unpublishable science.

PI's AutoEval paper (Zhou, Atreya, Tan, Pertsch, Levine, arXiv:2503.24278, CoRL 2025) documents the exact failure this project targets. Evaluation scores held steady "for the first 7 evaluation runs, or a total of 350 evaluation episodes" within "the natural variance of robot evaluations (plus or minus 10%)," then showed "a regression in performance after approximately 8 hours of continuous operation, which we attribute to an overheating of the motors of our rather affordable WidowX robot." The robot degraded, not the policy, and the score moved anyway.

The same paper contains the seam this project sews into. Its Algorithm 1 has the line:

> Failure: If unable to reset or robot unhealthy, notify human operator to help.

"Unhealthy" is never defined. AutoEval's only mitigation for the overheating is a blunt fixed timer: it pauses "for 20 minutes every 6 hours" regardless of the actual temperature. A health-triggered check is the obvious unbuilt improvement. AutoEval also re-runs and excludes hard motor-faulted trials ("only report evaluation trials that do not contain motor failures"), so it handles hard faults but misses slow drift, and it "currently only supports binary success estimates," so it wants richer health signals it does not yet have.

This project sits in a specific research neighborhood, and all of it shares one blind spot. AutoEval automates eval so robots evaluate themselves around the clock. PolaRiS (arXiv:2512.16881, a Physical Intelligence co-authored paper) evaluates policies in simulation reconstructed from a short real-world scan, validated by correlation against real-world evals and against RoboArena; the physical robot provides the scan, and real rollouts establish that correlation. RoboArena (arXiv:2506.18123) runs distributed double-blind pairwise policy comparisons across seven institutions, ranked by Elo, an LLM-leaderboard for robots. Every one of these treats the physical robot, when it is used, as a trusted, stable measurement device. None monitors the robot's own health. If hardware drift corrupts the real evals, it corrupts the reference standard the rest calibrate against.

There is a compounding cost. PI feeds autonomously collected data back into training annotated with quality and speed metadata, bucketed so the model can be steered toward higher-quality behavior. If a degraded robot's episodes are mislabeled as low-quality policy data, the mislabeling propagates into the next model. Health-stamping episodes protects the training set, not just the eval.

## The idea: test only what corrupts the data, not what varies

The obvious move is a hardware health dashboard that flags every imperfection. It is the wrong move. These robots run closed-loop visuomotor policies: they look, see where the object actually is, and adapt in real time. They are built to be robust to most hardware variation, because that variation is the entire point of a foundation model.

So the work is to distinguish two things:

- **Acceptable variation** (a tilted camera, a slightly imprecise arm, worn-in mechanics): the policy sees it and adapts. This is signal the model should handle. Do not test for it.
- **Data contamination** (a fault the policy cannot perceive or compensate for, that silently corrupts the recorded episode or confounds an eval): this breaks the science. This is what to test.

Two filters make the distinction precise.

**Filter 1, closed-loop compensability.** A hardware test is valid only if it targets a degradation the policy cannot perceive and cannot compensate for. Anything the policy can see and adapt to is acceptable variation, and testing for it is testing a capability the policy does not use.

**Filter 2, fault frequency.** Even if a fault survives Filter 1, it must actually occur on this specific hardware, often enough to justify a test, given how the hardware is built and warrantied. "I can imagine this failing" is not the bar. "This recurs in normal operation on this hardware" is the bar.

**The burden of proof is on inclusion, not exclusion.** The default is to not build a test. A fault earns one by clearing both filters with positive evidence. This turns every cut from an unprovable claim ("this never happens") into a defensible one ("this has not earned a test"), so the framework never has to prove a negative.

## The audit

This is the centerpiece. Filtering the robot's bill of materials against both filters leaves a deliberately small set.

| Candidate fault | Filter 1: policy cannot compensate? | Filter 2: actually occurs here? | Verdict |
|---|---|---|---|
| **Motor thermal** | Pass: a hot motor physically cannot deliver commanded torque, and no vision fixes a throttled actuator | Pass: AutoEval measured score regression from this, on this arm class, within normal operation | **Core, proven** |
| **Motor effort drift** (friction, gear, bearing wear as a symptom) | Pass: a binding mechanism cannot execute commanded motion | Partial: the physics is certain (all mechanical wear raises effort), but the rate on these specific gears is unvalidated | **Maintenance candidate, labeled** |
| Gripper pad wear | Partial: a worn pad slips, but the policy perceives a failed grasp and reacts, and the slip is visible in the episode, so it is far less silent than a throttled motor | Fail on frequency for this hardware: ALOHA Unleashed's failure analysis does not list it; ALOHA 2 documents the gripping tape wearing (a different material, different platform); the WidowX-250's foam and sorbothane pads are not documented to wear from repeated trials | **Cut on frequency** (test designed in full, see below) |
| Encoder drift | Pass: it corrupts the proprioceptive observation itself | Fail: the contactless magnetic absolute encoder (ams AS5045) has no wear surface; it fails abruptly with an error, not slow drift, so there is no signal to trend | **Cut** |
| Comms bus health | Pass: dropped packets break the real-time control loop | Fail: binary, not gradual; it works or errors immediately, and is already handled in the software stack | **Cut** |
| Gearbox backlash (measured directly) | Partial: closed-loop absorbs moderate backlash; only fine-contact tasks are affected | Fail as a direct measurement: noisy on this encoder, warrantied within cycle life. Captured indirectly via the effort channel | **Cut as direct test, folded into effort** |
| Supply voltage sag | Pass: like thermal, the motor cannot source torque the supply cannot provide | Partial: real but rare and usually noticed; a free register read (Present Input Voltage) | **Optional secondary read** |
| Camera position / tilt | Fail: a shifted view is exactly the variation the policy should be robust to; the observation is still honest, so the data stays valid | (moot) | **Cut** (a narrow eval-confound case is a footnote, not a test) |
| Depth-sensor calibration | Pass: false depth the policy cannot know is false | Fail: the D405 ships pre-calibrated, with no field calibration needed in normal use | **Cut** |
| Pose repeatability / accuracy | Fail: the closed-loop policy sees the object and adapts; it never relies on reaching hardcoded poses | (moot) | **Cut** (the clearest paradigm error: testing open-loop precision on a closed-loop robot) |

The honesty about exclusions is the credibility. Most hardware tests are pointless for a closed-loop visuomotor policy, because the policy adapts to imprecision, camera shifts, and most variation, and that is the entire point of the model. Thermal is the one fault that is both compensation-proof and documented to occur. That is a feature, not a limitation: ship the right monitor for the real problem rather than an elaborate dashboard watching faults that do not happen, and add the next fault the moment fleet data justifies it.

### The gripper-wear test that was designed and then cut

This cut was made after designing the test in full, not by dismissing it, and it is worth recording because it shows the difference between "could not build it" and "chose not to."

A grip-integrity check would work like this. The arm moves to a fixed reference object in its workspace, closes the gripper at a standard commanded force, lifts a few centimeters, performs a small standardized shake, and holds. It measures two things from existing registers, with no added sensors: the gripper servo's Present Current during the close (the actuation side), and whether the object stayed put, read from the gripper's own position encoder (if the fingers close past the object's known width, it slipped), optionally confirmed by the camera. A clean hold at normal current scores high; a slip, or a hold reachable only at abnormally high current, scores low. This answers the grip-pad critique directly, because it catches wear that current alone cannot, and it frames the real question: can a grasp failure be trusted to mean the policy failed, not the hardware?

It was cut on frequency. The WidowX-250's sticker-backed foam and sorbothane rubber pads are a low-load compliance aid that relieves gripper-servo stress, and they are not documented to wear from repeated trials. ALOHA Unleashed's fleet-scale failure analysis does not list pad wear. ALOHA 2 does document its gripping tape wearing out over time, but that is a different material on a different platform. Running a per-session grip test for a wear mode that is not shown to recur on these pads is overkill. The architecture adds it the day fleet data shows otherwise.

## Key decisions, and the thinking behind them

The hard part of this project was not the code; it was deciding what not to build, and being honest about what I do and do not know. These are the choices I made and why.

**One fault, deeply done, instead of a broad dashboard.** The audit above is the project. I could have flagged a dozen hardware conditions, but most of them are things a closed-loop policy adapts to, so testing for them is noise. I built the monitor for the one fault that is both compensation-proof and documented to occur (thermal), plus one labeled candidate (effort), and I wrote down exactly what I cut and why. Disciplined scope is the point, not a limitation.

**An honest scoring curve.** A naive "linear from room temperature to the limit" scale would score a perfectly healthy 61 C joint at about 35, which would cry wolf constantly and train operators to ignore the gate. My curve is flat at 100 through the healthy range and only falls as a joint nears its limit. I chose piecewise-linear over a smooth curve deliberately: I have hard ground truth at only two points (healthy operation and the datasheet limit), and the band between is unmeasured, so a straight line is the most honest interpolation. Inventing a smooth curve would imply a precision I do not have.

**Each joint against its own limit.** The arm has two servo models with different ceilings (XM430 to 80 C, XL430 to 72 C). Scoring every joint against a single number would be wrong for the cooler wrist joints. The gate scores each joint against its own datasheet limit and takes the weakest, because one hot joint corrupts the run regardless of the others.

**No countdown I cannot justify.** It is tempting to print "this joint fails in 9 days." I refuse to. CUSUM detects that a sustained shift has happened; turning that into a date assumes the degradation rate is stable, which I have not validated. So the maintenance layer shows the measured trend and the point it crossed an action threshold, never a forecast. Refusing to fabricate a number is itself a design decision.

**Two conditions before I flag a joint.** With seven joints times two channels across a fleet, there are many detectors, and any statistical detector trips on clean noise occasionally. So a joint is flagged only when the detector fires AND the performance score has actually dropped past a watch level. A flat, healthy joint never moves its score, so it stays quiet. This keeps the real deterioration visible instead of drowned in false positives.

**Effort is labeled a candidate, on purpose.** Rising effort from mechanical wear is certain physics, but its rate on these specific gears is unvalidated, so I tier the two channels honestly: thermal rests on published evidence, effort rests on principle with an unknown rate. The label is about the rate, not whether it happens.

**One source of truth for every number.** Every threshold and the whole fleet setup live in `config.json`. The Python core reads it, and the build emits it to the browser, so the dashboard and the Python can never disagree. The browser runs a hand-port of the pipeline so the demo needs no backend; that is the only duplication, the constants are shared, and it is documented at the top of the engine file.

**Synthetic data, real reads.** The fleet is simulated so anyone can run the demo with no hardware, and the README and code are explicit about that. But the measurement path is real: the checks read DYNAMIXEL registers the servo already reports, with the real addresses documented, so the path from demo to deployment is one adapter swap, not a rewrite.

## What it does, in detail

**One signal philosophy, two timescales.** The same queryable registers (DYNAMIXEL Present Temperature and Present Current, which the servo already reports over its existing serial bus) are read for two purposes.

**The per-run gate (data-integrity).** Before every test run, not once a day, the gate reads all seven joints (waist, shoulder, elbow, forearm_roll, wrist_angle, wrist_rotate, gripper) and scores each one's headroom against that joint's own datasheet limit. The run's gate score is the weakest joint.

- The scoring curve is the percent of usable thermal headroom remaining to a joint's limit: flat at 100 through the healthy range (up to the limit minus 20 C), declining only as the joint nears its limit. A joint at 61 C on an 80 C limit scores 95. Only the datasheet limits are sourced; the band and the verdict offsets are illustrative and labeled.
- The verdict has three tiers, not two: PASS (collect), WARN (collect, but flag the episodes for downweighting, which maps onto PI's quality-metadata practice), and QUARANTINE (do not collect, pull the robot). The continuous score reports headroom; the discrete verdict carries the operational decision, with a margin below the limit.
- Every run is stamped with its score, verdict, weakest joint, and the full per-joint breakdown, so each episode inherits the health context of the robot that produced it.

**The predictive-maintenance layer (longitudinal).** End of day, the same registers feed a CUSUM drift detector for every joint, on two channels: thermal (the daily temperature trend) and effort (the daily reference-motion current). Each channel reports a measured trend, a drift status (stable, drifting, or alarm), and an action cap expressed as a degradation magnitude, never a date.

**The engine.** CUSUM is two-sided, with slack k = 0.5 sigma and threshold h = 5 sigma, expressed in units of each channel's healthy noise so the parameters are principled rather than arbitrary. The noise sigma is pooled across all joints over a healthy baseline window, because measurement noise is a property of the sensor, not of one short channel; a self-estimated 7-day baseline gave a 21 percent false-alarm rate, and pooling fixed it. Wilson score intervals are used wherever a success rate is reported, because the naive normal approximation returns [1.0, 1.0] for 20 of 20 successes, claiming certainty from twenty trials, while Wilson returns roughly [0.84, 1.0]. The width of that interval at low trial counts is why eval throughput, set by robot uptime, governs how fast research can tell two policies apart.

## How the dashboard works

The dashboard (`docs/index.html`) is a single static page with the data baked in, so it loads instantly with no backend. The "New simulation" button runs a faithful in-browser port of the Python pipeline (`docs/engine.js`), so a visitor can regenerate the demo or reproduce a seed, all client-side. The reference fleet shown on load is the Python output for a fixed seed.

The constants and the fleet config are single-sourced in `config.json`. The Python core reads it through `src/config.py`, and the build emits it to `docs/config.js`, so the browser engine reads the exact same values. Change a number in `config.json` and it propagates to both the Python and the dashboard at once, with no second place to update. The only thing written in both languages is the small set of formula bodies; every number you tune lives in one file.

## Running it on a real fleet

The vitals reads add no sensors. They are DYNAMIXEL control-table register queries over the serial bus the servo already uses. `src/interface.py` documents the real addresses: Present Temperature at 146 (1 byte, 1 degree C), Present Current at 126 (2 bytes, 2.69 mA on the XM430-W350), Present Input Voltage at 144 (2 bytes, 0.1 V), all read-only. In this repo the `WidowXAdapter` reads from a simulated bus so the demo runs with no hardware; swapping in a real dynamixel-sdk bus is a one-class change.

The protocol layer never touches a specific SDK, so other platforms plug in via one adapter each. Rather than ship empty stub classes, `interface.py` keeps an `OTHER_PLATFORM_SOURCES` table naming the real data source for the rest of a typical fleet: UR5e (RTDE `joint_temperatures` and `actual_current`), Franka (libfranka `RobotState.tau_J`, with temperature from diagnostics rather than the standard state), and ARX (ARX SDK motor feedback). Adding a platform is writing one adapter against the named source; nothing above it changes.

A note for a hardware reader: the WidowX-250 6DOF is the arm class AutoEval documents overheating. Trossen's current Stationary and Mobile AI kits ship a newer WidowX AI redesign of the same lineage; the DYNAMIXEL register approach is identical either way.

## Architecture

**Start here (the 5-minute path):** open `docs/index.html` in a browser to see it run, then read `src/quality_score.py` (the per-run gate) and `src/maintenance.py` (the longitudinal CUSUM layer), which are the two-timescale core. `config.json` holds every tunable. `src/generate_dataset.py` is the wiring that runs the pipeline end to end. Everything else is plumbing.

```
robot-vitals/
  README.md
  config.json           single source of truth for constants and the fleet config
  src/
    config.py           reads config.json for the Python core
    cusum.py            two-sided CUSUM, sigma-relative, detection not forecasting
    wilson.py           Wilson score intervals, honest at small samples
    interface.py        HardwareInterface, real WidowXAdapter, documented sources
    quality_score.py    thermal gate: headroom curve, three-tier verdict, stamp
    maintenance.py      longitudinal CUSUM on the temperature and effort channels
    simulator.py        the degradation simulator (synthetic fleet)
    generate_dataset.py produces docs/data.json, data.js, and config.js
  tests/                cusum, wilson, quality_score, simulator, maintenance, interface
  docs/
    index.html          the static, interactive dashboard (GitHub Pages serves this)
    engine.js           in-browser port of the core, reads constants from config.js
    config.js           constants emitted from config.json (shared with Python)
    data.js, data.json  the baked reference fleet
```

The library and dashboard are pure standard library and need no install. To run:

```
pip install -r requirements-dev.txt   # pytest, for the tests only
python3 -m pytest tests/ -q            # 46 tests
python3 src/generate_dataset.py        # regenerate docs/data.json, data.js, config.js
open docs/index.html                   # the dashboard
```

## Honest limitations

- **Thermal rests on documented evidence; the effort channel rests on principle.** Mechanical wear raising effort is certain, but its rate on these gears is unvalidated, and the code and dashboard say so. The effort cap is illustrative.
- **This is one fault deeply done, not a broad suite.** The audit found exactly one fault that is both compensation-proof and documented to occur on this hardware. That is disciplined scoping, not thinness.
- **CUSUM has a finite false-positive rate, handled by design.** A self-calibrating detector trips on clean noise at some rate, driven by the finite baseline window. With seven joints times two channels times eight arms, that is many detectors, so a stray CUSUM trip on a flat healthy joint is likely somewhere. The two-condition flag (a CUSUM detection AND a meaningful drop in the performance score) suppresses those, and the serious state (alarm, pull) additionally requires crossing the action cap, which a healthy joint never does. The shipped demo uses a fixed seed where every healthy joint reads stable; it is one representative clean instance, not a hidden fix.
- **Every threshold except the servo datasheet limits is illustrative,** pending fleet validation, and labeled as such in the code, the dashboard, and this README. The constants live in one file, `config.json`.

## References

- AutoEval: Zhou, Atreya, Tan, Pertsch, Levine. "AutoEval: Autonomous Evaluation of Generalist Robot Manipulation Policies in the Real World." arXiv:2503.24278, CoRL 2025.
- PolaRiS: "PolaRiS: Scalable Real-to-Sim Evaluations for Generalist Robot Policies." arXiv:2512.16881 (Physical Intelligence co-authored).
- RoboArena: "RoboArena: Distributed Real-World Evaluation of Generalist Robot Policies." arXiv:2506.18123.
- pi0: "pi0: A Vision-Language-Action Flow Model for General Robot Control." arXiv:2410.24164 (7 robot configurations).
- pi0.7: Physical Intelligence, the pi0.7 paper and blog (bimanual UR5e zero-shot laundry, matching expert teleoperators' zero-shot success; data annotated by quality and speed).
- ALOHA Unleashed: arXiv:2410.13126 (failure analysis does not list gripper pad wear). ALOHA 2: arXiv:2405.02292 (documents gripping tape wear and re-application).
- DYNAMIXEL XM430-W350 and XL430-W250 control tables and specifications: the Robotis e-manuals. WidowX-250 6DOF: Trossen / Interbotix documentation. Intel RealSense D405: Intel RealSense documentation.

All quotations and figures above were checked against these primary sources. Thresholds in the code are illustrative except the servo datasheet limits (80 C for the XM430-W350 joints, 72 C for the XL430-W250 joints).
