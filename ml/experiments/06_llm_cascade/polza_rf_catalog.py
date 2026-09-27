"""List Polza chat models with providers marked as storing data in Russia.

Public read-only catalog. Prints no keys and sends no resident messages.
"""
from __future__ import annotations

import json

import requests


def main() -> None:
    response = requests.get("https://polza.ai/api/v1/models",
                            params={"type": "chat", "include_providers": "true"},
                            timeout=30)
    response.raise_for_status()
    rows = []
    for model in response.json().get("data", []):
        for provider in model.get("providers", []):
            if not provider.get("stores_data_in_russia"):
                continue
            price = provider.get("pricing", {})
            rows.append({"model": model["id"], "provider": provider["name"],
                         "input_rub_per_million": price.get("prompt_per_million"),
                         "output_rub_per_million": price.get("completion_per_million"),
                         "fz152_flag": provider.get("is_fz152_compliant")})
    rows.sort(key=lambda row: (float(row["input_rub_per_million"] or "inf"), row["model"]))
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
