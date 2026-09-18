"""A-15 tenant/access foundation; preserve C0 data and provenance.

Non-demo legacy houses get an isolated suspended/unverified management, never a
fabricated active company. Their records remain intact pending verified setup.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0002"
down_revision: str | None = "20260917_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute("""
        ALTER TABLE users ADD COLUMN platform_role varchar(30),
        ADD CONSTRAINT ck_users_platform_role
            CHECK (platform_role IS NULL OR platform_role = 'superadmin')
    """)
    op.execute("""
        CREATE TABLE management_companies (
            id uuid PRIMARY KEY, name varchar(200) NOT NULL,
            status varchar(30) NOT NULL DEFAULT 'active',
            is_demo boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_management_companies_status
                CHECK (status IN ('active', 'suspended', 'archived'))
        )
    """)
    op.execute("""
        CREATE TABLE house_managements (
            id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES management_companies(id) ON DELETE RESTRICT,
            house_id uuid NOT NULL REFERENCES houses(id) ON DELETE RESTRICT,
            valid_from timestamptz NOT NULL, valid_to timestamptz,
            status varchar(30) NOT NULL DEFAULT 'active',
            basis_type varchar(100), basis_reference varchar(500),
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            is_demo boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_management_id_house UNIQUE (id, house_id),
            CONSTRAINT ck_house_managements_period
                CHECK (valid_to IS NULL OR valid_to > valid_from),
            CONSTRAINT ck_house_managements_status CHECK (status IN ('active','suspended','ended')),
            CONSTRAINT ex_management_active_period EXCLUDE USING gist
                (house_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)
                WHERE (status = 'active')
        )
    """)
    for column in ("house_id", "tenant_id"):
        op.create_index(f"ix_house_managements_{column}", "house_managements", [column])
    op.execute("""
        CREATE INDEX ix_management_current ON house_managements(house_id, valid_from)
        WHERE status = 'active'
    """)
    op.execute("""
        CREATE TABLE organization_memberships (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES management_companies(id) ON DELETE CASCADE,
            role varchar(30) NOT NULL, status varchar(30) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_organization_user_tenant UNIQUE(user_id, tenant_id),
            CONSTRAINT ck_organization_memberships_role
                CHECK (role IN ('company_admin','operator')),
            CONSTRAINT ck_organization_memberships_status CHECK (status IN ('active','revoked'))
        )
    """)
    op.create_index(
        "ix_organization_memberships_tenant_id", "organization_memberships", ["tenant_id"]
    )
    op.execute("""
        CREATE TABLE house_assignments (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            management_id uuid NOT NULL REFERENCES house_managements(id) ON DELETE CASCADE,
            role varchar(30) NOT NULL, status varchar(30) NOT NULL DEFAULT 'active',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_assignment_user_management UNIQUE(user_id, management_id),
            CONSTRAINT ck_house_assignments_role CHECK (role IN ('responsible','operator')),
            CONSTRAINT ck_house_assignments_status CHECK (status IN ('active','revoked'))
        )
    """)
    op.create_index("ix_house_assignments_management_id", "house_assignments", ["management_id"])
    op.execute("ALTER TABLE house_memberships RENAME TO resident_memberships")
    op.execute("ALTER TABLE resident_memberships RENAME COLUMN role TO legacy_role")
    op.execute("ALTER TABLE resident_memberships RENAME COLUMN granted_at TO created_at")
    op.execute("""
        ALTER TABLE resident_memberships
            RENAME CONSTRAINT uq_house_memberships_user_house TO uq_resident_user_house
    """)
    for column in ("user_id", "house_id"):
        op.execute(
            f"ALTER INDEX ix_house_memberships_{column} RENAME TO ix_resident_memberships_{column}"
        )
    op.execute("""
        ALTER TABLE resident_memberships
            ALTER COLUMN legacy_role SET DEFAULT 'resident',
            ALTER COLUMN evidence_source SET DEFAULT 'manual',
            ADD COLUMN source varchar(100) NOT NULL DEFAULT 'manual',
            ADD COLUMN verification_level varchar(50) NOT NULL DEFAULT 'unverified',
            ADD COLUMN verified_at timestamptz,
            ADD COLUMN expires_at timestamptz,
            ADD COLUMN status varchar(30) NOT NULL DEFAULT 'active',
            ADD CONSTRAINT ck_resident_memberships_status
                CHECK (status IN ('active','revoked','expired'))
    """)
    op.execute("""
        UPDATE resident_memberships r SET source = CASE
            WHEN h.is_demo OR r.evidence_source = 'demo_seed' THEN 'demo'
            ELSE 'manual' END
        FROM houses h WHERE r.house_id = h.id
    """)
    op.execute("""
        INSERT INTO management_companies(id, name, is_demo)
        SELECT '00000000-0000-0000-0000-000000000301', 'Demo ManagementCompany', true
        WHERE EXISTS (SELECT 1 FROM houses WHERE is_demo)
    """)
    op.execute("""
        INSERT INTO management_companies(id, name, status)
        SELECT id, 'Unverified legacy management', 'suspended' FROM houses WHERE NOT is_demo
    """)
    op.execute("""
        INSERT INTO house_managements
            (id, tenant_id, house_id, valid_from, status, basis_type, is_demo)
        SELECT h.id, CASE WHEN h.is_demo
            THEN '00000000-0000-0000-0000-000000000301'::uuid ELSE h.id END,
            h.id, LEAST(h.created_at,
                (SELECT min(i.created_at) FROM incidents i WHERE i.house_id=h.id)),
            CASE WHEN h.is_demo THEN 'active' ELSE 'suspended' END,
            CASE WHEN h.is_demo THEN 'demo' ELSE 'legacy_unverified' END, h.is_demo
        FROM houses h
    """)
    op.execute("ALTER TABLE incidents ADD COLUMN management_id uuid")
    op.execute("UPDATE incidents SET management_id = house_id")
    op.execute("""
        ALTER TABLE incidents ALTER COLUMN management_id SET NOT NULL,
            ADD CONSTRAINT fk_incident_management_house FOREIGN KEY (management_id, house_id)
            REFERENCES house_managements(id, house_id) ON DELETE RESTRICT
    """)
    op.create_index("ix_incident_house_status", "incidents", ["house_id", "status"])
    op.create_index("ix_incident_management_status", "incidents", ["management_id", "status"])
    # Stable identities prevent moving history to another company by UPDATE.
    op.execute("""
        CREATE FUNCTION protect_management_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                OR NEW.house_id IS DISTINCT FROM OLD.house_id THEN
                RAISE EXCEPTION 'Management identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER management_identity BEFORE UPDATE ON house_managements
        FOR EACH ROW EXECUTE FUNCTION protect_management_identity()
    """)
    op.execute("""
        CREATE FUNCTION protect_incident_scope() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.management_id IS DISTINCT FROM OLD.management_id
                OR NEW.house_id IS DISTINCT FROM OLD.house_id THEN
                RAISE EXCEPTION 'Incident scope is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER incident_scope BEFORE UPDATE ON incidents
        FOR EACH ROW EXECUTE FUNCTION protect_incident_scope()
    """)


def downgrade() -> None:
    # A populated A-15 access model cannot be represented safely in C0. Fail
    # closed instead of silently restoring revoked grants or discarding staff.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE platform_role IS NOT NULL)
                OR EXISTS (SELECT 1 FROM organization_memberships)
                OR EXISTS (SELECT 1 FROM house_assignments)
                OR EXISTS (SELECT 1 FROM resident_memberships
                    WHERE status <> 'active' OR expires_at IS NOT NULL)
                OR EXISTS (SELECT 1 FROM house_managements WHERE id <> house_id) THEN
                RAISE EXCEPTION 'A-15 access data cannot be downgraded safely; restore a C0 backup';
            END IF;
        END $$
    """)
    op.execute("DROP TRIGGER incident_scope ON incidents")
    op.execute("DROP FUNCTION protect_incident_scope()")
    op.execute("DROP TRIGGER management_identity ON house_managements")
    op.execute("DROP FUNCTION protect_management_identity()")
    op.drop_index("ix_incident_management_status", table_name="incidents")
    op.drop_index("ix_incident_house_status", table_name="incidents")
    op.drop_constraint("fk_incident_management_house", "incidents", type_="foreignkey")
    op.drop_column("incidents", "management_id")
    op.drop_table("house_assignments")
    op.drop_table("organization_memberships")
    op.drop_table("house_managements")
    op.drop_table("management_companies")
    op.execute("ALTER TABLE resident_memberships DROP CONSTRAINT ck_resident_memberships_status")
    for column in ("source", "verification_level", "verified_at", "expires_at", "status"):
        op.drop_column("resident_memberships", column)
    op.execute("ALTER TABLE resident_memberships ALTER COLUMN legacy_role DROP DEFAULT")
    op.execute("ALTER TABLE resident_memberships ALTER COLUMN evidence_source DROP DEFAULT")
    op.execute("ALTER TABLE resident_memberships RENAME COLUMN legacy_role TO role")
    op.execute("ALTER TABLE resident_memberships RENAME COLUMN created_at TO granted_at")
    op.execute("""
        ALTER TABLE resident_memberships
        RENAME CONSTRAINT uq_resident_user_house TO uq_house_memberships_user_house
    """)
    for column in ("user_id", "house_id"):
        op.execute(
            f"ALTER INDEX ix_resident_memberships_{column} RENAME TO ix_house_memberships_{column}"
        )
    op.execute("ALTER TABLE resident_memberships RENAME TO house_memberships")
    op.execute("ALTER TABLE users DROP CONSTRAINT ck_users_platform_role")
    op.drop_column("users", "platform_role")
    # btree_gist may be shared with unrelated schemas; do not remove the extension.
