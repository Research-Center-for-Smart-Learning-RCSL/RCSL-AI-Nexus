"""Evaluation-import argparse entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .service import run


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", required=True, help="login of the importing administrator")
    parser.add_argument("--label", required=True, help="how operators will refer to this run")
    parser.add_argument("--ran-at", required=True, help="when it ran (ISO date or timestamp)")
    parser.add_argument("--harness-ref", default="", help="path or commit of the harness")
    parser.add_argument(
        "--phase",
        action="append",
        default=[],
        help=(
            "harness phase to include; repeatable, and a later one supersedes "
            "an earlier one task by task (e.g. --phase full --phase repair)"
        ),
    )
    parser.add_argument(
        "--tasks",
        default=None,
        help=(
            "JSON file of task definitions from `tasks.py --json`, stored with "
            "the run so the screen can show the question beside the score; only "
            "the tasks the run's samples name are kept"
        ),
    )
    parser.add_argument("--note", default="", help="a sentence about the run")
    parser.add_argument(
        "--caveat",
        action="append",
        default=[],
        help="what this run does not establish; repeatable",
    )
    return asyncio.run(run(parser.parse_args()))
