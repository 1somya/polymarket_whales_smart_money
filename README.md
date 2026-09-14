# Polymarket Whales / Smart money

On Polymarket
every wallet is public and sits on-chain forever. Early digging into
the data -  0.7% of trades account for almost 60% of the dollar
volume. The flow really is dominated by a small set of wallets, and because it's all public,
you can follow any one of them all the way back through its entire history.

So the obvious next question: could you just copy them?

Not blindly, though. That's the actual question this whole project is trying to answer —
who are the winners that I can copy and when to follow the wallet and when
not to.

But "winning" isn't one thing. A wallet can be
sitting on +$5M and none of it be something you could actually replicate. The only kind
of winning I actually care about is a wallet that bought at 30 cents because it believed that
outcome would happen, held through all the noise, and got paid out when the market resolved.

So before answering "who's winning," I had to find out what should I consider winning? Just Pnl would not give something that can be copied. So
for every wallet, how much of its money came from trading the price around, and how much
came from just being right and holding? I rebuilt each wallet's entire trading history from
raw on-chain fills, matched every buy to every sell, and split every dollar of profit into
two buckets — money made from price movement, and money made from holding to settlement.
Only the second bucket is copyable.

That split turned out to be the first real finding. Most of these wallets, even
the famous ones, make surprisingly little from clever trading. Almost all of the clean
profit comes from holding.

But knowing a wallet made its money the "right" way isn't enough to build a strategy on
either. There's already research out there on this exact platform that found the same
concentration — a handful of wallets hold most of the profit, and the winners tend to hold
to resolution rather than trade in and out. That's useful, but it only tells you who *has*
won. It doesn't tell you whether to trust any of them going forward. Plenty of people get it right once and then fall apart. So the next
question became: if I take today's list of winners, how likely is it that they're still
winning a month from now? Three months? Six? I tested that — took each
wallet's track
record up to some point in time, then checked what it did afterward, on data it had never
touched, to see if the past genuinely predicts the future here or if it's just noise.

It does predict it, a little. Not a lot but a
wallet with real holding skill is meaningfully more likely to keep showing it than a random
wallet is, and whatever edge is there fades slowly instead of vanishing overnight.

Which loops back to the actual question from the top. It was never "find the top wallets and
copy them." It's copy winners, but not blindly — figure out a way to know when to follow
a wallet and when not to.

## Work till now


**Experiment 1** is the earlier, rougher pass — take the biggest wallets on the leaderboard
and figure out what "kind" of trader each one actually is, purely from behavior 

**Experiment 2** is the real question above, done properly — the trading-vs-holding split,
and then the actual persistence testing: does a wallet's past holding skill predict its
future holding skill, and for how long.
## How this repo is laid out

- All the code (`.py` files) lives flat in this main folder and always runs from here,
  regardless of which experiment it belongs to.
- `data/` and `out/` hold everything the code downloads and produces — also shared between
  both.
- `experiment1/` and `experiment2/` just hold each experiment's write-ups and web pages, so
  the two stories don't get tangled together.
