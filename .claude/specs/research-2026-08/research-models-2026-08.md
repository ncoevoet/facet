# Facet model-stack research pass — 2026-08-12

Scope: what is NEW or CHANGED since ~May 2026 (last pass 2026-07-01), plus re-verification of
two July watch-list items. Local-first constraint respected: no video models, no cloud-only
defaults.

## Verified environment baseline (measured this session, not assumed)

`venv/bin/pip list` on 2026-08-12:

| Package | **Installed in venv** | **Pinned in `requirements.lock.txt`** | Notes |
|---|---|---|---|
| torch | 2.10.0+cu128 | — | current stable; nothing to chase |
| transformers | 5.2.0 | `==5.2.0` | ✅ in sync; deliberately capped `<5.3` (see below) |
| pyiqa | 0.1.15.post2 | **`==0.1.16`** | ⚠️ **venv is STALE vs the lockfile** |
| bitsandbytes | 0.49.1 | **`==0.50.0`** | ⚠️ **venv is STALE vs the lockfile** |
| accelerate | 1.1.0 | — | |
| timm | 1.0.24 | — | |
| insightface | 0.7.3 | — | |
| mediapipe | 0.10.35 | — | |

### ⚠️ Correction to my own first-pass reading — the upgrades are already committed

I initially reported "Facet is on pyiqa 0.1.15.post2, bump it" and "bump bitsandbytes to
0.50". **That was wrong at the level that matters.** Checking `requirements.lock.txt` (clean
working tree, `git status --porcelain` empty, committed in `078f3b1 build(deps): bump the
python-minor-patch group across 1 directory with 19 updates (#88)`), the repo **already pins
`pyiqa==0.1.16` and `bitsandbytes==0.50.0`.** Dependabot landed both.

So the true state is: **the declared dependency set is current; the local venv is stale
against it.** The action is `venv/bin/pip install -r requirements.lock.txt`, not a version
bump. This distinction matters because it means `qrealign` and the fused 4-bit GEMM are
*already available to Facet as shipped* — no dependency negotiation required.

One genuine gap remains: `requirements.txt:39` still declares the loose floor
**`pyiqa>=0.1.11`**, and `pyproject.toml:47` declares `pyiqa>=0.1.10`. A fresh non-lockfile
install could therefore resolve to a pyiqa without `qrealign`. **If `qrealign` becomes
load-bearing, raise that floor to `>=0.1.16`.** Likewise `bitsandbytes>=0.43.0` in the
`iqa-extended` extra.

### The transformers cap is deliberate and load-bearing — do not raise it casually

`requirements.txt:11-15`, verbatim:

```
# HuggingFace Transformers - required for BiRefNet saliency, SigLIP 2 NaFlex embeddings,
# and VLM taggers (Qwen3.5 / Qwen3-VL / Qwen2.5-VL on 16gb/24gb profiles).
# Upper-bounded: transformers 5.3+ changed Qwen3.5 vision-token handling and breaks the
# batched VLM tagger (torch.cat "sizes must match" during tagging); 5.2.x is validated.
transformers>=4.57.0,<5.3
```

`pyproject.toml:63-65` mirrors it. **This cap is the single biggest constraint on adopting any
new VLM**, and it is fortunate for finding #1: `qrealign` requires `transformers>=5.0`, which
5.2.0 satisfies — the Q-ReAlign recommendation does **not** collide with the cap. Anything
requiring ≥5.3 (notably Gemma 4, which needs ≥5.5) is effectively blocked until the batched
tagger is re-validated.

Facet's own licence: MIT (`LICENSE`, "Copyright (c) 2026 Nicolas Coevoet"). This matters for
several findings below.

---

# 1. HEADLINE FINDING — Q-ReAlign (replaces Q-Align in the extended IQA tier)

**Name:** Q-ReAlign (`qrealign` / `qrealign-mini` / `qrealign-lite` / `qrealign-pro`)
**URLs:**
- Code: https://github.com/Q-Future/Q-ReAlign
- Weights: https://huggingface.co/q-future/Q-ReAlign-Mini-0.8B , `.../Q-ReAlign-Lite-4B` , `.../Q-ReAlign-Pro-9B`
- pyiqa integration: https://github.com/chaofengc/IQA-PyTorch (README, "Jun, 2026" entry)

**Dates (verified via GitHub + HF APIs):** repo created 2026-06-22, last push 2026-06-24;
HF weights last modified 2026-06-22; adopted into pyiqa v0.1.16, released **2026-07-08**.
479 GitHub stars in ~7 weeks.

**Licence — the important part, and it is a split:**
- **Weights: `apache-2.0`** — verified via the HF API for all three repos (`cardData.license`
  *and* the `license:apache-2.0` tag). `base_model` is declared as `Qwen/Qwen3.5-VL`.
- **Code repo: NO LICENSE FILE.** GitHub API returns `license: None`; the repo root
  (`.gitignore, Dockerfile, README.md, assets, configs, docs, examples, pyproject.toml,
  qalign, requirements.txt, scripts, tests`) contains no `LICENSE`, and the README contains
  zero occurrences of "licen"/"apache"/"MIT"/"non-commercial" (grepped).

  This split is *survivable for Facet specifically* because Facet would consume `qrealign`
  through **pyiqa**, not by vendoring the Q-Future repo — so the code Facet executes is
  pyiqa's, and the artefact Facet downloads is the Apache-2.0 weights. Still, the unlicensed
  upstream repo should be recorded as a residual risk, and re-checked before any vendoring.

**Why this matters:** Facet's extended tier currently offers Q-Align 4/8-bit. Q-Align is
**S-Lab License 1.0 — non-commercial only**. Verified: `Q-Future/Q-Align` GitHub API reports
`spdx_id: NOASSERTION` and the repo root contains both `LICENSE` and `S-Lab-LICENSE`; the
S-Lab text scopes itself to "Redistribution and use for **non-commercial purpose**" and states
"In the event that redistribution and/or use for commercial purpose ... is required, please
contact the contributor(s) of the work." Q-ReAlign's Apache-2.0 weights remove that
constraint outright.

**Measured benchmarks (SRCC / PLCC), self-reported in the Q-ReAlign README:**

| Model | KonIQ | SPAQ | KADID | AGI | LIVE | AVA | LSVQ | Avg. |
|---|---|---|---|---|---|---|---|---|
| Q-Align (current) | 0.942 / 0.944 | 0.932 / 0.933 | 0.912 / 0.920 | 0.738 / 0.781 | 0.897 / 0.870 | 0.798 / 0.796 | 0.867 / 0.866 | 0.869 / 0.873 |
| Mini (0.8B) | 0.935 / 0.938 | 0.931 / 0.933 | 0.903 / 0.907 | 0.811 / 0.848 | **0.907** / 0.873 | 0.797 / 0.794 | 0.869 / 0.869 | 0.879 / 0.880 |
| Lite (4B) | 0.943 / 0.941 | 0.932 / 0.934 | 0.928 / 0.931 | 0.829 / 0.871 | 0.899 / 0.862 | 0.814 / 0.804 | 0.880 / 0.879 | 0.889 / 0.889 |
| Pro (9B) | **0.950** / **0.952** | **0.935** / **0.937** | **0.934** / **0.939** | **0.843** / **0.885** | 0.902 / **0.876** | **0.832** / **0.828** | **0.883** / **0.884** | **0.896** / **0.900** |

Trained on the ONE-ALIGN mix (KonIQ + SPAQ + KADID + AGIQA-20K + AVA + LSVQ).

**Against Facet's incumbents:**
- vs **TOPIQ** (Facet's aesthetic model, 0.93 SRCC KonIQ): Lite-4B 0.943 / Pro-9B 0.950 on
  KonIQ — a real but modest technical-quality gain.
- vs **TOPIQ IAA** (Facet's aesthetic-merit model): the AVA column is the comparable one —
  0.814 (Lite) / 0.832 (Pro). **No head-to-head TOPIQ-IAA-vs-Q-ReAlign AVA number was found**,
  so the size of that gain is UNVERIFIED.

**⚠️ SOURCING CAVEAT — read before trusting the table above.**
- **There is no Q-ReAlign paper.** I checked: the repo's citation section asks users to cite
  the *original* works only (`@inproceedings{wu2024qalign}` and `@inproceedings{swift2025}`
  for ms-swift). No arXiv preprint, no venue. The numbers have had **no peer review**.
- The GitHub README table and the HF model-card table are **the same authors restating the
  same claim**, so they are one source, not two.
- The only genuine external corroboration is that **chaofengc — the author of TOPIQ itself,
  i.e. the incumbent this would displace — adopted `qrealign` into pyiqa v0.1.16 within ~2
  weeks of release.** That is meaningful signal about the code working and the maintainer
  finding it credible; it is *not* independent replication of the SRCC figures.

**Status: UNVERIFIED — needs a local benchmark on Facet's own labelled data before shipping.**
This is exactly the class of claim (vendor-reported benchmark) that should not be promoted to
fact on a README alone. The ship recommendation below is conditional on that measurement.

**Method detail (from the HF model card, useful for integration):** Q-ReAlign uses the Q-Align
level-token mechanism — the model rates quality, and the probability mass on the discrete
tokens `excellent / good / fair / poor / bad` is collapsed via fixed weights
`[1.0, 0.75, 0.5, 0.25, 0.0]` into a scalar in **`[0, 1]`** (hence the `score_range` gotcha
below). Backbone is Qwen3.5-VL (`model_type: qwen3_5`, hybrid linear/full-attention text tower
+ SigLIP-style vision encoder), trained by full-parameter bf16 SFT via ms-swift. Covers IQA +
IAA + VQA in the unified ONE-ALIGN setting.

**VRAM / compute (weight sizes measured via the HF API, safetensors totals):**

| Variant | safetensors | ~bf16 VRAM | Throughput (author-reported, SPAQ) |
|---|---|---|---|
| Mini 0.8B | **2.21 GB** | ~2.5–3 GB | **26.7 img/s @ bs=4 on RTX 4090** |
| Lite 4B | 10.35 GB | ~11–12 GB | (see repo Speed.png) |
| Pro 9B | 18.82 GB | ~19–21 GB | (H200 numbers only) |

Requires `transformers>=5.0` — Facet is on 5.2.0, satisfied.

**Integration sketch — exact surfaces, read from the source this session:**

1. `requirements.txt` / `pyproject.toml`: bump `pyiqa` to `>=0.1.16` (Facet is on
   `0.1.15.post2`, which does **not** contain `qrealign` — I confirmed the installed registry
   exposes 99 metrics with no `qrealign` entry). `pyiqa 0.1.16` is live on PyPI, uploaded
   **2026-07-08T10:58:01**, so the bump is immediately actionable.
2. `models/pyiqa_scorer.py`: add entries to the model-spec dict alongside the existing
   `qalign` / `qalign_8bit` / `qalign_4bit` block (lines 110-134), which already carries
   exactly the fields needed — `pyiqa_id`, `vram_gb`, `lower_better`, `score_range`,
   `description`.
   **Gotcha:** Q-Align's spec declares `score_range: (1, 5)` (AVA MOS scale), but pyiqa
   registers **`qrealign` with `score_range: '0, 1'`**. Copying the Q-Align spec verbatim
   would silently mis-scale every score into Facet's percentile normaliser. Use `(0, 1)`.
3. Batching: **no change required.** `models/pyiqa_scorer.py:141` defines
   `_BATCHABLE_MODELS = {'topiq', 'hyperiqa', 'dbcnn', 'topiq_iaa', 'topiq_nr_face',
   'clipiqa+'}` — an **allowlist**, not a denylist, so any model not named there is serial by
   default. A new `qrealign` entry therefore stays serial automatically, matching how the
   VLM Q-Align variants are already handled. (Q-ReAlign's reported 26.7 img/s @ bs=4 hints
   that adding Mini to the allowlist later could pay off, but that would need verifying
   against the comment's own criterion — that batching must be *bit-identical* to per-image
   scoring — which is not obviously true for a level-token softmax over variable-resolution
   inputs. Do not do it speculatively.)
4. `scoring_config.default.json` line ~3235: the `iqa_extended` block is currently exactly
   `{"qalign": false, "aesthetic_v25": false, "deqa": false}`. Add `"qrealign": false`,
   keeping the tier OFF by default per Facet's existing posture.
5. Docs: `docs/CONFIGURATION.md` extended-tier section and the `iqa-extended` extra in
   `pyproject.toml`.

The 0.8B Mini at 2.2 GB is the interesting one: it is
small enough to run on the **8gb profile** — where Q-Align never fitted — and at 26.7 img/s it
is plausibly viable in the main scoring pass rather than only as an opt-in tier. Lite-4B suits
**16gb**, Pro-9B only **24gb** and only if the VLM tagger is not co-resident. Because the
weights are Apache-2.0, this also lets the *non-commercial* `qalign*` entries be retired from
the extended tier, simplifying Facet's licence story. Gate the swap on a local A/B against
TOPIQ over a labelled Facet subset — the vendor SRCC table is not sufficient evidence to ship.

---

# 2. WATCH-LIST RE-VERIFICATION (both July items)

## (a) DSL-FIQA — **STILL SKIP. Nothing changed.**

https://github.com/DSL-FIQA/DSL-FIQA (CVPR 2024)

| Question asked | Answer (verified 2026-08-12) |
|---|---|
| Has a LICENSE file appeared? | **NO.** GitHub API `license: None`. Repo root listing is `README.md, __pycache__, ckpt, config.conf, config.py, data, dataset, file, landmark_detection, models, requirements.txt, result, test.py, test_custom.py, timm, utils, train_iqa.py` — no `LICENSE`. |
| Are weights downloadable? | **Yes** — Google Drive folder `1SQ40NDDGQB4g-sk-uBcRcGnEKrUhQSDt`, "models pretrained on three scenarios (GFIQA, CGFIQA and custom)". Not gated, not "coming soon". |
| Activity | `pushed_at: 2024-09-02` — **no code push in ~23 months.** (`updated_at` 2026-06-08 is stars/metadata only, not a commit.) 81 stars. |

**Verdict: SKIP, unchanged from July.** Downloadable weights do not rescue an unlicensed
repo — absent a licence grant the default is all-rights-reserved, which is incompatible with
shipping inside an MIT project. The one thing that would flip this (a LICENSE file) has not
happened and the repo is dormant. Recommend **dropping it from the watch list** rather than
re-checking a fourth time.

## (b) GenCrop — **STILL SKIP. Weights were never released.**

https://github.com/jhong93/gencrop

| Question asked | Answer (verified 2026-08-12) |
|---|---|
| Were weights ever released? | **NO.** README "Pretrained models" section still reads verbatim: **"Coming soon!"** |
| Licence | BSD-3-Clause — confirmed by GitHub API (`spdx_id: BSD-3-Clause`). The licence was never the problem. |
| Activity | **One single commit, ever:** `2023-12-28 "Initial commit"`. `pushed_at: 2023-12-28`. |

**Verdict: SKIP, and close the item permanently.** A repo that has had exactly one commit in
32 months and still says "Coming soon!" is abandoned. Facet needs a cropping model with
actual weights; GenCrop is not going to be it.

## (c) Q-Align licence status — **CONFIRMED NON-COMMERCIAL; now avoidable**

`Q-Future/Q-Align`, `spdx_id: NOASSERTION`, repo root carries `LICENSE` **and**
`S-Lab-LICENSE`. S-Lab License 1.0 permits only non-commercial redistribution and use.
Last push 2026-06-24 (still maintained). Facet's posture is currently correct — Q-Align sits
in an opt-in `iqa_extended` tier that is OFF by default, and Facet never redistributes the
weights — but **finding #1 makes this constraint removable entirely**, which is the strongest
practical argument for the Q-ReAlign swap.

## (d) aesthetic-predictor-v2-5 — **UNMAINTAINED + AGPL. Recommend deprecating.**

https://github.com/discus0434/aesthetic-predictor-v2-5

- **Licence: `AGPL-3.0`** (GitHub API `spdx_id: AGPL-3.0`).
- **Last commit: 2024-12-18** ("add makefile command"). That is **~20 months of no
  maintenance.** 433 stars, 11 open issues, not archived.

Two independent problems, both worth surfacing:
1. **Staleness.** No commits across the entire transformers 4.x→5.x transition. It is not
   verified to work on transformers 5.2.0.
2. **Licence.** AGPL-3.0 against Facet's MIT, in a project whose primary interface
   (`viewer.py`) *is a network service* — precisely the case AGPL §13 targets. It is
   currently an optional extra (`pip install -e .[iqa-extended]`, OFF by default) and a
   user-installed dependency rather than vendored code, which is the mitigating factor. But
   `pyproject.toml` lists `aesthetic-predictor-v2-5` in the `iqa-extended` extra, so Facet is
   actively suggesting the install.

**Recommendation:** flag `aesthetic_v25` as deprecated in `docs/CONFIGURATION.md` with an
explicit AGPL note, and prefer `qrealign` (Apache-2.0, maintained, better AVA SRCC) as the
extended-tier aesthetic option. This is a licence-hygiene win, not just a model upgrade.
*(Not a lawyer; flagging for a human decision rather than asserting a legal conclusion.)*

---

# 3. pyiqa 0.1.16 — new metrics (released 2026-07-08, Facet is on 0.1.15.post2)

Verified from the GitHub releases API and the main-branch `default_model_configs.py`.

| Metric | Added | Mode | Source | Licence | Facet relevance |
|---|---|---|---|---|---|
| `qrealign{,-mini,-lite,-pro}` | Jun 2026 | NR, range 0–1 | Q-ReAlign | weights apache-2.0 / repo unlicensed | **See finding #1 — the reason to upgrade** |
| `fgresq`, `fgresq_pair` | May 2026 | NR / FR | [sxfly99/FGResQ](https://github.com/sxfly99/FGResQ), AAAI 2026, [arXiv 2508.14475](https://arxiv.org/abs/2508.14475) | **Apache-2.0** (verified) | **SKIP — wrong domain.** Fine-grained IQA *for perceptual image restoration* (ranking super-resolved/restored outputs). Facet scores camera originals, not restoration outputs. |
| `metaiqa` | 2026 | NR, range 0–1 | MetaIQA, CVPR **2020** | — | SKIP — a 2020 model, well below TOPIQ. |

Also already present in Facet's installed 0.1.15.post2 but **unused**, worth noting:
`afine_nr` / `afine_fr` / `afine_all` / `afine_all_scale` from
[A-FINE](https://github.com/ChrisDud0257/AFINE) (CVPR 2025, **Apache-2.0**, weights on Google
Drive). I initially searched for a metric named `afine` and found none — the registered names
are `afine_*`. A-FINE's premise is *relaxing the perfect-reference assumption*, i.e. it is
fundamentally a full-reference/comparative model; only the naturalness branch is exposed as
NR. **Not a TOPIQ replacement** for Facet's no-reference use case. Note: pyiqa's v0.1.15
release notes describe `afine` as "for No-Reference image quality assessment", which
mis-describes the paper — do not take that at face value.

**Upgrade risk for `pyiqa>=0.1.16`:** the release notes list no breaking changes; changes are
additive plus robustness fixes (`qalign`/`compare2score` transformers-compat, centralised
`clip_imports`, lazy dataset/model loading, `InferenceModel` input validation). v0.1.15 had
already bundled the full Q-Align architecture in-package. Low risk, but Facet's registered
metric set should be smoke-tested after the bump since `clip_imports` refactored CLIP loading
paths — which `liqe`/`clipiqa` depend on.

---

# 4. FACE IMAGE QUALITY — a strong, weights-free option

## VLM-FIQA (FG 2026) — use Facet's *existing* VLM as a zero-shot face-quality estimator

**Name:** "Employing Vision-Language Models for Face Image Quality Assessment"
**Authors:** Erdi Sarıtaş, Eren Onaran, Vitomir Štruc, Hazım Kemal Ekenel (ITU / Ljubljana / NYU Abu Dhabi)
**Venue/date:** 2026 Int. Conf. on Automatic Face and Gesture Recognition (FG), camera-ready
April 2026; arXiv **2605.17489** (2026-05-17).
**Code:** https://github.com/ThEnded32/VLM4FIQA — **MIT licence** (verified via GitHub API),
last push 2026-04-15. Contents are an *analysis/evaluation pipeline*
(`analysis_evr.py`, `analysis_scface.py`, `report_*.py`, `run_all.py`), **not** a model.
**Two-source status: VERIFIED** — the FG camera-ready PDF and the arXiv listing agree.

**Measured results — Table I, accumulated partial AUC on LFW (ArcFace, FMR=1e-3). LOWER IS BETTER:**

| Method | AUC@1% | AUC@5% | AUC@10% | AUC@20% |
|---|---|---|---|---|
| *Supervised / specialised baselines* | | | | |
| SDD-FIQA | 0.00091 | 0.00376 | 0.00622 | 0.00833 |
| ViT-FIQA | 0.00092 | 0.00372 | 0.00627 | 0.00856 |
| FaceQAN | 0.00092 | 0.00375 | 0.00638 | 0.00891 |
| eDifFIQA | 0.00092 | 0.00381 | 0.00649 | 0.00903 |
| *Zero-shot VLMs (Simple prompt)* | | | | |
| QWEN2.5-72B | 0.00092 | 0.00381 | 0.00624 | 0.00850 |
| **QWEN2.5-7B** | 0.00092 | 0.00378 | 0.00657 | 0.00898 |
| QWEN2.5-32B | 0.00092 | 0.00379 | 0.00659 | 0.00936 |
| QWEN2-7B | 0.00092 | 0.00382 | 0.00644 | 0.00937 |
| Phi-4 | 0.00094 | 0.00399 | 0.00703 | 0.01016 |
| Gemma-3 | 0.00097 | 0.00437 | 0.00779 | 0.01127 |
| Idefics | 0.00097 | 0.00485 | 0.00971 | 0.01555 |

Zero-shot Qwen VLMs land **inside the spread of purpose-built supervised FIQA models** at 1%
and 5% rejection, degrading modestly at 10–20%.

**Table III, clean-image trustworthiness (false-positive degradation calls):** QWEN2.5-7B is
the most reliable detector — **87.9%** of clean images correctly called degradation-free (QS
94.8), vs QWEN2-7B 75.7% and QWEN2.5-32B only **50.9%** (hallucinates artefacts on ~half of
clean images). Bigger is *not* better here.

**Reusable prompt design (the actual deliverable):** role = "expert image quality assessor for
face images", instruction = "evaluate the image quality for facial analysis", strict JSON
`{"Quality Score": <0-100>}`. Plus an attribute-classification variant returning
Sharpness (Clear / Slightly- / Moderately- / Strongly Blurred), Resolution (High/Medium/Low/
Very Low), Lighting (Balanced + Dark/Bright intensities), Compression (None/Minimal/Moderate/
Severe). Prompt-phrasing ablation (Table II): the **7B-class model scored best with
"Reliability"- and "Utility"-framed prompts**, while the 32B was phrasing-invariant — smaller
models need explicit semantic cues.

**⚠️ Two honest caveats:**
1. **The smallest model evaluated was ~4–7B** (Gemma-3-4B, Phi-4-6B, QWEN2-7B). Facet runs
   Qwen3.5-VL **2B/4B**. The paper's own conclusion is that *architecture matters more than
   parameter count* and that smaller models are more prompt-sensitive — and Gemma-3-4B was
   among the worst performers. **Extrapolating these results to Qwen3.5-VL-2B is NOT
   supported by the paper.** This must be measured locally, not assumed.
2. **The evaluation metric itself is under attack.** [arXiv 2607.22752](https://arxiv.org/abs/2607.22752)
   (2026-07-23), "Beyond Error-vs-Discard Characteristic", shows the EDC protocol used for
   the table above has "fundamental limitations: Test-Set Divergence and Threshold Drift,
   which together limit the reliability and comparability of FIQA methods", across 5 datasets
   / 4 FR models / 15 FIQA methods. So the AUC deltas above should be read as *rough
   equivalence*, not a ranking.

Also note the whole benchmark is **biometric utility** (is this face usable for recognition),
which is related to but not identical with Facet's question (is this a good photo of a
person). **No head-to-head number vs Facet's incumbent `topiq_nr-face` exists** — TOPIQ
NR-Face was not among the 15 baselines. UNVERIFIED gap.

**Integration sketch:** zero new weights, zero new VRAM — this is the appeal. Facet already
loads Qwen3.5-VL for tagging/captioning and already has a structured-prompt path in
`models/vlm_backend.py` + `models/vlm_tagger.py`, and already has per-face crops from the
InsightFace pipeline in `analyzers/face.py` / `faces/`. The work is a new prompt template
returning the strict-JSON quality score plus the four attribute fields, run over existing face
crops, landing next to the appearance-based eyes/smile signals in `analyzers/face_blendshapes.py`.
Config would sit under the existing `face_detection` block. Applies to **16gb/24gb profiles
only** (legacy/8gb have no local VLM). The genuine win is *explainability* — Facet could
finally say "rejected: strongly blurred, low resolution" instead of emitting an opaque scalar,
which fits the viewer's existing capsule/critique surfaces. Ship only behind a local
validation against `topiq_nr-face` on Facet's own faces, given caveat (1).

## Other FIQA papers surfaced (arXiv sweep, all post-2026-04-15)

`EX-FIQA` (2604.22842) and `ATTN-FIQA` (2604.22841), both 2026-04-21; `PreFIQs` (2605.13396).
None triaged in depth — all are academic FIQA aimed at biometric utility, and none showed
released weights on a first pass. **Not recommended**: Facet's need is photo-quality, not
recognition-utility, and the VLM-FIQA route above achieves the same end with no new model.

---

# 5. NEW IQA / AESTHETICS PAPERS (arXiv sweep, May–Aug 2026) — triaged, nothing shippable

Swept via the arXiv API across `cs.CV` for no-reference/blind IQA, image aesthetics, cropping,
and face image quality, filtered to ≥ 2026-04-15.

| Paper | Date | Weights / licence | Verdict |
|---|---|---|---|
| **MR-IQA** — Unified Margin View of Regression and Ranking for BIQA, [2606.29760](https://arxiv.org/abs/2606.29760), [repo](https://github.com/RobinY99/MR-IQA) | 2026-06-29 | **MIT**, weights at [RobinY99/MR-IQA](https://huggingface.co/RobinY99/MR-IQA) (single `model.safetensors`), last mod 2026-06-30 | **INVESTIGATE-weak.** Licence and weights are clean, but **40 HF downloads / 2 GitHub stars**, and I found **no published SRCC table vs TOPIQ/LIQE** in the README. Unproven. |
| **RED-Aes** — Relative Edit-induced Difference for generalizable IAA, [2606.05778](https://arxiv.org/abs/2606.05778) | 2026-06-04 | No weights found | SKIP |
| GLIA — Global-Local Adaptive Interaction for BIQA, [2605.17748](https://arxiv.org/abs/2605.17748) | 2026-05-18 | No weights found | SKIP |
| Resolution-agnostic IQA w/ Quality-aware Saliency, [2608.01730](https://arxiv.org/abs/2608.01730) | 2026-08-03 | No weights found | SKIP (too new) |
| Spatially Localized Degradation Embeddings for IQA, [2606.29162](https://arxiv.org/abs/2606.29162) | 2026-06-28 | No weights found | SKIP |
| **PRAC** — Personalized IAA, ACM MM 2026, [2607.15752](https://arxiv.org/abs/2607.15752), [repo](https://github.com/yzc-ippl/PRAC) | 2026-07-17 | **No code**: repo is `PRAC.png, README.md, docs` only; no licence | SKIP — paper-only. |
| XPASS-Vis — cross-domain PIAA *dataset*, [2606.15629](https://arxiv.org/abs/2606.15629) | 2026-06-14 | dataset, not a model | Note only |
| Zero-shot PIAA w/ Profile-aware MLLM, [2604.17233](https://arxiv.org/abs/2604.17233) | 2026-04-19 | not triaged | Note only |

**Corroborating negative evidence — the Hugging Face side is quiet too.** I queried the HF
models API for `image quality assessment`, `aesthetic predictor` and `aesthetic score`, sorted
by downloads, filtered to models modified since 2026-04-01. The *entire* result set was two
models, both with **0 downloads** (`topdan/aesthetic-scorer-v1-beta`, 2026-05-11;
`mikebrave/dinov3-vitb-aesthetic-scorer`, 2026-06-16) — hobby projects, no model cards of
substance. There is no trending open-weight aesthetic/IQA model this cycle that the arXiv
sweep missed.

**Bottom line: no NR-IQA model published May–Aug 2026 clears the bar of "beats TOPIQ *and*
has downloadable weights *and* has a usable licence *and* has corroborated numbers."** The
only IQA movement that matters this cycle is Q-ReAlign (finding #1), and it arrives via pyiqa
rather than as a paper.

## A cautionary datapoint for Facet's VLM critique feature

**Visual Aesthetic Benchmark (VAB)** — "Can Frontier Models Judge Beauty?",
[arXiv 2605.12684](https://arxiv.org/abs/2605.12684), submitted **2026-05-12**, 17 authors.
Licence **CC BY-NC-ND 4.0** (benchmark/dataset, non-commercial — so *not usable inside Facet*,
but usable as evidence).

Findings, quoted: across "20 frontier MLLMs and six dedicated visual-quality reward models",
"the strongest system identifies both the best and the worst image correctly across three
random permutations of the candidate order in only **26.5%** of tasks, far below the **68.9%**
achieved by human experts." Separately, in a study with eight expert annotators,
"score-derived rankings align poorly with the same annotators' direct comparisons, while
direct ranking yields substantially higher inter-annotator agreement."

**Two implications for Facet, both actionable:**
1. Do not expand the VLM's role into *authoritative* aesthetic ranking. Facet's design —
   VLM for tagging/captioning/critique text, dedicated IQA models for the numbers — is the
   correct split, and this is external evidence for keeping it.
2. The scalar-vs-comparison result is a direct endorsement of Facet's **pairwise comparison**
   subsystem (`comparison/`, `comparisons` table, learned scores) over absolute scoring for
   capturing user preference. Worth citing if that subsystem's priority is ever questioned.

---

# 6. RUNTIME / DEPENDENCY STATE

## transformers 5.x — Facet is already on 5.2.0; one real inconsistency found

v5.0.0 landed **2026-01-26**. The breaking changes that could touch Facet's SigLIP2 /
BiRefNet / Qwen-VL loading paths: TF/Flax removal, `torch_dtype`→`dtype` rename, quantisation
shortcuts (`load_in_4bit=`) removed in favour of explicit `BitsAndBytesConfig`,
`AutoModelForVision2Seq`→`AutoModelForImageTextToText`, `AutoFeatureExtractor`→
`AutoImageProcessor`, and fast-only image processors (requires torchvision).

**I grepped Facet's source for every removed API. Result — Facet is clean except one file:**

| Removed/renamed API | Occurrences in Facet |
|---|---|
| `AutoModelForVision2Seq` | 0 |
| `AutoFeatureExtractor` | 0 |
| `AutoModelWithLMHead` | 0 |
| `load_in_4bit` / `load_in_8bit` | 0 |
| `torch_dtype` | **9** |

Of the 9 `torch_dtype` hits, 8 are benign — they are Facet's own *config key name*
(`config/scoring_config.py:695`, `models/model_manager.py:116-117`,
`models/vlm_tagger.py:179-180`) and both call sites correctly pass the new
`dtype=` kwarg (`models/model_manager.py:121`, `models/vlm_tagger.py:199`).

**The outlier is real, and it sits in the SigLIP 2 path:**

```
api/routers/search.py:185-189
    if backend == 'transformers':
        from transformers import AutoModel, AutoTokenizer
        logger.info(f"Loading SigLIP text encoder: {model_name}")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name, torch_dtype=torch.float32).to(device)
```

This is live code — the **SigLIP 2 text-encoder load for `/api/search`**, i.e. it only runs on
the 16gb/24gb profiles (`backend == 'transformers'`), which is why a break here would surface
as "semantic search is down on high-VRAM profiles" rather than a scan failure.

This is the only site still passing the **renamed kwarg** to `from_pretrained`. I verified
empirically against the installed transformers 5.2.0 by reading
`PreTrainedModel.from_pretrained`'s source:

```
torch_dtype = kwargs.pop("torch_dtype", None)  # kept for BC
# For BC on torch_dtype argument
if torch_dtype is not None:
    dtype = dtype if dtype is not None else torch_dtype
```

So it **still works today** on 5.2.0 via an explicit backward-compat shim — this is not a live
bug. But it is explicitly labelled "kept for BC", it is inconsistent with the two other call
sites in the same codebase, and it is exactly the kind of shim that gets dropped in a 5.x
minor. **Recommended: a one-line change to `dtype=torch.float32`.** Low risk, low effort,
removes a latent break. *(Static + tooling claim, both verified this session; I did not
execute the search endpoint itself.)*

### Loading test actually run (offline, against the local HF cache)

I closed most of this gap rather than leaving it assumed. Ran with `HF_HUB_OFFLINE=1` on
transformers 5.2.0, exercising the two things v5 actually changed (config parsing and the
fast-only image processors):

| Model | AutoConfig | AutoImageProcessor | AutoProcessor |
|---|---|---|---|
| `Qwen/Qwen3.5-2B` | OK → `Qwen3_5Config` | OK → `Qwen2VLImageProcessorFast` | OK → `Qwen3VLProcessor` |
| `Qwen/Qwen3-VL-2B-Instruct` | OK → `Qwen3VLConfig` | OK → `Qwen2VLImageProcessorFast` | OK → `Qwen3VLProcessor` |
| `ZhengPeng7/BiRefNet_dynamic` | OK → `BiRefNetConfig` | FAIL (OSError) | FAIL (ValueError) |

**The Qwen paths are clean** — and note the resolved class is `...ImageProcessorFast`,
i.e. the v5 fast-only image-processor change is already satisfied.

**The BiRefNet failures are expected and harmless, verified not assumed:** Facet never asks
for an HF processor for saliency. `models/saliency_scorer.py:94-105` loads via
`AutoModelForImageSegmentation.from_pretrained(self.model_name, trust_remote_code=True)` and
builds its own preprocessing with **torchvision** (`T.Compose([T.Resize(...), ...,
T.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225])])`). That call site also passes no
dtype kwarg at all, so it is unaffected by the `torch_dtype` rename.

**Still genuinely unverified:**
- Full **weight** loading and forward-pass correctness (I loaded configs/processors, not
  `.safetensors`). `UNVERIFIED — needs a real scoring pass.`
- **SigLIP 2 NaFlex.** `google/siglip2-so400m-patch16-naflex` (the configured
  `models.clip.model_name`) is **not in the local HF cache** — the cache holds only SigLIP *1*
  timm checkpoints (`timm/ViT-SO400M-14-SigLIP-384`, `timm/ViT-L-16-SigLIP-256`) plus
  `laion/CLIP-ViT-L-14-...`. So the 16gb/24gb embedding path could not be tested offline here.
  `UNVERIFIED — needs a machine where the SigLIP 2 weights have been fetched.` This is also
  the exact path the `search.py:189` fix above touches.

## torch — nothing to chase

Facet runs **2.10.0+cu128**, which is current. 2.9 (Oct 2025) brought torch.compile gains
mostly on aarch64 CPU plus small-batch CPU utilisation; 2.10 added **Combo-kernels horizontal
fusion in TorchInductor** (fuses independent ops into one GPU kernel, reducing launch
overhead), Python 3.14 `torch.compile` support, and ROCm/Intel GPU work. The combo-kernel
fusion is the only item with plausible relevance to Facet's many-small-model batched inference
on consumer GPUs, and Facet *already has it*. **No action.**

## bitsandbytes 0.50 — safe upgrade with a real inference win

Facet is on **0.49.1**; PyPI's latest is **0.50.0, uploaded 2026-07-24** (Facet is also behind
an intermediate `0.49.2`, 2026-02-16). 0.50 brings **a new fused 4-bit GEMM for inference on
CUDA and ROCm**,
faster CPU ops on x86-64/ARM64, reduced host-side overhead, an improved Apple Silicon backend,
Windows-on-ARM CPU support, and a oneAPI 2026 build.

Breaking changes, checked against Facet's usage: minimum **PyTorch 2.4** (Facet has 2.10 ✓);
removed the `research` module, non-blockwise (`block_wise=False`) optimizers, legacy dynamic
quantisation functions, and legacy sparse ops (`spmm_coo`, `spmm_coo_very_sparse`).
**Facet uses bitsandbytes only for inference-time 4-/8-bit quantisation** (the `iqa-extended`
extra declares `bitsandbytes>=0.43.0` for Q-Align 4/8-bit) and has **zero occurrences of
`BitsAndBytesConfig`, `load_in_4bit` or `load_in_8bit`** in its own source — quantisation is
delegated to pyiqa. None of the removed APIs are optimizer or sparse paths Facet touches.

**Recommendation:** bump the floor to `bitsandbytes>=0.50` in the `iqa-extended` extra. The
fused 4-bit inference GEMM directly benefits the quantised extended tier at zero code cost.
*(Release-note claim is web-sourced; I did not install and benchmark 0.50 —
`UNVERIFIED — needs a local install + timing run` for the magnitude of the speedup.)*

## DeQA-Score — maintained, but check the licence chain

https://github.com/zhiyuanyou/DeQA-Score — **MIT**, actively pushed **2026-07-11**, 244 stars.
Weights `zhiyuanyou/DeQA-Score-Mix3` (MIT tag, 4,339 downloads). **Caveat:** HF `base_model`
is `MAGAer13/mplug-owl2-llama2-7b`, so the artefact is a **Llama-2 derivative** — an "MIT" tag
on the fine-tune does not obviously override the upstream Llama-2 community licence plus
mPLUG-Owl2 terms. Same class of concern as Q-Align. Another argument for consolidating the
extended tier on Q-ReAlign's Apache-2.0 weights. Note the earlier Facet doc reference to a
`Q-Future/DeQA-Score` repo is wrong — **that path 404s**; the correct owner is `zhiyuanyou`.

---

# 7. EMBEDDING TOWERS — nothing beats SigLIP 2 SO400M. Keep it.

## Most important negative result: **SigLIP 3 does not exist**

Verified two independent ways: (1) an HF API listing of every `google/*` model sorted by
`createdAt` descending back to Jan 2026 contains no SigLIP 3 — Google's newest image-text
encoder is TIPSv2 (2026-04-09), and its May–Aug 2026 output was Gemma 4 variants,
DiffusionGemma, TabFM and Magenta-RT-2; (2) an HF search for `siglip3` returns only 4
unrelated community repos. **Do not assume a SigLIP 3 exists in future passes.**

Same "could not confirm existence" verdict, same method, for: **MetaCLIP 3** (latest is
MetaCLIP 2, Jul/Aug 2025) · **Jina CLIP v3** (latest v2, Nov 2024) · **Nomic Embed Vision v2**
(latest v1.5) · **EVA-CLIP successor** (BAAI has shipped no VL-contrastive model since BGE-VL,
May 2025) · **DFN / AIMv2 successors** (Apple's last vision encoder is `apple/aimv2-*`,
Oct–Nov 2024).

## Candidates

| Model | Date | Licence | Verdict |
|---|---|---|---|
| **TIPSv2** `google/tipsv2-so400m14` ([repo](https://github.com/google-deepmind/tips), arXiv 2604.12012, CVPR 2026) | HF repos 2026-04-09 | **Apache-2.0** (code; other materials CC BY 4.0) | **INVESTIGATE — retrieval only** |
| **PE-Core** `facebook/PE-Core-G14-448` (arXiv 2504.13181) | 2025-04-11, unchanged since | **Apache-2.0** | INVESTIGATE-weak — 2025 model, ~1.9B vision params |
| Jina embeddings v5-omni | 2026-03-31 | **`cc-by-nc-4.0` on every repo in the family** | **SKIP — non-commercial** |
| OpenVision 2 / 3 | Sep 2025 / Jan 2026 | Apache-2.0 | **SKIP — no text tower by construction** |
| EUPE (`facebook/EUPE-ViT-*`) | 2026-03-23 | — | SKIP — no text tower, edge-distillation focus |
| Muse Glimmer 30B | 2026-08-09 | Apache-2.0 | SKIP — VLM vision tower, not a contrastive dual encoder |
| Qwen3-VL-Embedding 2B/8B | Jan 2026 | Apache-2.0 | INVESTIGATE-weak — retrieval only, heavy |

**TIPSv2 head-to-head (paper Table 6, giant scale):**

| Model | COCO I→T | COCO T→I | Flickr I→T | Flickr T→I | 0-shot ImageNet |
|---|---|---|---|---|---|
| SigLIP 2 g/16 (incumbent family) | 72.8 | 56.1 | 95.4 | 86.0 | **85.0** |
| PE-core G/14 | 75.4 | 58.1 | **96.2** | 85.7 | **85.4** |
| TIPSv2 g/14 | **75.7** | **60.7** | 95.1 | 85.9 | 80.7 |

**Why this is not a swap:** TIPSv2 wins retrieval (+2.9 / +4.6 COCO) but **loses zero-shot
ImageNet by 4.3 points**. Facet uses this tower for zero-shot *classification* — tag-prompt
similarity **and** the ExIQA distortion attributes — not only KNN. A 4.3-pt classification
regression is the wrong direction for the majority of Facet's use. TIPSv2 also drops
**NaFlex** (fixed 448², vs SigLIP 2's native aspect ratio), which matters for a photo tool
handling portrait/landscape/panoramic framing. And there is **no SO400m-scale head-to-head**
(Table 15 reports only ImageNet-KNN + retrieval) — `UNVERIFIED` at the size Facet would use.

**Narrow opportunity worth noting:** TIPSv2-SO400m/14 is **dim 1152 — identical to SigLIP 2
SO400M** — so it could be trialled as a *retrieval-only side index* in `photos_vec` with **no
schema change**. That is the only bounded experiment I would endorse here, and only if
semantic search quality is a live complaint.

PE-Core is the only encoder with an independently-measured win over SigLIP 2 on *both* axes
(85.4 vs 85.0 IN, 75.4 vs 72.8 COCO I→T) — and notably that number comes from TIPSv2's paper,
i.e. a competitor, which makes it stronger evidence than a vendor self-report. But it is an
April 2025 model with no update since, and ~1.9B vision params would blow the 16gb profile's
budget. Not worth the disruption.

---

# 8. COMPOSITION & CROPPING — SAMP-Net has no successor; one cropping candidate

**Keep SAMP-Net.** Verified two ways: an arXiv full-text search for `"image composition
assessment"` returns **exactly one** paper — SAMP-Net itself (2104.03133, 2021) — and the
curated `bcmi/Awesome-Aesthetic-Evaluation-and-Cropping` list still shows only KU-PCP (2018)
and CADB (2021) for composition assessment, with its newest cropping entries from 2024.
**Nothing in five years has replaced composition *pattern* classification with shipped
weights.**

| Model | Date | Licence | Weights | Verdict |
|---|---|---|---|---|
| **ProCrop** (AAAI 2026) — [repo](https://github.com/BWGZK-keke/ProCrop), [weights](https://huggingface.co/BWGZK/ProCrop), arXiv 2505.22490 | paper 2025-05-28; **HF weights created 2026-05-15**; last push 2026-06-03 | HF tagged **apache-2.0**, but **GitHub repo has NO LICENSE** (`license: null`) | **Yes** — `procrop_flms_supervised.pth` | **INVESTIGATE** |
| AesCrop (ICCV 2025 WS), arXiv 2510.22528 | 2025-10-26 | CC BY 4.0 (paper only) | **None — no GitHub, no HF** | **SKIP** |
| GAFIC, arXiv 2608.04821 | **2026-08-05** | **No LICENSE file** | Training code only, no checkpoint | **SKIP** |
| COMEX, arXiv 2608.07570 | **2026-08-04** | Paper **CC BY-NC-ND 4.0** | No repo, no release statement | **SKIP** |
| CROP, arXiv 2605.12545 | 2026-05-09 | — | None | SKIP |
| GenCrop | 2023-12-28 | BSD-3-Clause | **"Coming soon!"** | **SKIP** (see §2b) |

**Note — GenCrop was independently confirmed dead by two separate investigations this
session** (my direct GitHub-API check and this lane's survey), which is the kind of
cross-verification the watch-list deserved.

**ProCrop assessment:** the only shippable new artefact in this area. FLMS **IoU 0.843**
(README states it matches paper Table 3). Two real caveats before anyone gets excited:
1. **Licence split** — Apache-2.0 on the HF weights but *no LICENSE on the GitHub code*, so
   the code is all-rights-reserved by default. Same shape as the Q-ReAlign issue.
2. **Inference is not a single forward pass.** It needs Conditional DETR + ResNet-50 **plus a
   SAM-embedding Faiss retrieval index over a professional-photo reference database** plus
   CLIP at inference time. That is a heavy new subsystem for a feature Facet does not
   currently have, and only one checkpoint (FLMS) is published — no GAICD/CPC.

No head-to-head vs SAMP-Net exists, and none is meaningful: crop-box regression and
composition-pattern classification are different tasks. ProCrop would be a *new* capability,
not an upgrade. Given Facet has no cropping feature today and the roadmap is already full,
I would not start here.

---

# 9. VLMs (2-8B class) — nothing in-window beats Qwen3.5-2B/4B. Keep them.

## Naming correction, independently confirmed twice

**There are no `Qwen/Qwen3.5-VL-*` repos.** The task brief (and Facet's `CLAUDE.md`) describe
the taggers as "Qwen3.5-VL-2B/4B"; the actual models are **`Qwen/Qwen3.5-2B` and
`Qwen/Qwen3.5-4B`**, which are *natively* multimodal. Confirmed three ways this session:
1. `scoring_config.json` declares `models.qwen3_5_2b.model_path = Qwen/Qwen3.5-2B`.
2. The local HF cache contains `models--Qwen--Qwen3.5-2B` (no `-VL` variant).
3. My offline load test resolved `Qwen/Qwen3.5-2B` → `Qwen3_5Config` with
   `Qwen3VLProcessor` + `Qwen2VLImageProcessorFast` — i.e. vision is built in, no `-VL`
   suffix needed.

This also *strengthens* finding #1: Q-ReAlign's HF card declares `model_type: qwen3_5`, the
exact config class my local test resolved — so it is genuinely the same family Facet already
loads, despite its `base_model` field nominally reading `Qwen/Qwen3.5-VL`.

**Baseline scores (official cards):** Qwen3.5-2B — MMMU-Pro 50.3, MMBench 83.3 ·
Qwen3.5-4B — MMMU-Pro 66.3, MMBench 89.4, MMMU 77.6.

**Leaderboard caveat:** the OpenCompass OpenVLM leaderboard was last updated **2025-09-17** and
contains none of these models — unusable as a cross-check this cycle.

## Candidates

| Model | Date | Licence | Verdict |
|---|---|---|---|
| [`baidu/ERNIE-Image-Aes`](https://huggingface.co/baidu/ERNIE-Image-Aes) (arXiv 2605.25347) | HF 2026-05-18 ✅ in window | **apache-2.0** | **INVESTIGATE** — aesthetic axis only |
| [`microsoft/Mage-VL`](https://huggingface.co/microsoft/Mage-VL) (arXiv 2607.24904) | 2026-07-25 ✅ | **apache-2.0** | **INVESTIGATE** — only competitive new generalist |
| [`moondream/moondream3.1-9B-A2B`](https://huggingface.co/moondream/moondream3.1-9B-A2B) | 2026-06-30 ✅ | ⚠️ **custom "Moondream Model License 1.0"** (non-SPDX) | INVESTIGATE — structured tagging niche |
| `google/gemma-4-26B-A4B-it` | **2026-04-02 — pre-window** | apache-2.0 (a real change from Gemma ToU) | INVESTIGATE (deferred) — **blocked by the transformers cap** |
| Gemma 4 E4B-it / E2B-it | 2026 | apache-2.0 | **SKIP — size-matched competitors LOSE** (MMMU-Pro 52.6 vs 66.3; 44.2 vs 50.3, Google's own numbers) |
| `openbmb/MiniCPM-V-4.6` | 2026-05-11 | apache-2.0 | SKIP — vendor claims *parity*, not a beat; numbers only in unverifiable chart images |
| `LiquidAI/LFM2.5-VL-3B` | 2026-08-11 | ⚠️ **LFM Open License v1.0 — commercial use barred above $10M revenue** | **SKIP** — and its own card shows Qwen3.5-4B winning 6/11 (MMMU-Pro 60.9 vs 30.5) |
| `meta-models/Muse-Glimmer-30B` | 2026-08-10 | apache-2.0 | SKIP — out of class. **Trap:** the `-assistant` 2.5B variant is a speculative-decoding drafter with **no vision tower** |
| CapRL-Video-4B, Unlimited-OCR, MiniMax-M3, Kimi-K3, Step-3.7-Flash, Ovis2.6-80B, Nemotron-Diffusion-VLM | — | mixed / restrictive | SKIP — wrong task, out of class, or restrictive licence |

**ERNIE-Image-Aes detail:** 7.94B, ~16 GB bf16 (24gb profile only). ERIA-1K **SRCC 0.7445 /
PLCC 0.7598** vs ArtiMuse 0.4277 and LAION-Aesthetic 0.2944. **Critically: there is no
comparison to TOPIQ, and Facet's "TOPIQ 0.93 SRCC" is on entirely different data — the numbers
are NOT comparable.** Its benchmark is also ~50% non-photography (anime/design/web), which is
a poor match for Facet's corpus. Output is a bare 1-10 score, no JSON, no critique prose.

**Mage-VL detail:** 4.74B (Qwen3-4B backbone + from-scratch Mage-ViT), ~9.5 GB bf16.
MMBench-EN 84.02, DocVQA 95.14, OCRBench 81.80 — each slightly above **Qwen3-VL-4B**, i.e. the
*previous* generation. **No head-to-head vs Qwen3.5-4B exists**, and Qwen3.5-4B's MMMU-Pro 66.3
suggests the real gap is larger than the card implies. Multi-image support is contradictory
across sources (`UNVERIFIED`); JSON output undocumented.

## Could not confirm existence (explicit negatives — do not re-search blindly)

InternVL 4.x / any post-Aug-2025 InternVL · MiniCPM-V 5.x · Ovis 3 · Kimi-VL successor ·
**Qwen3.5-VL point release / Qwen3.6-VL / Qwen4-VL** · Pixtral 2 · SmolVLM 3 / Idefics
successor · Florence-3 · Phi-5-multimodal · Seed-VL open weights (API-only) · Hunyuan-Vision
open weights ("planned", never shipped) · DeepSeek-VL3 · new general Molmo · Llama vision
successor.

## The honest upgrade path is out-of-window

Since nothing in May–Aug 2026 beats the baseline: **`Qwen/Qwen3.5-9B`** (March 2026,
apache-2.0, MMMU-Pro **70.1**, MMBench **90.1**) is the zero-integration-risk upgrade — same
family, same loader, no transformers change, beats Gemma 4 12B. It needs ~19 GB bf16, so it is
a **24gb-profile-only** option. Not new, but it is the answer to the underlying question.

## Two cross-cutting constraints (both verified against the repo)

1. **The `transformers<5.3` cap gates every Gemma option** (Gemma 4 needs ≥5.5). Verified in
   `requirements.txt:15` and `pyproject.toml:65`, with the reason documented in-line.
2. **Facet has no 4-bit load path.** I grepped independently: **zero** occurrences of
   `BitsAndBytesConfig`, `load_in_4bit` or `load_in_8bit` anywhere in Facet's source —
   quantisation is entirely delegated to pyiqa. So *every* "fits at 4-bit" claim above
   requires new loader plumbing in `models/model_manager.py` / `models/vlm_tagger.py` that
   does not exist today. This is the hidden cost behind every MoE candidate.
3. **Cheap A/B path exists:** `models/vlm_backend.py` already supports Ollama / OpenAI-compatible
   backends, so any candidate can be evaluated **without touching the transformers pin**.

---

# 10. RANKED SHORTLIST

| # | Item | Verdict | One-line justification |
|---|---|---|---|
| 1 | **Sync the venv to the committed lockfile** (`pyiqa` 0.1.15.post2→0.1.16, `bitsandbytes` 0.49.1→0.50.0) | **SHIP** | Zero research risk and zero dependency negotiation — the repo **already pins both**; the venv is simply stale, and syncing is what unlocks items #2 and #4. |
| 2 | **Q-ReAlign** (`qrealign-mini` 0.8B, already reachable once #1 lands) | **SHIP** *(hard-gated on a local A/B)* | Apache-2.0 weights verified via HF API, 2.21 GB, 26.7 img/s on a 4090, avg SRCC 0.879–0.896 vs Q-Align 0.869 — and it retires the **non-commercial S-Lab** Q-Align; but there is **no paper and no independent replication**, so the A/B is a precondition, not a formality. |
| 3 | **`torch_dtype=` → `dtype=` at `api/routers/search.py:189`** | **SHIP** | One-line fix in the SigLIP 2 text-encoder path for `/api/search`; verified as the codebase's only remaining transformers-v5 BC shim (upstream marks it `# kept for BC`) while both sibling call sites already use `dtype=`. |
| 4 | **VLM-FIQA prompt** (zero-shot face quality on the already-loaded Qwen3.5 tagger) | **INVESTIGATE** | MIT pipeline, peer-reviewed (FG 2026), **zero new weights and zero new VRAM**, and it buys explainable per-face verdicts — but the paper never tested below ~4B and its EDC metric is itself under published attack, so measure against `topiq_nr-face` first. |
| 5 | **Deprecate `aesthetic_v25`** (aesthetic-predictor-v2-5) | **INVESTIGATE** | **AGPL-3.0** against Facet's MIT in a project whose main surface is a network service, plus **20 months without a commit** spanning the entire transformers 4→5 transition; item #2 supersedes it functionally. |

**Deliberately NOT in the top 5, despite being interesting:** TIPSv2 (retrieval-only gain, but
−4.3 pts zero-shot ImageNet is the wrong direction for Facet's tag-prompt and ExIQA use, and
it drops NaFlex) · ProCrop (only shippable cropping weights, but needs a SAM+Faiss+CLIP
subsystem for a feature Facet doesn't have) · Qwen3.5-9B (the real VLM upgrade, but
out-of-window and 24gb-only) · ERNIE-Image-Aes / Mage-VL (both apache-2.0 and plausible, but
**neither has a head-to-head against Facet's actual incumbents**).

**Explicit SKIPs — close these, do not revisit:** DSL-FIQA (no LICENSE, 23 months dormant) ·
GenCrop (one commit ever; "Coming soon!" for 32 months) · **SigLIP 3 / MetaCLIP 3 / Jina CLIP
v3 / Qwen3.5-VL point release / InternVL 4.x / Florence-3 / Pixtral 2 — verified NOT to
exist** · FGResQ (Apache-2.0 and real, but scoped to image *restoration* — wrong domain) ·
MetaIQA (CVPR 2020) · A-FINE (full-reference by design) · AesCrop/GAFIC/COMEX/CROP (no
weights) · PRAC/RED-Aes/GLIA (no weights) · Jina v5-omni & LFM2.5-VL-3B (non-commercial
licences) · VAB (CC BY-NC-ND benchmark, not a model).

---

## Net assessment

**Three of the four model families Facet uses are already at the frontier and should not be
touched.** SigLIP 2 SO400M is unbeaten (and SigLIP 3 does not exist). SAMP-Net has had no
successor in five years. Qwen3.5-2B/4B beat every in-window VLM at their size — several
candidates marketed as upgrades measurably *lose* to them.

**The one real opportunity is licence hygiene, not accuracy.** Facet's two most legally
awkward optional dependencies — **S-Lab non-commercial Q-Align** and **AGPL-3.0,
20-months-unmaintained aesthetic-predictor-v2-5** — become simultaneously replaceable by a
single Apache-2.0 model that is smaller, faster, and scores better, and that is *already
reachable through a dependency the repo has already pinned*. The cost is a venv sync plus a
config entry.

**The most valuable thing this pass produced may be the negative results.** "SigLIP 3 does not
exist", "no `Qwen3.5-VL-*` repo exists", "SAMP-Net has no successor", and "DSL-FIQA/GenCrop are
dead" are each worth more than another speculative candidate, because they stop future passes
from re-searching ground already covered.

## Caveats on this pass itself

- **WebSearch budget exhausted (200/200).** Later verification was done via direct GitHub /
  HF / PyPI / arXiv API calls and WebFetch, which is generally *stronger* evidence than search
  snippets — but a few threads (a second source for Q-ReAlign's numbers) could not be pursued.
- **No model weights were actually loaded or benchmarked.** Config/processor loading was
  tested offline; forward-pass correctness and every SRCC/throughput figure quoted here remain
  vendor claims. `UNVERIFIED — needs a local benchmark run.`
- **SigLIP 2 NaFlex could not be tested** — it is absent from this machine's HF cache.
- Recurring pattern worth carrying forward: **Q-ReAlign, ProCrop and DSL-FIQA all show
  permissive-or-absent licence metadata that disagrees between their HF weights and their code
  repos.** Always check both; an HF `apache-2.0` tag says nothing about the GitHub repo.
