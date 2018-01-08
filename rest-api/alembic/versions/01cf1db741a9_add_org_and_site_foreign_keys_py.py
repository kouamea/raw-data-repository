"""add_org_and_site_foreign_keys.py

Revision ID: 01cf1db741a9
Revises: 5dc5d353452c
Create Date: 2018-01-08 15:06:47.061657

"""
from alembic import op
import sqlalchemy as sa
import model.utils
from sqlalchemy.dialects import mysql

from participant_enums import PhysicalMeasurementsStatus, QuestionnaireStatus, OrderStatus
from participant_enums import WithdrawalStatus, SuspensionStatus
from participant_enums import EnrollmentStatus, Race, SampleStatus, OrganizationType
from participant_enums import MetricSetType, MetricsKey
from model.site_enums import SiteStatus
from model.code import CodeType

# revision identifiers, used by Alembic.
revision = '01cf1db741a9'
down_revision = '5dc5d353452c'
branch_labels = None
depends_on = None


def upgrade(engine_name):
    globals()["upgrade_%s" % engine_name]()


def downgrade(engine_name):
    globals()["downgrade_%s" % engine_name]()



def upgrade_rdr():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('participant', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('participant', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('participant_history', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('participant_history', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('participant_summary', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column('participant_summary', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    # ### end Alembic commands ###


def downgrade_rdr():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('participant_summary', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('participant_summary', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('participant_history', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('participant_history', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('participant', 'site_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column('participant', 'organization_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    # ### end Alembic commands ###


def upgrade_metrics():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###


def downgrade_metrics():
    # ### commands auto generated by Alembic - please adjust! ###
    pass
    # ### end Alembic commands ###

