"""Fictional sample data for local development and demos.

Run with: uv run flask seed
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Category, Contract, License, LicenseAllocation, Role, School, Setting, User, Vendor,
)

TODAY = date.today()


def _get_or_create(model, defaults=None, **kwargs):
    instance = model.query.filter_by(**kwargs).first()
    if instance:
        return instance
    params = {**kwargs, **(defaults or {})}
    instance = model(**params)
    db.session.add(instance)
    db.session.flush()
    return instance


def run_seed():
    # Assumes `flask db upgrade` has already created the schema.

    # Roles
    for name in Role.ALL:
        _get_or_create(Role, name=name)
    db.session.commit()

    admin_role = Role.query.filter_by(name=Role.ADMINISTRATOR).first()
    it_role = Role.query.filter_by(name=Role.IT_ADMINISTRATOR).first()
    curriculum_role = Role.query.filter_by(name=Role.CURRICULUM_ADMINISTRATOR).first()
    school_role = Role.query.filter_by(name=Role.SCHOOL_ADMINISTRATOR).first()
    viewer_role = Role.query.filter_by(name=Role.VIEWER).first()

    # Default settings (spec section 8)
    Setting.set_value("critical_days", 30)
    Setting.set_value("warning_days", 60)
    Setting.set_value("upcoming_days", 90)
    Setting.set_value("high_utilization_pct", 90)
    Setting.set_value("over_allocated_pct", 100)
    db.session.commit()

    # Categories
    for name in Category.DEFAULTS:
        _get_or_create(Category, name=name)
    db.session.commit()

    curriculum_cat = Category.query.filter_by(name="Curriculum").first()
    assessment_cat = Category.query.filter_by(name="Assessment").first()
    lms_cat = Category.query.filter_by(name="Learning Management").first()
    sis_cat = Category.query.filter_by(name="Student Information").first()

    # Schools - fictional district
    schools_data = [
        ("Calexico High School", "CHS-01", "High School", "Maria Gonzalez", "9,10,11,12", 1450),
        ("Enrique Camarena Junior High", "ECJ-02", "Middle School", "David Park", "6,7,8", 820),
        ("William Moreno Junior High", "WMJ-03", "Middle School", "Angela Reyes", "6,7,8", 780),
        ("Jefferson Elementary School", "JES-04", "Elementary", "Thomas Lee", "K,1,2,3,4,5", 610),
        ("Rockwood Elementary School", "RES-05", "Elementary", "Susan Villa", "K,1,2,3,4,5", 540),
        ("District Office", "DO-00", "District Office", "N/A", None, 0),
    ]
    schools = {}
    for name, code, school_type, principal, grades, count in schools_data:
        schools[name] = _get_or_create(
            School, code=code,
            defaults=dict(name=name, school_type=school_type, principal=principal, grades=grades, student_count=count),
        )
    db.session.commit()

    # Vendors
    vendors_data = [
        ("IXL Learning", "https://www.ixl.com", "support@ixl.example.com", "800-555-0101", "Jamie Cole"),
        ("Curriculum Associates", "https://www.curriculumassociates.com", "support@curriculumassociates.example.com", "800-555-0102", "Priya Nair"),
        ("Benchmark Education", "https://www.benchmarkeducation.com", "support@benchmark.example.com", "800-555-0103", "Chris Adams"),
        ("Canvas (Instructure)", "https://www.instructure.com", "support@instructure.example.com", "800-555-0104", "Sam Rivera"),
        ("Clever", "https://clever.com", "support@clever.example.com", "800-555-0105", "Alex Kim"),
    ]
    vendors = {}
    for name, website, email, phone, manager in vendors_data:
        vendors[name] = _get_or_create(
            Vendor, name=name,
            defaults=dict(website=website, support_email=email, support_phone=phone, account_manager=manager),
        )
    db.session.commit()

    # Contracts - created under a vendor first, per the district's real
    # setup order (School -> Vendor -> Contract -> License). Vendor contact
    # is a term of the agreement and lives here; annual cost lives on the
    # License(s) it covers instead, since one contract can bundle several.
    contract_plan = [
        ("CN-2026-IXL-01", "IXL Learning", TODAY - timedelta(days=347), TODAY + timedelta(days=18),
         "Annual", True, "Jamie Cole", 112000),
        ("CN-2026-CA-02", "Curriculum Associates", TODAY - timedelta(days=292), TODAY + timedelta(days=73),
         "Annual", True, "Priya Nair", 135000),
        ("CN-2025-BM-03", "Benchmark Education", TODAY - timedelta(days=362), TODAY - timedelta(days=3),
         "Annual", False, "Chris Adams", 78000),
        ("CN-2026-CV-04", "Canvas (Instructure)", TODAY - timedelta(days=155), TODAY + timedelta(days=210),
         "Multi-Year", True, "Sam Rivera", 95000),
        ("CN-2026-CL-05", "Clever", TODAY - timedelta(days=65), TODAY + timedelta(days=300),
         "Annual", True, "Alex Kim", 42000),
    ]
    contracts = {}
    for number, vendor_name, start, end, freq, auto, contact, amount in contract_plan:
        contracts[vendor_name] = _get_or_create(
            Contract, po_number=number,
            defaults=dict(
                vendor_id=vendors[vendor_name].id,
                start_date=start, end_date=end, renewal_date=end - timedelta(days=30),
                vendor_contact=contact, payment_frequency=freq, auto_renewal=auto,
                cancellation_deadline=end - timedelta(days=45), annual_cost=amount,
            ),
        )
    db.session.commit()

    # Licenses - added under their contract, taking that contract's vendor
    # and dates (start/expiration/renewal all live on the Contract now).
    license_data = [
        dict(name="IXL", vendor=vendors["IXL Learning"], contract=contracts["IXL Learning"], category=curriculum_cat,
             license_count=4000,
             description="Math and Language Arts practice platform."),
        dict(name="i-Ready", vendor=vendors["Curriculum Associates"], contract=contracts["Curriculum Associates"], category=assessment_cat,
             license_count=5000,
             description="Adaptive diagnostic and instruction for reading and math."),
        dict(name="Benchmark", vendor=vendors["Benchmark Education"], contract=contracts["Benchmark Education"], category=curriculum_cat,
             license_count=3000,
             description="K-6 literacy curriculum."),
        dict(name="Canvas", vendor=vendors["Canvas (Instructure)"], contract=contracts["Canvas (Instructure)"], category=lms_cat,
             license_count=2500,
             description="Learning management system."),
        dict(name="Clever", vendor=vendors["Clever"], contract=contracts["Clever"], category=sis_cat,
             license_count=6000,
             description="Single sign-on and rostering."),
    ]
    licenses = {}
    for data in license_data:
        name = data.pop("name")
        vendor = data.pop("vendor")
        contract = data.pop("contract")
        category = data.pop("category")
        licenses[name] = _get_or_create(
            License, name=name,
            defaults=dict(vendor=vendor, contract=contract, category=category, status="Active", **data),
        )
    db.session.commit()

    # Allocations (kept within each license's license_count)
    allocation_plan = {
        "IXL": [("Calexico High School", 800), ("Enrique Camarena Junior High", 700),
                ("William Moreno Junior High", 650), ("Rockwood Elementary School", 500),
                ("Jefferson Elementary School", 450)],
        "i-Ready": [("Calexico High School", 950), ("Enrique Camarena Junior High", 725),
                    ("William Moreno Junior High", 680), ("Jefferson Elementary School", 510)],
        "Benchmark": [("Jefferson Elementary School", 1600), ("Rockwood Elementary School", 1300)],
        "Canvas": [("Calexico High School", 1450), ("Enrique Camarena Junior High", 820), ("William Moreno Junior High", 230)],
        "Clever": [("Calexico High School", 1450), ("Enrique Camarena Junior High", 820),
                   ("William Moreno Junior High", 780), ("Jefferson Elementary School", 610),
                   ("Rockwood Elementary School", 540)],
    }
    for lic_name, allocations in allocation_plan.items():
        lic = licenses[lic_name]
        for school_name, count in allocations:
            _get_or_create(
                LicenseAllocation, license_id=lic.id, school_id=schools[school_name].id,
                defaults=dict(allocated_count=count),
            )
    db.session.commit()

    # Users - fictional accounts, one per role
    users_data = [
        ("victor.solis@licensehubk12.example.org", "Victor", "Solis", admin_role, None),
        ("maria.tech@licensehubk12.example.org", "Maria", "Tech", it_role, None),
        ("carlos.curriculum@licensehubk12.example.org", "Carlos", "Curriculum", curriculum_role, None),
        ("angela.reyes@licensehubk12.example.org", "Angela", "Reyes", school_role, schools["William Moreno Junior High"].id),
        ("viewer@licensehubk12.example.org", "Dana", "Viewer", viewer_role, None),
    ]
    for email, first, last, role, school_id in users_data:
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, first_name=first, last_name=last, role_id=role.id, school_id=school_id)
            user.set_password("ChangeMe!2026")
            db.session.add(user)
    db.session.commit()

    print("Seeded roles, categories, schools, vendors, licenses, allocations, contracts and demo users.")
    print("Demo login: victor.solis@licensehubk12.example.org / ChangeMe!2026")
