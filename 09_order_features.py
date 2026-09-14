"""
Re-pull cohort fills WITH orderHash and compute ORDER-level features (not fill-level).
A fill is one execution; an order (orderHash) is one decision/quote. One resting bid can
generate thousands of fills, so fill-based 'frequency' is misleading. This rebuilds the
metrics on orders and on true buy/sell balance, to test whether real market makers exist.
"""
import json, os, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd, numpy as np
import lib_subgraph as sg

tok2cond=json.load(open('data/tok2cond.json')); cond=json.load(open('data/cond_payout.json'))
OUT=os.path.join(sg.HERE if hasattr(sg,'HERE') else '.', 'out', 'order_features.csv')

def fetch_oh(w, cap=250000):
    out,seen,last_ts=[],set(),0
    while len(out)<cap:
        q='''{ orderFilledEvents(first:1000, orderBy:timestamp, orderDirection:asc,
          where:{and:[{timestamp_gte:%d},{or:[{maker:"%s"},{taker:"%s"}]}]}){
          id orderHash timestamp maker taker makerAssetId takerAssetId makerAmountFilled takerAmountFilled }}'''%(last_ts,w,w)
        d=sg.gq(sg.OB,q); rows=(d or {}).get('orderFilledEvents',[])
        if not rows: break
        fresh=[r for r in rows if r['id'] not in seen]
        for r in fresh: seen.add(r['id']); out.append(r)
        if len(rows)<1000: break
        last_ts=int(rows[-1]['timestamp'])
    return out

def norm(f,w):
    w=w.lower(); ma,ta=f['makerAssetId'],f['takerAssetId']
    mk,tk=int(f['makerAmountFilled']),int(f['takerAmountFilled'])
    is_maker=f['maker'].lower()==w
    if ma=='0': token,usdc,toks,mside=ta,mk,tk,'BUY'
    elif ta=='0': token,usdc,toks,mside=ma,tk,mk,'SELL'
    else: return None
    if toks==0: return None
    side=mside if is_maker else ('SELL' if mside=='BUY' else 'BUY')
    return dict(oh=f['orderHash'],side=side,size=toks/1e6,ts=int(f['timestamp']),maker=is_maker,token=token)

def features(w):
    raw=fetch_oh(w); F=[n for f in raw if (n:=norm(f,w))]
    if not F: return None
    n_fills=len(F); n_orders=len({f['oh'] for f in F})
    days=max(1,(max(f['ts'] for f in F)-min(f['ts'] for f in F))/86400)
    # per (token) resolved positions -> holding, per (market) buy/sell for two-sidedness/flip
    tok=defaultdict(lambda:{'b':0.0,'s':0.0}); condv=defaultdict(lambda:{'b':0.0,'s':0.0})
    for f in F:
        c=tok2cond.get(f['token'])
        tok[f['token']]['b' if f['side']=='BUY' else 's']+=f['size']
        if c: condv[c]['b' if f['side']=='BUY' else 's']+=f['size']
    bt=st=0.0; nres=0; flip_mk=0; twosided=0; nres_mk=0
    for t,p in tok.items():
        c=tok2cond.get(t)
        if not c or not cond.get(c,{}).get('resolved') or p['b']<=0: continue
        nres+=1; bt+=p['b']; st+=min(p['s'],p['b'])  # cap sold at bought for holding calc
    for c,p in condv.items():
        if not cond.get(c,{}).get('resolved') or p['b']<=0: continue
        nres_mk+=1
        if p['s']>0 and p['b']>0: twosided+=1
        if p['s']>=0.5*p['b']: flip_mk+=1     # flipped >=half of what they bought in this market
    holding=1-(st/bt) if bt else np.nan
    return dict(wallet=w, n_fills=n_fills, n_orders=n_orders,
        fills_per_order=n_fills/max(n_orders,1),
        orders_per_day=n_orders/days, fills_per_day=n_fills/days,
        maker_share=float(np.mean([f['maker'] for f in F])),
        holding_fraction=holding, sell_share=(st/bt) if bt else np.nan,
        two_sided_share=twosided/max(nres_mk,1), flip_market_share=flip_mk/max(nres_mk,1),
        n_markets=nres_mk)

def main():
    fp=pd.read_csv('out/fingerprints.csv'); cl=pd.read_csv('out/fingerprints_clustered.csv')[['wallet','cluster_name']]
    coh=fp[(fp.reconstructed==True)&(fp.truncated==False)&(fp.n_resolved>=50)].merge(cl,on='wallet')
    wallets=coh.wallet.tolist()
    t0=time.time(); res=[]
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={ex.submit(features,w):w for w in wallets}
        for i,fu in enumerate(as_completed(futs),1):
            r=fu.result()
            if r: res.append(r)
            if i%15==0: print(f"[{i}/{len(wallets)}] {time.time()-t0:.0f}s",flush=True)
    d=pd.DataFrame(res).merge(coh[['wallet','cluster_name','lz_roi','lz_realized_pnl','lz_volume']],on='wallet')
    d.to_csv(OUT,index=False); print(f"wrote {OUT}  ({len(d)} wallets, {time.time()-t0:.0f}s)")

if __name__=="__main__": main()
