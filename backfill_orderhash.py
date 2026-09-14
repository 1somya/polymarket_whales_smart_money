"""
One-time backfill: add `orderHash` to every already-cached fill in data/fills/*.json.

Uses orderFilledEvents(where:{id_in:[...]}) batched 1000 known fill ids per query — a
direct id lookup, not a re-walk of history, so it's independent of fetch_fills's
timestamp-cursor pagination and the per-wallet truncation cap.

Idempotent: a wallet file is skipped once every one of its fills already has orderHash,
so a killed/re-run pass only redoes the files it didn't finish.
"""
import json, os, glob, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import lib_subgraph as sg

FILLS_DIR = os.path.join(sg.DATA, "fills")
BATCH = 1000
WORKERS = 12

def fetch_orderhashes(ids):
    out = {}
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        idlist = ",".join('"%s"' % x for x in chunk)
        q = '{ orderFilledEvents(first:%d, where:{id_in:[%s]}){ id orderHash } }' % (len(chunk), idlist)
        d = sg.gq(sg.OB, q)
        if d is None:
            raise sg.FetchError(f"id_in lookup failed for a batch of {len(chunk)} ids")
        for row in d.get("orderFilledEvents", []):
            out[row["id"]] = row["orderHash"]
    return out

def backfill_one(fp):
    d = json.load(open(fp))
    fills = d["fills"]
    missing_ids = [f["id"] for f in fills if "orderHash" not in f]
    if not missing_ids:
        return ("skip", 0, 0)
    oh_map = fetch_orderhashes(missing_ids)
    unresolved = 0
    for f in fills:
        if "orderHash" not in f:
            oh = oh_map.get(f["id"])
            if oh is not None:
                f["orderHash"] = oh
            else:
                unresolved += 1
    tmp = fp + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh)
    os.replace(tmp, fp)
    return ("ok", len(missing_ids) - unresolved, unresolved)

def main(limit=None):
    files = sorted(glob.glob(os.path.join(FILLS_DIR, "*.json")))
    if limit:
        files = files[:limit]
    print(f"{len(files)} wallet files to check", flush=True)
    t0 = time.time()
    done = skipped = failed = 0
    total_ok = total_unresolved = 0
    fails = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(backfill_one, fp): fp for fp in files}
        for fut in as_completed(futs):
            fp = futs[fut]
            try:
                status, ok_n, unresolved_n = fut.result()
            except Exception as e:
                failed += 1
                fails.append(fp)
                print(f"FAIL {os.path.basename(fp)}: {e}", flush=True)
                continue
            done += 1
            if status == "skip":
                skipped += 1
            else:
                total_ok += ok_n
                total_unresolved += unresolved_n
            if done % 100 == 0:
                el = time.time() - t0
                print(f"[{done}/{len(files)}] skipped={skipped} failed={failed} "
                      f"ids_backfilled={total_ok} unresolved={total_unresolved} "
                      f"{el:.0f}s elapsed", flush=True)
    print(f"DONE: {done}/{len(files)} processed, {skipped} already had orderHash, "
          f"{failed} failed, {total_ok} ids backfilled, {total_unresolved} unresolved, "
          f"{time.time()-t0:.0f}s", flush=True)
    if fails:
        json.dump(fails, open(os.path.join(sg.DATA, "backfill_fails.json"), "w"))

if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(lim)
