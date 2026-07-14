"""promote training-sample labels to columns

Adds signal / diagram_type / model / prompt_version as real (indexed) columns on
training_samples so a trainer can filter without scanning + parsing the JSON blob.

Revision ID: a1b2c3d4e5f6
Revises: d6702b8388ae
Create Date: 2026-07-14 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd6702b8388ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('training_samples', schema=None) as batch_op:
        batch_op.add_column(sa.Column('signal', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('diagram_type', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('model', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('prompt_version', sa.String(), nullable=True))
        batch_op.create_index(batch_op.f('ix_training_samples_signal'), ['signal'], unique=False)
        batch_op.create_index(batch_op.f('ix_training_samples_diagram_type'), ['diagram_type'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('training_samples', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_training_samples_diagram_type'))
        batch_op.drop_index(batch_op.f('ix_training_samples_signal'))
        batch_op.drop_column('prompt_version')
        batch_op.drop_column('model')
        batch_op.drop_column('diagram_type')
        batch_op.drop_column('signal')
