# Daily Stop-Loss Processing + Bug Fixes

## Files to Modify
- [x] `stoploss_utils.py` — Bug 6: trailing stop guard
- [ ] `actions_repository.py` — `get_pending_actions()`, `insert_action()`
- [ ] `actions_service.py` — capital-aware approval, `reject_pending_actions()`, Bug 1/2/4
- [ ] `runner.py` — daily SL loop, rewrite `run()`
- [ ] Verification — re-run backtest, validate DB data
- [ ] Cleanup — remove `debug_db.py`, `debug_db_output.txt`
