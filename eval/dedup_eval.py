"""B4: duplicate-removal accuracy, offline, with the production pure functions in job_hunter.ingestion.dedup.

Usage (from the repository root, evaluation virtualenv):
    python eval/dedup_eval.py                       # writes eval/results/b4-dedup-<date>/summary.md and .json

Scores two labelled sets:
* eval/dedup/staging_pairs.json: real pairs from the staging pulls, labelled by reading both postings
  (see "about" in the file). 'unsure' pairs are left out; same-source reposts are reported on their own, because
  the design never merges two rows of one source.
* backend/tests/fixtures/dedup_pairs.json: the 16 synthetic pairs the threshold was tuned on (for comparison).

Each pair is judged with dedup.same_posting on rows built the way import_jobs builds them (company = employer,
match_key from company, title and location). A missed duplicate is explained as "employer/title key differs" or
"descriptions below the threshold".
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from job_hunter.ingestion import dedup  # noqa: E402

STAGING = ROOT / "eval" / "dedup" / "staging_pairs.json"
SYNTHETIC = ROOT / "backend" / "tests" / "fixtures" / "dedup_pairs.json"
THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
GENERIC_EMPLOYER_WORDS = {"asia", "pacific", "group", "global", "international", "technology", "technologies", "solutions",
                          "consulting", "services", "recruitment", "bank", "na", "n", "a"}


def employer_head(company) -> str:
    """First distinctive word of the normalised employer ('IG Group' and 'IG Asia Pte Ltd' both give 'ig')."""
    words = [word for word in dedup.normalise_company(company).split() if word not in GENERIC_EMPLOYER_WORDS]
    return words[0] if words else ""


def what_if(pair: dict, rule: str, threshold: float) -> bool:
    """Alternative rules, for discussion only (production uses dedup.same_posting)."""
    a, b = pair["a"], pair["b"]
    if a["source"] == b["source"]:
        return False
    similarity = dedup.description_similarity(a.get("description"), b.get("description"))
    if rule == "text_only":
        return similarity >= threshold
    if rule == "employer_head_and_text":
        return bool(employer_head(a.get("company"))) and employer_head(a.get("company")) == employer_head(b.get("company")) \
            and similarity >= threshold
    raise ValueError(rule)


def row(side: dict) -> SimpleNamespace:
    company = side.get("company")
    return SimpleNamespace(source=side["source"], source_url=side.get("source_url"), description=side.get("description"),
                           match_key=dedup.match_key(company, side.get("title"), side.get("location")))


def judge(pair: dict, threshold: float) -> dict:
    a, b = row(pair["a"]), row(pair["b"])
    merged = dedup.same_posting(a, b, threshold)
    reason = None
    if not merged and pair["truth"]:
        reason = "employer/title key differs" if a.match_key != b.match_key else "descriptions below the threshold"
    return {"merged": merged, "reason": reason, "similarity": round(dedup.description_similarity(a.description, b.description), 3),
            "same_key": a.match_key == b.match_key}


def scores(pairs: list[dict], threshold: float, rule: str | None = None) -> dict:
    tp = fp = fn = tn = 0
    for pair in pairs:
        merged = judge(pair, threshold)["merged"] if rule is None else what_if(pair, rule, threshold)
        tp += merged and pair["truth"]
        fp += merged and not pair["truth"]
        fn += (not merged) and pair["truth"]
        tn += (not merged) and not pair["truth"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else 0.0 if precision is not None else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1}


def staging_pairs() -> tuple[list[dict], list[dict], int]:
    data = json.loads(STAGING.read_text())["pairs"]
    scored = [{**pair, "truth": pair["label"] == "same"} for pair in data if pair["label"] in ("same", "different")]
    reposts = [pair for pair in data if pair["label"] == "same_source_repost"]
    unsure = sum(pair["label"] == "unsure" for pair in data)
    return scored, reposts, unsure


def synthetic_pairs() -> list[dict]:
    return [{"id": pair["name"], "truth": bool(pair["same"]), "a": pair["a"], "b": pair["b"], "note": pair.get("note", "")}
            for pair in json.loads(SYNTHETIC.read_text())]


def fmt(value) -> str:
    return "–" if value is None else f"{value:.2f}"


def main() -> None:
    staging, reposts, unsure = staging_pairs()
    synthetic = synthetic_pairs()
    threshold = dedup.SIMILARITY_THRESHOLD
    result = {"threshold": threshold, "staging": scores(staging, threshold), "synthetic": scores(synthetic, threshold),
              "sweep": {str(t): scores(staging, t) for t in THRESHOLDS}, "unsure_excluded": unsure,
              "what_if": {rule: {str(t): scores(staging, t, rule) for t in THRESHOLDS}
                          for rule in ("text_only", "employer_head_and_text")},
              "pairs": [{"id": pair["id"], "group": pair["group"], "truth": pair["truth"], "note": pair["note"],
                         "a": f"{pair['a']['source']}: {pair['a']['company']} | {pair['a']['title']}",
                         "b": f"{pair['b']['source']}: {pair['b']['company']} | {pair['b']['title']}",
                         **judge(pair, threshold)} for pair in staging],
              "reposts": [{"id": pair["id"], "merged": dedup.same_posting(row(pair["a"]), row(pair["b"])),
                           "same_key": row(pair["a"]).match_key == row(pair["b"]).match_key,
                           "similarity": round(dedup.description_similarity(pair["a"]["description"], pair["b"]["description"]), 3)}
                          for pair in reposts]}
    out_dir = ROOT / "eval" / "results" / f"b4-dedup-{datetime.now(timezone.utc):%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(result, indent=2))

    s, y = result["staging"], result["synthetic"]
    positives, negatives = s["tp"] + s["fn"], s["fp"] + s["tn"]
    lines = [f"# B4 duplicate removal: accuracy (threshold {threshold})", "",
             "| Set | Pairs | Duplicates | Precision | Recall | F1 | TP / FP / FN / TN |", "|---|---|---|---|---|---|---|",
             f"| Staging pulls (real, labelled) | {len(staging)} | {positives} | {fmt(s['precision'])} | {fmt(s['recall'])} | "
             f"{fmt(s['f1'])} | {s['tp']} / {s['fp']} / {s['fn']} / {s['tn']} |",
             f"| Synthetic fixture (tuning set) | {len(synthetic)} | {y['tp'] + y['fn']} | {fmt(y['precision'])} | {fmt(y['recall'])} | "
             f"{fmt(y['f1'])} | {y['tp']} / {y['fp']} / {y['fn']} / {y['tn']} |", "",
             f"Staging set: {positives} duplicates, {negatives} hard non-duplicates; {unsure} unsure pair left out.", "",
             "Missed duplicates:", "", "| Pair | A | B | Why missed | Description similarity |", "|---|---|---|---|---|"]
    for pair in result["pairs"]:
        if pair["truth"] and not pair["merged"]:
            lines.append(f"| {pair['id']} | {pair['a']} | {pair['b']} | {pair['reason']} | {pair['similarity']:.2f} |")
    false_merges = [pair for pair in result["pairs"] if pair["merged"] and not pair["truth"]]
    lines += ["", f"False merges: {len(false_merges)}." + "".join(f" Pair {p['id']}: {p['a']} / {p['b']}." for p in false_merges), "",
              "Threshold sweep on the staging set:", "", "| Threshold | Precision | Recall | F1 |", "|---|---|---|---|"]
    for t, row_ in result["sweep"].items():
        lines.append(f"| {t} | {fmt(row_['precision'])} | {fmt(row_['recall'])} | {fmt(row_['f1'])} |")
    lines += ["", "What-if rules on the staging set (not in production; P / R / F1):", "",
              "| Threshold | Text similarity only | Same employer head word + text |", "|---|---|---|"]
    for t in THRESHOLDS:
        cells = [result["what_if"][rule][str(t)] for rule in ("text_only", "employer_head_and_text")]
        lines.append(f"| {t} | " + " | ".join(f"{fmt(c['precision'])} / {fmt(c['recall'])} / {fmt(c['f1'])}" for c in cells) + " |")
    merged_reposts = sum(r["merged"] for r in result["reposts"])
    lines += ["", f"Same-source reposts: {len(reposts)} pairs, all identical text; merged {merged_reposts} "
              "(by design two rows of one source never merge)."]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
