from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

from app.settings import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


@dataclass(frozen=True)
class Candidate:
    name: str
    instructions: str


def _load_candidates(db_path: str, limit: int | None = None) -> list[Candidate]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT name, llm
        FROM labels
        WHERE is_active = 1 AND llm IS NOT NULL AND TRIM(llm) != ''
        ORDER BY created_at ASC
        """
    ).fetchall()
    conn.close()
    candidates = [Candidate(name=row[0].strip(), instructions=row[1].strip()) for row in rows]
    if limit is not None:
        return candidates[:limit]
    return candidates


def _build_messages(ocr_text: str, candidates: list[Candidate]) -> list[dict]:
    system_prompt = (
        "You are a classification assistant. "
        "You must output strict JSON with keys: label_name, confidence, signals. "
        "label_name MUST be one of the candidate names or null. "
        "If not enough evidence, label_name must be null, confidence 0.0..0.5, "
        "and signals must include ABSTAIN_NOT_ENOUGH_EVIDENCE. "
        "Return only JSON."
    )
    lines: list[str] = []
    for candidate in candidates:
        lines.append(
            f'- NAME: {json.dumps(candidate.name)}\n  INSTRUCTIONS: {json.dumps(candidate.instructions)}'
        )
    candidates_block = "\n".join(lines)
    user_prompt = (
        "Classify the document using the OCR text and the candidate labels.\n"
        "Candidate labels:\n"
        f"{candidates_block}\n\n"
        "OCR text:\n"
        f"{ocr_text}"
    )
    return [
        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
        {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
    ]


def _post_openai(payload: dict) -> dict:
    try:
        response = requests.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        status = getattr(exc.response, "status_code", None)
        body = getattr(exc.response, "text", "") if getattr(exc, "response", None) else ""
        return {
            "_error": "OPENAI_REQUEST_FAILED",
            "status_code": status,
            "detail": body[:1000],
        }


def _parse_response_json(payload: dict) -> dict:
    output_items = payload.get("output", [])
    for item in output_items:
        content = item.get("content", [])
        for block in content:
            if block.get("type") == "output_json":
                json_payload = block.get("json")
                return json_payload if isinstance(json_payload, dict) else {"_error": "INVALID_JSON"}
            if block.get("type") in {"output_text", "text"}:
                text = block.get("text", "") or ""
                parsed = _parse_json_from_text(text)
                if parsed is not None:
                    return parsed
                return {"_error": "INVALID_JSON", "raw_text": text[:1000]}
    return {"_error": "NO_OUTPUT_TEXT"}


def _parse_json_from_text(text: str) -> dict | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _extract_usage(payload: dict) -> dict:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    return usage


def _run_single_call(ocr_text: str, candidates: list[Candidate]) -> tuple[dict, dict, float]:
    messages = _build_messages(ocr_text, candidates)
    payload = {
        "model": OPENAI_MODEL,
        "input": messages,
        "text": {"format": {"type": "json_object"}},
    }
    start = time.perf_counter()
    response = _post_openai(payload)
    elapsed = time.perf_counter() - start
    if "output" not in response:
        return response, _extract_usage(response), elapsed
    return _parse_response_json(response), _extract_usage(response), elapsed


def _run_per_label(ocr_text: str, candidates: list[Candidate]) -> tuple[list[dict], dict, float]:
    results: list[dict] = []
    usage_total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    start = time.perf_counter()
    for candidate in candidates:
        result, usage, _ = _run_single_call(ocr_text, [candidate])
        results.append({"candidate": candidate.name, "result": result, "usage": usage})
        usage_total = _merge_usage(usage_total, usage)
    elapsed = time.perf_counter() - start
    return results, usage_total, elapsed


def _merge_usage(total: dict, usage: dict) -> dict:
    if not usage:
        return total
    total["input_tokens"] = total.get("input_tokens", 0) + usage.get("input_tokens", 0)
    total["output_tokens"] = total.get("output_tokens", 0) + usage.get("output_tokens", 0)
    total["total_tokens"] = total.get("total_tokens", 0) + usage.get("total_tokens", 0)
    input_details = total.setdefault("input_tokens_details", {})
    output_details = total.setdefault("output_tokens_details", {})
    input_details["cached_tokens"] = input_details.get("cached_tokens", 0) + usage.get(
        "input_tokens_details", {}
    ).get("cached_tokens", 0)
    output_details["reasoning_tokens"] = output_details.get("reasoning_tokens", 0) + usage.get(
        "output_tokens_details", {}
    ).get("reasoning_tokens", 0)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare LLM fallback strategies: per-label calls vs single call."
    )
    parser.add_argument("--ocr", required=True, help="Path to OCR text file.")
    parser.add_argument("--db", default="app.db", help="Path to sqlite db.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of candidate labels for the comparison.",
    )
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is not set.")

    ocr_text = open(args.ocr, "r", encoding="utf-8").read()
    candidates = _load_candidates(args.db, args.limit)
    if not candidates:
        raise SystemExit("No LLM candidates found in app.db (labels with non-empty llm).")

    print(f"Model: {OPENAI_MODEL}")
    print(f"Candidates: {len(candidates)}")
    print("")

    print("Single call (all candidates)")
    single_result, single_usage, single_elapsed = _run_single_call(ocr_text, candidates)
    print(f"  elapsed_s: {single_elapsed:.2f}")
    if single_usage:
        print(f"  usage: {json.dumps(single_usage)}")
    print(json.dumps(single_result, indent=2))
    print("")

    print("Per-label calls")
    per_results, per_usage, per_elapsed = _run_per_label(ocr_text, candidates)
    print(f"  elapsed_s: {per_elapsed:.2f}")
    if per_usage:
        print(f"  usage: {json.dumps(per_usage)}")
    best = _pick_best(per_results)
    if best:
        print(f"  best: {best['candidate']} ({best['result'].get('confidence')})")


def _pick_best(results: list[dict]) -> dict | None:
    best = None
    best_conf = -1.0
    for item in results:
        result = item.get("result", {})
        try:
            conf = float(result.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        label = result.get("label_name")
        if label and conf > best_conf:
            best_conf = conf
            best = item
    return best


if __name__ == "__main__":
    main()
