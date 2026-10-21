"""Explicit foreground paper run against an already running live recorder."""

import argparse
import importlib
import json
import subprocess
import time

from tradingbot.db.session import SessionLocal
from tradingbot.strategy.registry import get_strategy

from .engine import PaperEngine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-module", required=True, help="Module registering the strategy class")
    parser.add_argument("--strategy-key", required=True)
    parser.add_argument("--strategy-id", required=True, type=int, help="Existing paper strategy with allocation")
    parser.add_argument("--instrument-id", required=True, action="append", type=int,
                        help="Explicitly reviewed standard non-sports PM US binary instrument; repeat as needed")
    parser.add_argument("--params", default="{}", help="JSON strategy parameters recorded in the trial")
    args = parser.parse_args()
    params = json.loads(args.params)
    if not isinstance(params, dict):
        parser.error("--params must be a JSON object")
    importlib.import_module(args.strategy_module)
    strategy = get_strategy(args.strategy_key)(params)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    with SessionLocal() as session:
        engine = PaperEngine(session, strategy, strategy_id=args.strategy_id, instrument_ids=args.instrument_id)
        trial_id = engine.start(git_commit=commit)
        print(json.dumps({"mode": "paper", "trial_id": trial_id}), flush=True)
        try:
            while True:
                engine.poll()
                time.sleep(1)
        except KeyboardInterrupt:
            print(json.dumps({"trial_id": trial_id, "status": "running", "resting_orders": "retained"}), flush=True)


if __name__ == "__main__":
    main()
