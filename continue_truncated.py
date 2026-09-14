"""
Resume fetching for wallets that were truncated under the OLD raw-fill cap.

Continues each wallet's timestamp-cursor walk from its last cached fill, under
the NEW distinct-order cap (see lib_subgraph._walk / fetch_fills), so wallets
truncated purely on fill-count noise (one order, thousands of fills) get to
keep going instead of staying stuck at their old fill-count cutoff.

Overwrites each wallet's cache file in place with the extended fill set.
Idempotent-ish: a wallet whose cached orderHash count already meets CAP is
left untouched (no network call) — re-running only does work where needed.
"""
import json, os, glob, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import lib_subgraph as sg

FILLS_DIR = os.path.join(sg.DATA, "fills")
CAP = 8_000
WORKERS = 8

def continue_one(fp):
    w = os.path.basename(fp)[:-5]  # strip ".json"
    d = json.load(open(fp))
    if not d.get("truncated"):
        return ("not_truncated", 0, len(d["fills"]), False)
    fills = d["fills"]
    before_n = len(fills)
    seen = set(f["id"] for f in fills)
    seen_orders = set(f["orderHash"] for f in fills)
    if len(seen_orders) >= CAP:
        # already meets the new cap purely from existing data; nothing to fetch
        return ("already_capped", 0, before_n, True)
    last_ts = max(int(f["timestamp"]) for f in fills)
    out = list(fills)
    new_out, truncated = sg._walk(w, CAP, out, seen, seen_orders, last_ts)
    added = len(new_out) - before_n
    tmp = fp + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"fills": new_out, "truncated": truncated}, fh)
    os.replace(tmp, fp)
    return ("ok", added, len(new_out), truncated)

def main(limit=None):
    files = sorted(glob.glob(os.path.join(FILLS_DIR, "*.json")))
    trunc_files = []
    for fp in files:
        try:
            d = json.load(open(fp))
        except Exception:
            continue
        if d.get("truncated"):
            trunc_files.append(fp)
    if limit:
        trunc_files = trunc_files[:limit]
    print(f"{len(trunc_files)} truncated wallet files to resume", flush=True)
    t0 = time.time()
    done = failed = still_trunc = now_complete = already_capped = 0
    total_added = 0
    fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(continue_one, fp): fp for fp in trunc_files}
        for fut in as_completed(futs):
            fp = futs[fut]
            try:
                status, added, total_n, trunc = fut.result()
            except Exception as e:
                failed += 1
                fails.append(fp)
                print(f"FAIL {os.path.basename(fp)}: {e}", flush=True)
                continue
            done += 1
            total_added += added
            if status == "already_capped":
                already_capped += 1
            if trunc:
                still_trunc += 1
            else:
                now_complete += 1
            if done % 25 == 0:
                el = time.time() - t0
                rate = total_added / max(el, 1)
                print(f"[{done}/{len(trunc_files)}] failed={failed} now_complete={now_complete} "
                      f"still_truncated={still_trunc} already_capped={already_capped} "
                      f"fills_added={total_added} ({rate:.0f}/s) {el:.0f}s elapsed", flush=True)
    print(f"DONE: {done}/{len(trunc_files)} processed, {failed} failed, "
          f"{now_complete} now complete (no longer truncated), {still_trunc} still truncated, "
          f"fills_added={total_added}, {time.time()-t0:.0f}s", flush=True)
    if fails:
        json.dump(fails, open(os.path.join(sg.DATA, "continue_fails.json"), "w"))

if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(lim)
