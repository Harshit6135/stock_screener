"""Auto migration

Revision ID: 7ae50fb1b1af
Revises: a735c30a07a5
Create Date: 2026-01-05 09:52:08.887774

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7ae50fb1b1af'
down_revision = 'a735c30a07a5'
branch_labels = None
depends_on = None


def upgrade():
    # Cleanup any leftover table from failed migration attempts
    op.execute("DROP TABLE IF EXISTS percentile")
    
    # Step 1: Create new 'percentile' table with same structure as old 'ranking'
    op.create_table('percentile',
        sa.Column('tradingsymbol', sa.String(length=50), nullable=False),
        sa.Column('percentile_date', sa.Date(), nullable=False),
        sa.Column('ema_50_slope', sa.Float(), nullable=True),
        sa.Column('trend_rank', sa.Float(), nullable=True),
        sa.Column('distance_from_ema_200', sa.Float(), nullable=True),
        sa.Column('trend_extension_rank', sa.Float(), nullable=True),
        sa.Column('distance_from_ema_50', sa.Float(), nullable=True),
        sa.Column('trend_start_rank', sa.Float(), nullable=True),
        sa.Column('rsi_signal_ema_3', sa.Float(), nullable=True),
        sa.Column('momentum_rsi_rank', sa.Float(), nullable=True),
        sa.Column('ppo_12_26_9', sa.Float(), nullable=True),
        sa.Column('momentum_ppo_rank', sa.Float(), nullable=True),
        sa.Column('ppoh_12_26_9', sa.Float(), nullable=True),
        sa.Column('momentum_ppoh_rank', sa.Float(), nullable=True),
        sa.Column('risk_adjusted_return', sa.Float(), nullable=True),
        sa.Column('efficiency_rank', sa.Float(), nullable=True),
        sa.Column('rvol', sa.Float(), nullable=True),
        sa.Column('rvolume_rank', sa.Float(), nullable=True),
        sa.Column('price_vol_correlation', sa.Float(), nullable=True),
        sa.Column('price_vol_corr_rank', sa.Float(), nullable=True),
        sa.Column('bbb_20_2', sa.Float(), nullable=True),
        sa.Column('structure_rank', sa.Float(), nullable=True),
        sa.Column('percent_b', sa.Float(), nullable=True),
        sa.Column('structure_bb_rank', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('tradingsymbol', 'percentile_date')
    )
    op.create_index('idx_percentile_date', 'percentile', ['percentile_date'], unique=False)
    
    # Step 2: Copy data from 'ranking' to 'percentile' (renaming ranking_date to percentile_date)
    op.execute("""
        INSERT INTO percentile (tradingsymbol, percentile_date, ema_50_slope, trend_rank, 
            distance_from_ema_200, trend_extension_rank, distance_from_ema_50, trend_start_rank,
            rsi_signal_ema_3, momentum_rsi_rank, ppo_12_26_9, momentum_ppo_rank, ppoh_12_26_9,
            momentum_ppoh_rank, risk_adjusted_return, efficiency_rank, rvol, rvolume_rank,
            price_vol_correlation, price_vol_corr_rank, bbb_20_2, structure_rank, percent_b,
            structure_bb_rank)
        SELECT tradingsymbol, ranking_date, ema_50_slope, trend_rank, 
            distance_from_ema_200, trend_extension_rank, distance_from_ema_50, trend_start_rank,
            rsi_signal_ema_3, momentum_rsi_rank, ppo_12_26_9, momentum_ppo_rank, ppoh_12_26_9,
            momentum_ppoh_rank, risk_adjusted_return, efficiency_rank, rvol, rvolume_rank,
            price_vol_correlation, price_vol_corr_rank, bbb_20_2, structure_rank, percent_b,
            structure_bb_rank
        FROM ranking
    """)
    
    # Step 3: Drop old 'ranking' table
    op.drop_table('ranking')
    
    # Step 4: Create new 'ranking' table with structure for weekly rankings
    op.create_table('ranking',
        sa.Column('tradingsymbol', sa.String(length=50), nullable=False),
        sa.Column('ranking_date', sa.Date(), nullable=False),
        sa.Column('composite_score', sa.Float(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('tradingsymbol', 'ranking_date')
    )
    op.create_index('idx_ranking_date', 'ranking', ['ranking_date'], unique=False)
    op.create_index('idx_ranking_score', 'ranking', ['composite_score'], unique=False)
    
    # Step 5: Copy data from 'avg_score' to 'ranking' with rank calculated
    # Note: rank is calculated using window function ordering by composite_score desc per date
    op.execute("""
        INSERT INTO ranking (tradingsymbol, ranking_date, composite_score, rank)
        SELECT 
            tradingsymbol, 
            score_date,
            composite_score,
            ROW_NUMBER() OVER (PARTITION BY score_date ORDER BY composite_score DESC)
        FROM avg_score
    """)
    
    # Step 6: Drop old 'avg_score' table
    with op.batch_alter_table('avg_score', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('idx_avg_score'))
        batch_op.drop_index(batch_op.f('idx_avg_score_date'))
    op.drop_table('avg_score')


def downgrade():
    # Recreate avg_score from ranking
    op.create_table('avg_score',
        sa.Column('tradingsymbol', sa.String(length=50), nullable=False),
        sa.Column('score_date', sa.Date(), nullable=False),
        sa.Column('composite_score', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('tradingsymbol', 'score_date')
    )
    with op.batch_alter_table('avg_score', schema=None) as batch_op:
        batch_op.create_index('idx_avg_score_date', ['score_date'], unique=False)
        batch_op.create_index('idx_avg_score', ['composite_score'], unique=False)
    
    op.execute("""
        INSERT INTO avg_score (tradingsymbol, score_date, composite_score)
        SELECT tradingsymbol, ranking_date, composite_score FROM ranking
    """)
    
    # Drop new ranking table
    op.drop_table('ranking')
    
    # Recreate old ranking table from percentile
    op.create_table('ranking',
        sa.Column('tradingsymbol', sa.String(length=50), nullable=False),
        sa.Column('ranking_date', sa.Date(), nullable=False),
        sa.Column('ema_50_slope', sa.Float(), nullable=True),
        sa.Column('trend_rank', sa.Float(), nullable=True),
        sa.Column('distance_from_ema_200', sa.Float(), nullable=True),
        sa.Column('trend_extension_rank', sa.Float(), nullable=True),
        sa.Column('distance_from_ema_50', sa.Float(), nullable=True),
        sa.Column('trend_start_rank', sa.Float(), nullable=True),
        sa.Column('rsi_signal_ema_3', sa.Float(), nullable=True),
        sa.Column('momentum_rsi_rank', sa.Float(), nullable=True),
        sa.Column('ppo_12_26_9', sa.Float(), nullable=True),
        sa.Column('momentum_ppo_rank', sa.Float(), nullable=True),
        sa.Column('ppoh_12_26_9', sa.Float(), nullable=True),
        sa.Column('momentum_ppoh_rank', sa.Float(), nullable=True),
        sa.Column('risk_adjusted_return', sa.Float(), nullable=True),
        sa.Column('efficiency_rank', sa.Float(), nullable=True),
        sa.Column('rvol', sa.Float(), nullable=True),
        sa.Column('rvolume_rank', sa.Float(), nullable=True),
        sa.Column('price_vol_correlation', sa.Float(), nullable=True),
        sa.Column('price_vol_corr_rank', sa.Float(), nullable=True),
        sa.Column('bbb_20_2', sa.Float(), nullable=True),
        sa.Column('structure_rank', sa.Float(), nullable=True),
        sa.Column('percent_b', sa.Float(), nullable=True),
        sa.Column('structure_bb_rank', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('tradingsymbol', 'ranking_date')
    )
    op.create_index('idx_ranking_date', 'ranking', ['ranking_date'], unique=False)
    
    op.execute("""
        INSERT INTO ranking (tradingsymbol, ranking_date, ema_50_slope, trend_rank, 
            distance_from_ema_200, trend_extension_rank, distance_from_ema_50, trend_start_rank,
            rsi_signal_ema_3, momentum_rsi_rank, ppo_12_26_9, momentum_ppo_rank, ppoh_12_26_9,
            momentum_ppoh_rank, risk_adjusted_return, efficiency_rank, rvol, rvolume_rank,
            price_vol_correlation, price_vol_corr_rank, bbb_20_2, structure_rank, percent_b,
            structure_bb_rank)
        SELECT tradingsymbol, percentile_date, ema_50_slope, trend_rank, 
            distance_from_ema_200, trend_extension_rank, distance_from_ema_50, trend_start_rank,
            rsi_signal_ema_3, momentum_rsi_rank, ppo_12_26_9, momentum_ppo_rank, ppoh_12_26_9,
            momentum_ppoh_rank, risk_adjusted_return, efficiency_rank, rvol, rvolume_rank,
            price_vol_correlation, price_vol_corr_rank, bbb_20_2, structure_rank, percent_b,
            structure_bb_rank
        FROM percentile
    """)
    
    # Drop percentile table
    op.drop_table('percentile')
