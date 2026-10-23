"""Manual extraction eval against an OpenAI-compatible endpoint."""
import argparse, json, os, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from perceive.extract import ExtractionParseError, build_prompt, parse_response_checked


def load_cases(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def norm(value):
    return "".join(str(value or "").lower().split())


def score_items(items, expected):
    wanted = [norm(x) for x in expected.get("texts", [])]
    actual = [norm(x.get("text")) for x in items if isinstance(x, dict)]
    hits = sum(1 for w in wanted if any(w in a or a in w for a in actual if a))
    return {"schema_ok": all(isinstance(x, dict) and x.get("text") and x.get("level") for x in items),
            "expected_hits": hits, "expected_total": len(wanted), "item_count": len(items)}


def call_model(base_url, key, model, prompt, timeout=60):
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def evaluate(cases, base_url, key, model, timeout=60):
    results = []
    for case in cases:
        raw = call_model(base_url, key, model, build_prompt([case["dialogue"]]), timeout)
        try:
            score = score_items(parse_response_checked(raw), case.get("expected", {}))
            score["parse_ok"] = True
        except ExtractionParseError:
            score = {"parse_ok": False, "schema_ok": False, "expected_hits": 0,
                     "expected_total": len(case.get("expected", {}).get("texts", [])),
                     "item_count": 0}
        results.append({"id": case.get("id", ""), **score})
    total = sum(row["expected_total"] for row in results)
    hits = sum(row["expected_hits"] for row in results)
    return {"model": model, "cases": len(results),
            "parse_ok": sum(row["parse_ok"] for row in results),
            "schema_ok": sum(row["schema_ok"] for row in results),
            "expected_hits": hits, "expected_total": total,
            "recall": round(hits / total, 4) if total else 0.0,
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--base-url", default=os.environ.get("SEEKMEMORY_EVAL_BASE_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("SEEKMEMORY_EVAL_API_KEY", ""))
    parser.add_argument("--model", default=os.environ.get("SEEKMEMORY_EVAL_MODEL", ""))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--out", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    if args.dry_run:
        print(json.dumps({"cases": len(cases), "configured": bool(args.base_url and args.api_key and args.model)}))
        return 0
    if not (args.base_url and args.api_key and args.model):
        raise SystemExit("set URL, key and model or use --dry-run")
    report = evaluate(cases, args.base_url, args.api_key, args.model, args.timeout)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
