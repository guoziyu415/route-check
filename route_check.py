#!/usr/bin/env python3
"""Route check: how often can a small local model answer on its own, and how often is it right when it does?

Sends every labeled example to a running Jeff server (or any server with the same
/v1/systemone request format), records the probability it gives each option, and
writes a JSON file you can drop on the web page to pick a confidence threshold.

Standard library only.

  python3 route_check.py --data data/banking77_routes.jsonl --question data/banking77_question.json
  python3 route_check.py --data my_tickets.jsonl --question my_question.json --out my-results.json
  python3 route_check.py --report results/banking77-jeff-0.8b.json      # threshold table, no server needed

Data file: one JSON object per line with "text" and "label", where label is one of the option keys.
Question file: {"instructions": "...", "criteria": {"1": "first option", "2": "second option"}}
"""
import argparse
import json
import platform
import statistics
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.1.0"
VIEWER_URL = "https://code415.dev/demos/2026-09-29/route-check"


def post(url, body, timeout=60):
    data = json.dumps(body).encode("utf-8")
    for attempt in range(20):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (503, 529):  # loading or busy
                time.sleep(0.5)
                continue
            raise SystemExit("Server answered %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
        except urllib.error.URLError as e:
            raise SystemExit("Cannot reach %s (%s). Is the Jeff server running?" % (url, e.reason))
    raise SystemExit("Server stayed busy.")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def threshold_table(items, out=sys.stdout):
    """Print, for a range of thresholds, how much the small model answers alone and how often it is right."""
    n = len(items)
    by_p = sorted(items, key=lambda x: -x["p"])
    cum, right = [], 0
    for x in by_p:
        right += x["choice"] == x["label"]
        cum.append(right)

    def at(t):
        k = sum(1 for x in by_p if x["p"] >= t)
        return k, (cum[k - 1] / k if k else None)

    out.write("\nthreshold  answered here  right when it does  sent to the big model\n")
    for t in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98):
        k, acc = at(t)
        out.write("  %4.2f       %5.1f%%          %s              %5.1f%%\n" % (
            t, 100.0 * k / n, "%5.1f%%" % (100 * acc) if acc is not None else "  n/a ", 100.0 * (n - k) / n))
    out.write("\n")
    for target in (0.9, 0.95, 0.98):
        best = None
        for k in range(n, 0, -1):
            if cum[k - 1] / k >= target:
                best = k
                break
        if best:
            out.write("To be right %d%% of the time it answers: threshold %.3f, answers %.1f%% here, sends %.1f%% up\n" % (
                round(target * 100), by_p[best - 1]["p"], 100.0 * best / n, 100.0 * (n - best) / n))
        else:
            out.write("To be right %d%% of the time it answers: not reachable on this data\n" % round(target * 100))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Measure how confident and how right a local decision model is on your labeled data.")
    ap.add_argument("--url", default="http://127.0.0.1:8765", help="server base URL (default http://127.0.0.1:8765)")
    ap.add_argument("--data", help="JSONL with text and label per line")
    ap.add_argument("--question", help="JSON with instructions and criteria")
    ap.add_argument("--report", help="print the threshold table for an existing results file and exit")
    ap.add_argument("--limit", type=int, default=0, help="only the first N examples")
    ap.add_argument("--name", default="", help="a name for this run, shown on the page")
    ap.add_argument("--out", default="route-check.json", help="where to write the results")
    a = ap.parse_args(argv)
    if a.report:
        d = json.load(open(a.report))
        s = d.get("summary", {})
        print("%s: %d examples, %.1f%% right overall, median %s ms" % (d.get("name", a.report), len(d["items"]),
              100.0 * sum(x["choice"] == x["label"] for x in d["items"]) / len(d["items"]), s.get("median_ms", "?")))
        threshold_table(d["items"])
        return
    if not a.data or not a.question:
        ap.error("--data and --question are required unless you use --report")

    q = json.load(open(a.question))
    keys = list(q["criteria"])
    rows = [json.loads(l) for l in open(a.data) if l.strip()]
    if a.limit:
        rows = rows[: a.limit]
    bad = [r for r in rows if str(r.get("label")) not in keys]
    if bad:
        raise SystemExit("%d examples have a label that is not an option key, first: %r" % (len(bad), bad[0]))
    health = get(a.url.rstrip("/") + "/health")
    endpoint = a.url.rstrip("/") + "/v1/systemone"

    items, times = [], []
    t_start = time.time()
    for i, r in enumerate(rows):
        body = {"model": "jeff-latest", "state": r["text"],
                "questions": {"q": {"type": "choice", "instructions": q["instructions"], "criteria": q["criteria"]}}}
        t0 = time.perf_counter()
        res = post(endpoint, body)
        ms = (time.perf_counter() - t0) * 1000
        ans = res["answers"]["q"]
        probs = [round(float(ans["probabilities"][k]), 5) for k in keys]
        best = max(range(len(keys)), key=lambda j: probs[j])
        item = {"text": r["text"], "label": str(r["label"]), "choice": keys[best], "p": probs[best], "probs": probs, "ms": round(ms, 1)}
        if "intent" in r:
            item["intent"] = r["intent"]
        items.append(item)
        times.append(ms)
        if (i + 1) % 100 == 0 or i + 1 == len(rows):
            acc = sum(x["choice"] == x["label"] for x in items) / len(items)
            sys.stderr.write("\r%d/%d  accuracy so far %.1f%%  median %.0f ms   " % (i + 1, len(rows), acc * 100, statistics.median(times)))
    sys.stderr.write("\n")

    acc = sum(x["choice"] == x["label"] for x in items) / len(items)
    times_sorted = sorted(times)
    out = {
        "tool": "route-check", "version": VERSION, "name": a.name or a.data,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "server": {"url": a.url, "model": health.get("model"), "status": health.get("status")},
        "machine": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()},
        "question": q, "keys": keys,
        "summary": {"n": len(items), "accuracy": round(acc, 4),
                    "median_ms": round(statistics.median(times), 1),
                    "p90_ms": round(times_sorted[int(0.9 * (len(times_sorted) - 1))], 1),
                    "wall_s": round(time.time() - t_start, 1)},
        "items": items,
    }
    json.dump(out, open(a.out, "w"), ensure_ascii=False)
    print("Accuracy %.1f%% on %d examples, median %.0f ms per decision." % (acc * 100, len(items), out["summary"]["median_ms"]))
    threshold_table(items)
    print("Saved %s. Drop it on %s to pick a threshold." % (a.out, VIEWER_URL))


if __name__ == "__main__":
    main()
