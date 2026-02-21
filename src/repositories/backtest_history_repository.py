"""
Backtest History Repository

Data access layer for persisting and retrieving backtest run history.
Heavy data (summary, equity curve, trades, report) is stored as files on disk.
"""
import os
import json
import shutil
from datetime import datetime
from typing import Optional, List

from db import db
from models import BacktestRunModel
from config import setup_logger


logger = setup_logger(name="BacktestHistoryRepository")

# Base directory for backtest history data files
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
HISTORY_REL_DIR = 'backtest_history'
HISTORY_ABS_DIR = os.path.join(PROJECT_ROOT, HISTORY_REL_DIR)


class BacktestHistoryRepository:
    """Repository for backtest run history with file-based data storage."""

    def __init__(self):
        os.makedirs(HISTORY_ABS_DIR, exist_ok=True)

    @staticmethod
    def _abs_path(relative_dir: str) -> str:
        """Resolve a relative data_dir stored in DB to absolute path."""
        return os.path.join(PROJECT_ROOT, relative_dir)

    def save(
        self,
        config_name: str,
        start_date,
        end_date,
        check_daily_sl: bool,
        mid_week_buy: bool,
        summary: dict,
        equity_curve: list,
        trades: list,
        report_text: str,
        run_label: Optional[str] = None,
    ) -> BacktestRunModel:
        """
        Save a backtest run: write data files to disk, insert metadata row.

        Returns:
            BacktestRunModel instance
        """
        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')

        # Insert DB row first to get the auto-increment id
        run = BacktestRunModel(
            run_label=run_label,
            created_at=now,
            config_name=config_name,
            start_date=start_date,
            end_date=end_date,
            check_daily_sl=check_daily_sl,
            mid_week_buy=mid_week_buy,
            total_return=summary.get('total_return'),
            max_drawdown=summary.get('max_drawdown'),
            sharpe_ratio=summary.get('sharpe_ratio'),
            data_dir='',  # placeholder, updated after we know the id
        )
        try:
            db.session.add(run)
            db.session.flush()  # get the id without committing

            # Build folder: backtest_history/{timestamp}_{id}
            folder_name = f"{timestamp}_{run.id}"
            rel_dir = os.path.join(HISTORY_REL_DIR, folder_name)
            abs_dir = os.path.join(PROJECT_ROOT, rel_dir)
            os.makedirs(abs_dir, exist_ok=True)

            # Write data files
            self._write_json(os.path.join(abs_dir, 'summary.json'), summary)
            self._write_json(os.path.join(abs_dir, 'equity_curve.json'), equity_curve)
            self._write_json(os.path.join(abs_dir, 'trades.json'), trades)
            with open(os.path.join(abs_dir, 'report.txt'), 'w', encoding='utf-8') as f:
                f.write(report_text or '')

            # Store relative path in DB
            run.data_dir = rel_dir
            db.session.commit()

            logger.info(f"Saved backtest run {run.id} to {rel_dir}")
            return run
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving backtest run: {e}")
            raise

    def list_runs(self) -> List[BacktestRunModel]:
        """List all runs ordered by most recent first (metadata only)."""
        return (
            db.session.query(BacktestRunModel)
            .order_by(BacktestRunModel.created_at.desc())
            .all()
        )

    def get_run(self, run_id: int) -> Optional[dict]:
        """
        Get full run data: metadata + file contents.

        Returns:
            dict with keys: metadata fields + summary, equity_curve, trades, report_text
            or None if not found.
        """
        run = db.session.query(BacktestRunModel).get(run_id)
        if not run:
            return None

        abs_dir = self._abs_path(run.data_dir)
        result = run.to_dict()

        # Read data files
        result['summary'] = self._read_json(os.path.join(abs_dir, 'summary.json'))
        result['equity_curve'] = self._read_json(os.path.join(abs_dir, 'equity_curve.json'))
        result['trades'] = self._read_json(os.path.join(abs_dir, 'trades.json'))
        result['report_text'] = self._read_text(os.path.join(abs_dir, 'report.txt'))

        return result

    def delete_run(self, run_id: int) -> bool:
        """
        Delete a run: remove DB row and data folder from disk.

        Returns:
            True if deleted, False if not found.
        """
        run = db.session.query(BacktestRunModel).get(run_id)
        if not run:
            return False

        abs_dir = self._abs_path(run.data_dir) if run.data_dir else None
        try:
            db.session.delete(run)
            db.session.commit()

            # Remove folder from disk
            if abs_dir and os.path.isdir(abs_dir):
                shutil.rmtree(abs_dir)
                logger.info(f"Deleted backtest run {run_id} and folder {abs_dir}")
            else:
                logger.info(f"Deleted backtest run {run_id} (folder not found)")

            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error deleting backtest run {run_id}: {e}")
            return False

    # ── File helpers ──────────────────────────────────────

    @staticmethod
    def _write_json(path: str, data) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, default=str)

    @staticmethod
    def _read_json(path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Could not read {path}: {e}")
            return None

    @staticmethod
    def _read_text(path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return ''
