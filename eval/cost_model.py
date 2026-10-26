"""B5: monthly cost against workload: the serverless design as built vs fixed-capacity alternatives.

Usage (from the repository root, evaluation virtualenv):
    python eval/cost_model.py          # writes eval/results/b5-cost-<date>/{summary.md,summary.json,cost-vs-users.png}

Every number below is either a dated list price (PRICES, from the AWS public price-list files for ap-southeast-1
and the sources named), a measurement from this evaluation (MEASURED, with the result it comes from), or a usage
assumption (USAGE, stated so it can be challenged). Free tiers are ignored except Cognito's 10,000 MAU (part of the
Lite tier's price), so the serverless figures are an upper bound for a new account. Singapore GST (9%) is added to
AWS charges. LLM tokens are shown separately: SoClaaS is provided by NUS (assumed free to the project), and two
public Bedrock prices show what the same tokens would cost commercially.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USERS = [10, 100, 1_000, 10_000, 100_000]
CHART_USERS = [round(10 ** (1 + i / 20)) for i in range(0, 81)]          # 10 to 100,000, log-spaced

# --- List prices (USD). AWS: public price-list files for ap-southeast-1, publication dates 2026-09-11 to 2026-10-23.
PRICES = {
    "lambda_gb_s_arm": 0.0000133334,          # AWSLambda APS1-Lambda-GB-Second-ARM, tier 1 (2026-10-22)
    "lambda_request": 0.0000002,              # AWSLambda APS1-Request-ARM
    "http_api_request": 0.00000125,           # AmazonApiGateway APS1-ApiGatewayHttpRequest, first 300M (2026-10-13)
    "aurora_acu_hour": 0.20,                  # AmazonRDS APS1-Aurora:ServerlessV2Usage, PostgreSQL (2026-10-20)
    "aurora_storage_gb_month": 0.11,          # AmazonRDS APS1-Aurora:StorageUsage
    "aurora_io_million": 0.22,                # AmazonRDS APS1-Aurora:StorageIOUsage
    "s3_gb_month": 0.025,                     # AmazonS3 APS1-TimedStorage-ByteHrs (2026-10-15)
    "s3_put": 0.000005, "s3_get": 0.0000004,  # AmazonS3 Requests-Tier1 / Tier2
    "logs_ingest_gb": 0.70,                   # AmazonCloudWatch APS1-DataProcessing-Bytes (2026-10-07)
    "logs_store_gb_month": 0.03,
    "cognito_lite_mau": 0.0055,               # AmazonCognito APS1-CognitoLiteMAU tier 1; first 10,000 MAU free (2026-10-20)
    "cognito_free_mau": 10_000,
    "amplify_gb_out": 0.15, "amplify_build_minute": 0.01,   # AWSAmplify APS1-DataTransferOut / BuildDuration (2026-09-11)
    "secret_month": 0.40,                     # AWSSecretsManager (2026-09-11)
    "ecr_gb_month": 0.10,                     # AmazonECR (2026-09-11)
    "gst": 0.09,                              # Singapore GST on AWS services
    # Fixed-capacity alternatives
    "ec2_c7g_xlarge_hour": 0.1666,            # EC2 Linux on-demand, Asia Pacific (Singapore) (2026-10-23)
    "ec2_t4g_medium_hour": 0.0424,
    "rds_pg_m7g_large_hour": 0.234,           # AmazonRDS PostgreSQL Single-AZ db.m7g.large (2 vCPU, 8 GiB)
    "rds_pg_t4g_medium_hour": 0.102,          # db.t4g.medium (2 vCPU, 4 GiB)
    "rds_gp3_gb_month": 0.138,
    "alb_hour": 0.0252, "alb_lcu_hour": 0.008,  # AWSELB Application load balancer (2026-09-11)
    # LLM references (AmazonBedrock price lists for ap-southeast-1, 2026-10-16 and 2026-10-12), per token
    "nova_lite_in": 0.081e-6, "nova_lite_out": 0.324e-6,
    "haiku_45_in": 1.0e-6, "haiku_45_out": 5.0e-6,
}
FX = {"usd_sgd": 1.4310 / 1.1193, "usd_myr": 4.5729 / 1.1193}     # ECB reference rates, 2026-10-23
ON_PREM = {
    "server_myr": 36_835.51,     # Dell PowerEdge R660xs configuration incl. SST, 3-year NBD warranty, dual 800 W PSU
                                 # (dell.com/en-my, per660xs20a, retrieved 2026-10-26)
    "amortise_months": 36,
    "average_watts": 250, "pue": 1.5,          # assumption: a lightly loaded 1U server; office cooling overhead
    "tariff_sgd_kwh": 0.3116,                  # SP Group regulated tariff Q4 2026, 28.59 cents + 9% GST
    "network_sgd_month": 267,                  # Singtel business broadband 100 Mbps with static IP (singtel.com/business)
    "admin_hours_month": 8,                    # assumption: patching, backups, monitoring, incidents
    "admin_sgd_month_salary": 5_000,           # median system administrator base pay (NodeFlair, 2026)
    "employer_cpf": 0.17,
}
ALWAYS_ON_ADMIN_HOURS = 2                      # assumption: OS patching of EC2 instances (RDS is managed)

# --- Measured in this evaluation.
MEASURED = {
    "api_gb_s_per_request": 0.80,      # B3: mean API function duration 0.68–0.94 s at 1,024 MB below saturation
    "log_bytes_per_request": 550,      # gateway access line (~220 B) + Lambda START/END/REPORT (~330 B)
    "acu_floor_when_awake": 1.0,       # B1/B3: one active user holds Aurora at 1 ACU (65–72% CPU)
    "acu_per_rps": 0.19,               # B3 run 2: 18.2 req/s used 86% of 4 ACU
    "pause_after_hours": 0.5,          # Aurora auto-pause after 1,800 s idle (A6)
    # AI tasks (B2): worker GB-s (model time x 0.5 GB), API GB-s (time held in the request x 1 GB), tokens
    "ai": {"fit": {"worker_gb_s": 12.3, "api_gb_s": 2.6, "tokens_in": 3253, "tokens_out": 1141},
           "cover_letter": {"worker_gb_s": 4.9, "api_gb_s": 11.4, "tokens_in": 1054, "tokens_out": 516},
           "tailor": {"worker_gb_s": 1.5, "api_gb_s": 4.4, "tokens_in": 872, "tokens_out": 86}},
    "pull_gb_s": 0.5 * 167 + 0.5 * 13 + 3.0 * 17,   # B4: discovery 167 s, import 13 s at 512 MB; embedding 17 s at 3,008 MB
    "fixed_secrets": 2, "fixed_ecr_gb": 8.1, "aurora_storage_gb": 1.0,
}
# --- Usage assumptions (per active user per month unless stated).
USAGE = {
    "sessions": 8, "requests_per_session": 25,          # browse requests (All jobs, For you, details, tracker, Save/Pass)
    "ai_tasks": {"fit": 1, "cover_letter": 1, "tailor": 1},   # within the 5 free AI uses
    "web_mb_per_session": 2.0,                          # website assets served by Amplify (mostly cached)
    "storage_mb": 5.0,                                  # uploads, documents, exports in S3
    "session_hours": 0.25,
    "waking_hours_month": 480,                          # 16 h a day carry most traffic
    "night_share": 0.05,                                # share of sessions in the other 8 h a day (240 h a month)
    "peak_factor": 3.0,
    "pulls_per_month": 60, "builds_per_month": 30, "build_minutes": 4,
}


def database_hours(users: int) -> float:
    """Hours a month Aurora is running: awake while any session (plus the pause delay) is open, with sessions arriving
    at random (Poisson) in the day and night windows; pulls wake it when it would otherwise be paused."""
    sessions = users * USAGE["sessions"]
    open_window = USAGE["session_hours"] + MEASURED["pause_after_hours"]
    day, night = USAGE["waking_hours_month"], 720 - USAGE["waking_hours_month"]
    awake = (day * (1 - math.exp(-sessions * (1 - USAGE["night_share"]) / day * open_window))
             + night * (1 - math.exp(-sessions * USAGE["night_share"] / night * open_window)))
    pulls = USAGE["pulls_per_month"] * MEASURED["pause_after_hours"] * (1 - awake / 720)
    return min(720.0, awake + pulls)


def serverless(users: int) -> dict:
    requests = users * USAGE["sessions"] * USAGE["requests_per_session"]
    ai = MEASURED["ai"]
    ai_worker_gb_s = users * sum(ai[t]["worker_gb_s"] * n for t, n in USAGE["ai_tasks"].items())
    ai_api_gb_s = users * sum(ai[t]["api_gb_s"] * n for t, n in USAGE["ai_tasks"].items())
    ai_requests = users * sum(USAGE["ai_tasks"].values())
    hours = database_hours(users)
    peak_rps = requests / (USAGE["waking_hours_month"] * 3600) * USAGE["peak_factor"]
    acu = max(MEASURED["acu_floor_when_awake"], MEASURED["acu_per_rps"] * peak_rps)
    lines = {
        "API function": (requests * MEASURED["api_gb_s_per_request"] + ai_api_gb_s) * PRICES["lambda_gb_s_arm"]
                        + (requests + ai_requests) * PRICES["lambda_request"],
        "API Gateway": (requests + ai_requests) * PRICES["http_api_request"],
        "Aurora": hours * acu * PRICES["aurora_acu_hour"] + MEASURED["aurora_storage_gb"] * PRICES["aurora_storage_gb_month"]
                  + requests * 10 / 1e6 * PRICES["aurora_io_million"],
        "AI and pipeline functions": (ai_worker_gb_s + USAGE["pulls_per_month"] * MEASURED["pull_gb_s"]) * PRICES["lambda_gb_s_arm"],
        "S3": users * USAGE["storage_mb"] / 1024 * PRICES["s3_gb_month"] + ai_requests * (2 * PRICES["s3_put"] + 3 * PRICES["s3_get"]),
        "CloudWatch Logs": requests * MEASURED["log_bytes_per_request"] / 1e9 * (PRICES["logs_ingest_gb"] + PRICES["logs_store_gb_month"]),
        "Cognito": max(0, users - PRICES["cognito_free_mau"]) * PRICES["cognito_lite_mau"],
        "Amplify": users * USAGE["sessions"] * USAGE["web_mb_per_session"] / 1024 * PRICES["amplify_gb_out"]
                   + USAGE["builds_per_month"] * USAGE["build_minutes"] * PRICES["amplify_build_minute"],
        "Secrets and images": MEASURED["fixed_secrets"] * PRICES["secret_month"] + MEASURED["fixed_ecr_gb"] * PRICES["ecr_gb_month"],
    }
    aws = sum(lines.values()) * (1 + PRICES["gst"])
    tokens_in = users * sum(ai[t]["tokens_in"] * n for t, n in USAGE["ai_tasks"].items())
    tokens_out = users * sum(ai[t]["tokens_out"] * n for t, n in USAGE["ai_tasks"].items())
    return {"users": users, "requests": requests, "database_hours": round(hours, 1), "acu": round(acu, 2),
            "lines": {k: round(v, 2) for k, v in lines.items()}, "aws_total": round(aws, 2),
            "llm": {"SoClaaS (NUS)": 0.0,
                    "Nova Lite price": round(tokens_in * PRICES["nova_lite_in"] + tokens_out * PRICES["nova_lite_out"], 2),
                    "Claude Haiku 4.5 price": round(tokens_in * PRICES["haiku_45_in"] + tokens_out * PRICES["haiku_45_out"], 2)}}


def shared_services(users: int) -> float:
    """Services every option keeps (sign-in, website, storage, logs, AI worker): from the serverless line items."""
    lines = serverless(users)["lines"]
    keep = ("S3", "CloudWatch Logs", "Cognito", "Amplify", "Secrets and images", "AI and pipeline functions")
    return sum(lines[k] for k in keep)


def admin_usd(hours: float) -> float:
    hourly_sgd = ON_PREM["admin_sgd_month_salary"] * (1 + ON_PREM["employer_cpf"]) / 173
    return hours * hourly_sgd / FX["usd_sgd"]


def always_on(users: int, peak: bool) -> float:
    """Peak-sized: 3 x c7g.xlarge (12 vCPU, the ~11 vCPU B3's 27.5 req/s peak used) behind an ALB, and db.m7g.large
    (8 GiB, about Aurora's 4 ACU). Minimum: one t4g.medium, no load balancer, db.t4g.medium."""
    hours = 730
    if peak:
        compute = 3 * PRICES["ec2_c7g_xlarge_hour"] * hours + PRICES["alb_hour"] * hours + 1 * PRICES["alb_lcu_hour"] * hours
        database = PRICES["rds_pg_m7g_large_hour"] * hours + 20 * PRICES["rds_gp3_gb_month"]
    else:
        compute = PRICES["ec2_t4g_medium_hour"] * hours
        database = PRICES["rds_pg_t4g_medium_hour"] * hours + 20 * PRICES["rds_gp3_gb_month"]
    return round((compute + database + shared_services(users)) * (1 + PRICES["gst"]) + admin_usd(ALWAYS_ON_ADMIN_HOURS), 2)


def on_premise(users: int) -> dict:
    hardware = ON_PREM["server_myr"] / FX["usd_myr"] / ON_PREM["amortise_months"]
    power = ON_PREM["average_watts"] * ON_PREM["pue"] * 730 / 1000 * ON_PREM["tariff_sgd_kwh"] / FX["usd_sgd"]
    network = ON_PREM["network_sgd_month"] / FX["usd_sgd"]
    admin = admin_usd(ON_PREM["admin_hours_month"])
    shared = shared_services(users) * (1 + PRICES["gst"])      # sign-in, website and AI worker stay hosted
    parts = {"hardware (3-year)": hardware, "power and cooling": power, "network": network, "admin time": admin,
             "hosted services kept": shared}
    return {"parts": {k: round(v, 2) for k, v in parts.items()}, "total": round(sum(parts.values()), 2)}


def break_even(series_a, series_b) -> int | None:
    """First user count (on the chart grid) where a stops being cheaper than b."""
    for users, a, b in zip(CHART_USERS, series_a, series_b):
        if a >= b:
            return users
    return None


def chart(path: Path, curves: dict[str, list[float]], marks: dict[str, int | None]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = {"Serverless (as built)": "#2a78d6", "Always-on cloud, peak-sized": "#eb6834",
               "Always-on cloud, minimum": "#1baf7a", "On-premise server": "#eda100"}
    styles = {"Serverless (as built)": "-", "Always-on cloud, peak-sized": "--", "Always-on cloud, minimum": ":",
              "On-premise server": "-."}
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for name, values in curves.items():
        ax.plot(CHART_USERS, values, styles[name], color=colours[name], linewidth=2, label=name, solid_capstyle="round")
        offset = {"On-premise server": 7, "Always-on cloud, peak-sized": -11}.get(name, 7)
        ax.annotate(name, (CHART_USERS[1], values[1]), xytext=(0, offset), textcoords="offset points", va="center",
                    fontsize=8.5, color="#0b0b0b")
    for label, users in marks.items():
        if users:
            y = curves["Serverless (as built)"][CHART_USERS.index(users)]
            ax.plot([users], [y], "o", markersize=8, color="#2a78d6", markeredgecolor="#fcfcfb", markeredgewidth=2, zorder=5)
    low = marks.get("Break-even vs always-on minimum")
    if low:
        y = curves["Serverless (as built)"][CHART_USERS.index(low)]
        ax.annotate(f"Break-even vs minimum always-on: ≈{low:,} users", (low, y), xytext=(10, -22), textcoords="offset points",
                    fontsize=8, color="#52514e")
    high = [marks.get("Break-even vs peak-sized"), marks.get("Break-even vs on-premise")]
    if all(high):
        y = curves["Serverless (as built)"][CHART_USERS.index(high[0])]
        ax.annotate(f"Break-even vs peak-sized cloud ≈{high[0]:,}\nand vs on-premise ≈{high[1]:,} users", (high[0], y),
                    xytext=(-12, 22), textcoords="offset points", ha="right", fontsize=8, color="#52514e")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Active users per month", color="#52514e")
    ax.set_ylabel("Monthly cost, USD (log scale)", color="#52514e")
    ax.set_title("Monthly cost against workload (LLM tokens excluded)", loc="left", fontsize=11, color="#0b0b0b")
    ax.grid(True, which="major", color="#e4e3df", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c9c8c2")
    ax.tick_params(colors="#52514e", labelsize=8.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(loc="lower right", fontsize=8.5, frameon=False)
    ax.set_xlim(CHART_USERS[0], CHART_USERS[-1] * 1.02)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())


def main() -> None:
    rows = [serverless(n) for n in USERS]
    curves = {"Serverless (as built)": [serverless(n)["aws_total"] for n in CHART_USERS],
              "Always-on cloud, peak-sized": [always_on(n, True) for n in CHART_USERS],
              "Always-on cloud, minimum": [always_on(n, False) for n in CHART_USERS],
              "On-premise server": [on_premise(n)["total"] for n in CHART_USERS]}
    marks = {"Break-even vs always-on minimum": break_even(curves["Serverless (as built)"], curves["Always-on cloud, minimum"]),
             "Break-even vs peak-sized": break_even(curves["Serverless (as built)"], curves["Always-on cloud, peak-sized"]),
             "Break-even vs on-premise": break_even(curves["Serverless (as built)"], curves["On-premise server"])}
    out_dir = ROOT / "eval" / "results" / f"b5-cost-{datetime.now(timezone.utc):%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    chart(out_dir / "cost-vs-users.png", curves, marks)
    alternatives = {n: {"always_on_peak": always_on(n, True), "always_on_minimum": always_on(n, False),
                        "on_premise": on_premise(n)} for n in USERS}
    (out_dir / "summary.json").write_text(json.dumps({"prices": PRICES, "fx": FX, "on_prem": ON_PREM, "measured": MEASURED,
                                                      "usage": USAGE, "serverless": rows, "alternatives": alternatives,
                                                      "break_even_users": marks}, indent=2))
    money = lambda v: f"${v:,.2f}" if v < 100 else f"${v:,.0f}"   # noqa: E731
    names = list(rows[0]["lines"])
    lines = ["# B5 cost model: monthly cost by active users (USD, incl. 9% GST on AWS)", "",
             "| | " + " | ".join(f"{n:,} users" for n in USERS) + " |", "|---|" + "---|" * len(USERS)]
    for name in names:
        lines.append(f"| {name} | " + " | ".join(money(r["lines"][name]) for r in rows) + " |")
    lines += [f"| **Serverless AWS total** | " + " | ".join(f"**{money(r['aws_total'])}**" for r in rows) + " |",
              "| Aurora hours running / ACU | " + " | ".join(f"{r['database_hours']:.0f} h / {r['acu']}" for r in rows) + " |"]
    for name in rows[0]["llm"]:
        lines.append(f"| LLM tokens at {name} | " + " | ".join(money(r["llm"][name]) for r in rows) + " |")
    lines += [f"| Always-on cloud, peak-sized | " + " | ".join(money(alternatives[n]["always_on_peak"]) for n in USERS) + " |",
              f"| Always-on cloud, minimum | " + " | ".join(money(alternatives[n]["always_on_minimum"]) for n in USERS) + " |",
              f"| On-premise server | " + " | ".join(money(alternatives[n]["on_premise"]["total"]) for n in USERS) + " |", "",
              "On-premise parts (10,000 users): " + ", ".join(f"{k} {money(v)}" for k, v in alternatives[10_000]["on_premise"]["parts"].items()) + ".",
              "", "Break-even (serverless stops being cheaper): " + "; ".join(f"{k}: {('about ' + format(v, ',') + ' users') if v else 'not within 100,000 users'}"
                                                                          for k, v in marks.items()) + ".",
              "", "Capacity note: the deployed limits serve about 10.7 browse requests/s (B3 run 1); at the usage above, "
              "10,000 active users peak at about " + f"{rows[3]['requests'] / (USAGE['waking_hours_month'] * 3600) * USAGE['peak_factor']:.1f}"
              + " req/s, and 100,000 at about " + f"{rows[4]['requests'] / (USAGE['waking_hours_month'] * 3600) * USAGE['peak_factor']:.0f}"
              + " req/s, which needs the raised limits of B3 run 2 or more."]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
