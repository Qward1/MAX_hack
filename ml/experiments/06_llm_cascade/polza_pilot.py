"""Budgeted Polza pilot on manually reviewed, paraphrased windows.

Dry run is the default. No prompt, response, API key or resident text is logged.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests

ROOT = Path(__file__).resolve().parents[2]
CATALOG = "https://polza.ai/api/v1/models"
COMPLETIONS = "https://polza.ai/api/v1/chat/completions"
ALLOWED = {
    "sber/gigachat-2": "sber-gigachat",
    "qwen/qwen3.6-35b-a3b": "yandex",
    "deepseek/deepseek-v3.2": "yandex",
    "openai/gpt-oss-120b": "yandex",
}
UNSAFE = re.compile(r"(?:\d|@|https?://|www\.|[A-Z][a-z]{2,}|[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)")


def get_json(url: str, headers: dict | None = None) -> dict:
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers or {}, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise RuntimeError("Could not read public model catalog") from None
            time.sleep(1)
    raise AssertionError("unreachable")


def provider_price(model: str, provider_name: str) -> tuple[float, float]:
    url = CATALOG + "?" + urlencode({"type": "chat", "include_providers": "true"})
    catalog = get_json(url)
    for item in catalog.get("data", []):
        if item.get("id") != model:
            continue
        for provider in item.get("providers", []):
            if provider.get("name") == provider_name and provider.get("stores_data_in_russia"):
                pricing = provider.get("pricing", {})
                return (float(pricing["prompt_per_million"]),
                        float(pricing["completion_per_million"]))
    raise RuntimeError("Requested provider is not currently marked as storing data in Russia")


def load_windows(path: Path) -> list[dict]:
    windows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    if not windows:
        raise ValueError("Empty input")
    ids = set()
    for item in windows:
        if item.get("id") in ids or not item.get("id"):
            raise ValueError("Missing or duplicate ID")
        ids.add(item["id"])
        if item.get("privacy_reviewed") is not True:
            raise ValueError("Every window needs privacy_reviewed=true")
        if item.get("task") not in {"classify", "link"}:
            raise ValueError("Unknown task")
        for field in ("message", "case_summary"):
            value = item.get(field, "")
            if not isinstance(value, str) or len(value) > 500 or UNSAFE.search(value):
                raise ValueError("Window failed strict privacy screen")
        if not item.get("message"):
            raise ValueError("Missing message")
        if item["task"] == "link" and not item.get("case_summary"):
            raise ValueError("Link task needs candidate case summary")
        if item["task"] == "classify" and not item.get("allowed_classes"):
            raise ValueError("Classify task needs local candidate classes")
        if item["task"] == "classify":
            classes = item["allowed_classes"]
            if (not isinstance(classes, list) or len(classes) > 5 or
                    any(not isinstance(name, str) or
                        not re.fullmatch(r"[a-z_]{1,40}", name) for name in classes)):
                raise ValueError("Unsafe or excessive class candidates")
            if not isinstance(item.get("gold"), str) or not re.fullmatch(
                    r"[a-z_]{1,40}", item["gold"]):
                raise ValueError("Missing or invalid pre-annotated gold")
        elif item.get("gold") not in {"same_case", "new_case", "unclear"}:
            raise ValueError("Missing or invalid pre-annotated gold")
    return windows


def messages_for(item: dict) -> list[dict]:
    system = ("Ты проверяешь предварительное решение локальной модели о проблеме дома. "
              "Ответь ровно одним JSON-объектом, без объяснений и markdown. "
              "Для classify: {\"decision\":\"<один из allowed_classes или "
              "not_a_problem или unclear>\"}. Для link: "
              "{\"decision\":\"same_case|new_case|unclear\"}. "
              "Выбирай unclear при недостатке сведений. Не выдумывай адрес или детали.")
    if item["task"] == "classify":
        payload = {"task": "classify", "message": item["message"],
                   "allowed_classes": item["allowed_classes"]}
    else:
        payload = {"task": "link", "message": item["message"],
                   "candidate_case": item["case_summary"]}
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def parse_decision(content: str, item: dict) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    try:
        decision = json.loads(stripped)["decision"]
    except (ValueError, TypeError, KeyError):
        return "invalid_json"
    allowed = (set(item["allowed_classes"]) | {"not_a_problem", "unclear"}
               if item["task"] == "classify" else
               {"same_case", "new_case", "unclear"})
    return decision if decision in allowed else "invalid_decision"


def call(model: str, provider: str, key: str, item: dict,
         price_in: float, price_out: float, max_tokens: int) -> tuple[str, dict, float]:
    body = {"model": model, "messages": messages_for(item), "max_tokens": max_tokens,
            "provider": {"only": [provider], "allow_fallbacks": False,
                         "max_price": {"prompt": price_in * 1.01,
                                       "completion": price_out * 1.01}}}
    request = Request(COMPLETIONS, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key,
                               "Content-Type": "application/json"}, method="POST")
    start = time.perf_counter()
    try:
        with urlopen(request, timeout=90) as response:
            data = json.load(response)
    except HTTPError as error:
        # Response bodies may echo a request; deliberately suppress them.
        raise RuntimeError(f"Polza HTTP {error.code}") from None
    latency = time.perf_counter() - start
    content = data["choices"][0]["message"].get("content") or ""
    if data.get("provider") and data["provider"].lower() != provider.lower():
        raise RuntimeError("Response provider differs from pinned provider")
    return parse_decision(content, item), data.get("usage") or {}, latency


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True,
                        help="Gitignored JSONL of manually reviewed paraphrased windows")
    parser.add_argument("--model", choices=sorted(ALLOWED), required=True)
    parser.add_argument("--live", action="store_true", help="Actually spend API credits")
    parser.add_argument("--max-rub", type=float, default=10.0)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--max-tokens", type=int, choices=[300, 800, 1600], default=300)
    parser.add_argument("--run-name", type=str, default="")
    args = parser.parse_args()
    if not 0 < args.max_rub <= 10 or not 0 < args.max_requests <= 100:
        raise ValueError("Pilot limits cannot exceed 10 RUB or 100 requests")
    if args.run_name and not re.fullmatch(r"[a-z0-9_]{1,40}", args.run_name):
        raise ValueError("run-name must be a short safe identifier")
    windows = load_windows(args.input)
    provider = ALLOWED[args.model]
    price_in, price_out = provider_price(args.model, provider)
    max_cost = (2000 * price_in + args.max_tokens * price_out) / 1_000_000
    if not args.live:
        print(json.dumps({"dry_run": True, "windows": len(windows), "model": args.model,
                          "pinned_provider": provider, "input_price": price_in,
                          "output_price": price_out,
                          "max_estimated_rub_per_request": round(max_cost, 4)},
                         ensure_ascii=False))
        return
    key_path = ROOT / "artifacts/polza_key.txt"
    if not key_path.is_file():
        raise RuntimeError("Local key file is absent")
    key = key_path.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("Local key file is empty")
    outcomes = []
    spent = 0.0
    for item in windows[:args.max_requests]:
        if spent + max_cost > args.max_rub:
            break
        decision, usage, latency = call(args.model, provider, key, item,
                                        price_in, price_out, args.max_tokens)
        prompt_tokens = int(usage.get("prompt_tokens") or 2000)
        completion_tokens = int(usage.get("completion_tokens") or args.max_tokens)
        estimate = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
        cost = float(usage.get("cost_rub") or usage.get("cost") or estimate)
        spent += cost
        outcomes.append({"id": item["id"], "task": item["task"],
                         "decision": decision, "correct": decision == item.get("gold"),
                         "prompt_tokens": prompt_tokens,
                         "completion_tokens": completion_tokens,
                         "provider_cost_reported": "cost_rub" in usage or "cost" in usage,
                         "billed_or_estimated_rub": round(cost, 5),
                         "latency_seconds": round(latency, 3)})
    report = {"model": args.model, "provider": provider,
              "max_tokens": args.max_tokens,
              "provider_rf_verified_before_run": True,
              "calls": len(outcomes), "billed_or_estimated_rub": round(spent, 4),
              "correct": sum(x["correct"] for x in outcomes),
              "outcomes": outcomes,
              "warning": "Pilot labels may be synthetic or assistant-created; not independent human gold."}
    suffix = f"_{args.run_name}" if args.run_name else ""
    output = ROOT / "artifacts" / (f"polza_pilot_{args.model.replace('/', '_')}"
                                     f"_{args.max_tokens}{suffix}.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "outcomes"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        # Errors above are deliberately text-free and key-free.
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(2)
