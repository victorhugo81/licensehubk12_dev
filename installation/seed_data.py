# seed_data.py
#
# Interactive first-run seed: creates the five roles, a default District
# Office school, the standard category list, default license-status
# thresholds, and one Administrator user - the minimum needed to log in
# and start configuring a real district.
#
# For fictional demo data (sample vendors, software, schools, allocations,
# contracts) use `uv run flask seed` instead (see app/seed.py) - that
# command is meant for local development and demos, not production.
#
# Applies pending Alembic migrations itself before seeding (via
# flask_migrate.upgrade(), the same code path as `flask db upgrade`) so a
# freshly created-but-empty database (e.g. one just provisioned by
# create_env.py) doesn't need a separate manual migration step first. This
# still goes through Alembic rather than db.create_all(), so the
# alembic_version table stays correctly stamped either way.
import os
import sys
from getpass import getpass

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from flask_migrate import upgrade as db_upgrade
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()

from app import create_app
from app.extensions import db
from app.models import Category, Role, School, Setting, User

app = create_app()

admin_email = input("Enter admin email (e.g., admin@yourdistrict.edu): ").strip()
admin_password = getpass("Enter admin password (min 10 characters): ")
admin_first_name = input("Enter admin first name (default: Admin): ") or "Admin"
admin_last_name = input("Enter admin last name (default: User): ") or "User"
district_name = input("Enter your district/site name (default: District Office): ") or "District Office"

with app.app_context():
    print("Applying database migrations...")
    db_upgrade(directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))

    try:
        # --- Roles ---
        for name in Role.ALL:
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name))
                print(f"Role added: {name}")
            else:
                print(f"Role already exists: {name}")
        db.session.commit()

        # --- Default license-status thresholds ---
        Setting.set_value("critical_days", 30)
        Setting.set_value("warning_days", 60)
        Setting.set_value("upcoming_days", 90)
        Setting.set_value("high_utilization_pct", 90)
        Setting.set_value("over_allocated_pct", 100)
        db.session.commit()
        print("Default license-status thresholds set.")

        # --- Categories ---
        for name in Category.DEFAULTS:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name))
                print(f"Category added: {name}")
            else:
                print(f"Category already exists: {name}")
        db.session.commit()

        # --- Default site (District Office) ---
        site = School.query.filter_by(code="DO-00").first()
        if site:
            site.name = district_name
            print("District Office school updated.")
        else:
            site = School(name=district_name, code="DO-00", school_type="District Office")
            db.session.add(site)
            print("District Office school created.")
        db.session.commit()

        # --- Admin user ---
        admin_role = Role.query.filter_by(name=Role.ADMINISTRATOR).first()
        user = User.query.filter_by(email=admin_email).first()
        if user:
            user.first_name = admin_first_name
            user.last_name = admin_last_name
            user.role_id = admin_role.id
            user.is_active_account = True
            user.set_password(admin_password)
            print("Admin user updated.")
        else:
            user = User(
                first_name=admin_first_name,
                last_name=admin_last_name,
                email=admin_email,
                role_id=admin_role.id,
                is_active_account=True,
            )
            user.set_password(admin_password)
            db.session.add(user)
            print("Admin user created.")
        db.session.commit()

        print("\nAll data seeded successfully.")
        print(f"Sign in with: {admin_email}")

    except SQLAlchemyError as err:
        db.session.rollback()
        print(f"SQLAlchemy Error: {err}")
        raise SystemExit(1)
