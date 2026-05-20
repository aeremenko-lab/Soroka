"""CLI entry point for the search-quality eval suite.

Usage:
    python -m tests.eval.run_eval                    # full set, baseline pipeline
    python -m tests.eval.run_eval --tag morphology   # subset by tag

Required env (loaded via dotenv from .env):
    SOROKA_JINA_API_KEY   — Jina embeddings key (free tier OK)
    SOROKA_LLM_MODEL      — openai:<model> or gemini:<model>
    SOROKA_OPENAI_API_KEY or SOROKA_GEMINI_API_KEY
"""
import argparse
import asyncio
import importlib
import os
import sys

from dotenv import load_dotenv

from src.adapters.llm import build_llm_client
from tests.eval.metrics import (
    aggregate, mrr, precision_at_k, recall_at_k,
)
from tests.eval.runner import run_all


def _format_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _print_report(results: list[dict]) -> None:
    scored = []
    for r in results:
        scored.append({
            "q": r["q"],
            "tag": r["tag"],
            "recall": recall_at_k(r["expected_ids"], r["predicted_ids"], k=5),
            "precision": precision_at_k(r["expected_ids"], r["predicted_ids"], k=5),
            "mrr": mrr(r["expected_ids"], r["predicted_ids"]),
            "expected_keys": r["expected_keys"],
            "expected_ids": r["expected_ids"],
            "predicted_ids": r["predicted_ids"],
        })

    summary = aggregate(scored)

    print()
    print("=" * 70)
    print("EVAL REPORT")
    print("=" * 70)
    g = summary["global"]
    print(f"Global  (n={g['n']:>2})  "
          f"recall@5={_format_pct(g['recall@5'])}  "
          f"precision@5={_format_pct(g['precision@5'])}  "
          f"MRR={g['mrr']:.3f}")
    print()
    print("By tag:")
    for tag, m in sorted(summary["by_tag"].items()):
        print(f"  {tag:<22} (n={m['n']:>2})  "
              f"R={_format_pct(m['recall@5'])}  "
              f"P={_format_pct(m['precision@5'])}  "
              f"MRR={m['mrr']:.3f}")

    print()
    print("Per-query (recall=0 first — these are the failures):")
    scored.sort(key=lambda x: (x["recall"], x["mrr"]))
    for r in scored:
        marker = "FAIL" if r["recall"] == 0 and r["expected_ids"] else (
            "OK" if r["recall"] >= 0.5 else "weak"
        )
        print(
            f"  [{marker:>4}] R={_format_pct(r['recall'])} "
            f"P={_format_pct(r['precision'])} "
            f"MRR={r['mrr']:.2f} "
            f"| {r['tag']:<18} | {r['q']!r}"
        )
        print(f"            expected={r['expected_keys']}")
        print(f"            predicted_ids={r['predicted_ids']}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Search-quality eval")
    parser.add_argument("--tag", help="run only queries with this tag")
    parser.add_argument(
        "--queries-module",
        default="tests.eval.queries",
        help="dotted path of module exposing QUERIES (default tests.eval.queries)",
    )
    args = parser.parse_args()
    queries_module = importlib.import_module(args.queries_module)
    QUERIES = queries_module.QUERIES
    print(f"queries={args.queries_module} (n={len(QUERIES)})")

    load_dotenv()
    jina_key = (
        os.environ.get("SOROKA_JINA_API_KEY", "").strip()
        or os.environ.get("JINA_API_KEY", "").strip()
    )
    llm = build_llm_client()
    if not jina_key:
        print("ERROR: SOROKA_JINA_API_KEY missing. Put it in .env or export it.",
              file=sys.stderr)
        return 2
    if llm is None:
        print("ERROR: SOROKA_LLM_MODEL and matching provider key are missing.",
              file=sys.stderr)
        return 2

    queries_subset = list(QUERIES)
    if args.tag:
        queries_subset = [q for q in QUERIES if q["tag"] == args.tag]
        if not queries_subset:
            print(f"ERROR: no queries match tag {args.tag!r}", file=sys.stderr)
            return 2
        print(f"running {len(queries_subset)} queries with tag={args.tag!r}")

    print(f"llm={llm.selector}")

    results, _ = await run_all(
        jina_key=jina_key,
        llm=llm,
        queries_subset=queries_subset,
    )
    _print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
