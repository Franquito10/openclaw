#!/usr/bin/env python3
"""
A/B Test: Compare base model vs heretic-abliterated model.

Usage:
  python scripts/ab_test_heretic.py [--rounds 5] [--timeout 600] [--num-predict 256]

Sends the same prompt to both models with identical parameters,
measures response time, and compares output quality.
"""
import argparse
import json
import os
import sys
import time
import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")

# Models to compare
MODEL_A = os.environ.get("AB_MODEL_A", "qwen2.5:7b")
MODEL_B = os.environ.get("AB_MODEL_B", "qwen2.5-7b-heretic")

# Test prompts covering different capabilities
TEST_PROMPTS = [
    {
        "name": "creative_marketing",
        "prompt": (
            "Write a compelling 3-sentence marketing pitch for an AI-powered "
            "project management tool that handles task decomposition automatically. "
            "Target audience: startup CTOs."
        ),
    },
    {
        "name": "technical_analysis",
        "prompt": (
            "Explain the trade-offs between file-based task queues and database-backed "
            "job queues for a multi-agent AI system. Keep it under 200 words."
        ),
    },
    {
        "name": "code_generation",
        "prompt": (
            "Write a Python function that implements atomic claiming for a job queue "
            "using PostgreSQL's FOR UPDATE SKIP LOCKED. Include type hints."
        ),
    },
    {
        "name": "reasoning",
        "prompt": (
            "A multi-agent system has 5 agents. Each agent can propose up to 10 tasks/day. "
            "The system has a global cap of 30 tasks/day. If 3 agents each propose 10 tasks, "
            "how many more tasks can the remaining 2 agents propose combined?"
        ),
    },
    {
        "name": "spanish_response",
        "prompt": (
            "Describí en español las ventajas de usar un sistema de heartbeat "
            "para monitorear agentes autónomos. Máximo 100 palabras."
        ),
    },
]


def call_model(model: str, prompt: str, num_predict: int, timeout: int, retries: int = 3) -> dict:
    """Call Ollama and return timing + response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": 0.7,
            "top_p": 0.9,
            "seed": 42,  # Fixed seed for reproducibility
        },
    }

    for attempt in range(1, retries + 1):
        try:
            t0 = time.monotonic()
            r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
            elapsed = time.monotonic() - t0
            r.raise_for_status()
            data = r.json()
            return {
                "model": model,
                "response": data.get("response", "").strip(),
                "elapsed_s": round(elapsed, 2),
                "eval_count": data.get("eval_count", 0),
                "eval_duration_ns": data.get("eval_duration", 0),
                "tokens_per_sec": round(
                    data.get("eval_count", 0)
                    / max(data.get("eval_duration", 1) / 1e9, 0.001),
                    1,
                ),
                "ok": True,
            }
        except requests.exceptions.Timeout:
            print(f"  [attempt {attempt}/{retries}] Timeout for {model} ({timeout}s)")
            if attempt == retries:
                return {"model": model, "ok": False, "error": f"Timeout after {retries} retries"}
        except Exception as e:
            print(f"  [attempt {attempt}/{retries}] Error for {model}: {e}")
            if attempt == retries:
                return {"model": model, "ok": False, "error": str(e)}
            time.sleep(2)

    return {"model": model, "ok": False, "error": "Unknown failure"}


def run_test(prompt_data: dict, num_predict: int, timeout: int) -> dict:
    """Run A/B test for a single prompt."""
    name = prompt_data["name"]
    prompt = prompt_data["prompt"]

    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"Prompt: {prompt[:80]}...")
    print(f"{'='*60}")

    result_a = call_model(MODEL_A, prompt, num_predict, timeout)
    result_b = call_model(MODEL_B, prompt, num_predict, timeout)

    # Print comparison
    for label, r in [("A", result_a), ("B", result_b)]:
        model = r["model"]
        if r["ok"]:
            print(f"\n  [{label}] {model}")
            print(f"      Time: {r['elapsed_s']}s | Tokens: {r['eval_count']} | Speed: {r['tokens_per_sec']} tok/s")
            preview = r["response"][:200].replace("\n", " ")
            print(f"      Response: {preview}...")
        else:
            print(f"\n  [{label}] {model} — FAILED: {r.get('error')}")

    return {"name": name, "model_a": result_a, "model_b": result_b}


def main():
    parser = argparse.ArgumentParser(description="A/B Test: base vs heretic model")
    parser.add_argument("--rounds", type=int, default=1, help="Rounds per prompt (default: 1)")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per call in seconds (default: 600)")
    parser.add_argument("--num-predict", type=int, default=256, help="Max tokens to generate (default: 256)")
    parser.add_argument("--model-a", type=str, default=None, help=f"Model A (default: {MODEL_A})")
    parser.add_argument("--model-b", type=str, default=None, help=f"Model B (default: {MODEL_B})")
    parser.add_argument("--output", type=str, default=None, help="Save results to JSON file")
    args = parser.parse_args()

    global MODEL_A, MODEL_B
    if args.model_a:
        MODEL_A = args.model_a
    if args.model_b:
        MODEL_B = args.model_b

    print(f"A/B Test Configuration:")
    print(f"  Model A: {MODEL_A}")
    print(f"  Model B: {MODEL_B}")
    print(f"  Rounds per prompt: {args.rounds}")
    print(f"  Timeout: {args.timeout}s")
    print(f"  Max tokens: {args.num_predict}")
    print(f"  Prompts: {len(TEST_PROMPTS)}")

    all_results = []
    for round_num in range(args.rounds):
        if args.rounds > 1:
            print(f"\n{'#'*60}")
            print(f"ROUND {round_num + 1}/{args.rounds}")
            print(f"{'#'*60}")

        for prompt_data in TEST_PROMPTS:
            result = run_test(prompt_data, args.num_predict, args.timeout)
            result["round"] = round_num + 1
            all_results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    a_wins = b_wins = ties = errors = 0
    a_total_time = b_total_time = 0.0
    a_total_tokens = b_total_tokens = 0

    for r in all_results:
        ra, rb = r["model_a"], r["model_b"]
        if not ra["ok"] or not rb["ok"]:
            errors += 1
            continue
        a_total_time += ra["elapsed_s"]
        b_total_time += rb["elapsed_s"]
        a_total_tokens += ra["eval_count"]
        b_total_tokens += rb["eval_count"]

        if ra["elapsed_s"] < rb["elapsed_s"]:
            a_wins += 1
        elif rb["elapsed_s"] < ra["elapsed_s"]:
            b_wins += 1
        else:
            ties += 1

    total = a_wins + b_wins + ties
    print(f"  Speed wins — A: {a_wins}  B: {b_wins}  Tie: {ties}  Errors: {errors}")
    if total > 0:
        print(f"  Avg time — A: {a_total_time/total:.2f}s  B: {b_total_time/total:.2f}s")
        print(f"  Total tokens — A: {a_total_tokens}  B: {b_total_tokens}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n  Results saved to: {args.output}")


if __name__ == "__main__":
    main()
