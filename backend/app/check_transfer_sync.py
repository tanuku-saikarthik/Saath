"""Dry run of the transfer-number sync: reads your Bolna agents and says what it would do. Changes nothing.

    python -m app.check_transfer_sync +919999911111
"""
from __future__ import annotations

import sys

from . import bolna
from .config import settings

def _find_transfer(node, path=""):
    """Every place in the agent that mentions a transfer, so we can see where Bolna keeps the number."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if "transfer" in str(k).lower():
                yield p, v
            else:
                yield from _find_transfer(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _find_transfer(v, f"{path}[{i}]")
    elif isinstance(node, str) and "transfer" in node.lower():
        yield path, node


if __name__ == "__main__":
    new = sys.argv[1] if len(sys.argv) > 1 else "+910000000001"
    for label, aid in (("Telugu", settings.BOLNA_AGENT_ID_TE), ("Hindi", settings.BOLNA_AGENT_ID_HI)):
        if not aid:
            print(f"{label}: no agent id set")
            continue
        try:
            keys = sorted(bolna._api("GET", f"/v2/agent/{aid}").keys())
        except bolna.BolnaError as exc:
            print(f"{label}: cannot read agent ({exc})")
            continue
        print(f"{label}: Bolna returns keys {keys}")
        agent = bolna._api("GET", f"/v2/agent/{aid}")
        for path, val in _find_transfer(agent):
            print(f"{label}: transfer found at {path} = {str(val)[:160]}")
        print(f"{label}: {bolna.sync_transfer_number(aid, '', new, dry_run=True)}")
