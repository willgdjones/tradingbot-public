# C04 sizing repair before any final

2026-10-01. Preparation `8149db6` produced six completed training attempts
4016–4021. All were positive after modeled fees, but each contained 65–100
risk-rejected buys. The frozen completeness gate rejected every configuration;
selection is null and **no C04 final holdout has been consumed**. Those original
trials, source and artifacts are retained without modification.

The mechanical discrepancy is between reference-price dollar targets and the
unchanged RiskEngine's price basis. Example: a buy on 2007-04-02 in trial 4017
requested 0.023795818 shares at a $142.31 rounded limit. The existing $140
post-order position cap permitted only 0.0227816177919 additional shares. The
engine correctly rejected the request. Five 19% sleeves in C05 did not expose
this single-instrument full-slot case; C04 did.

Version 2 caps any buy to
`floor_to_quantity_step(max(0, 140 / rounded_buy_limit - shares_already_owned))`
in addition to the existing frozen dollar target, settled cash, fee reserve
and sub-$1 skip rules. This changes requested quantity only; the RiskEngine
retains its absolute veto. No risk limit, source, signal, scaling constant,
monthly schedule, partition boundary or cost assumption changes. There is no
search over sizing parameters. Capacity clipping is recorded, and any remaining
rejection still makes a run ineligible under the same completeness gate.

The three preregistered variants at 5/10 bp will be recorded again as explicit
v2 attempts after code/tests are committed. No result is overwritten and no
failed configuration disappears from the ledger. Select one positive complete
10 bp case in the original order, commit it, then admit one final at 10 bp.
The family final guard is common to v1/v2 and ignores renamed source identity.
The preflight account-risk review remains applicable; historical SPY evidence
is still contaminated and cannot by itself authorize paper/live promotion.
