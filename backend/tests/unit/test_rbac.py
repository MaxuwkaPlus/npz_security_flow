import pytest

from app.domain.rbac import (
    MVP_ROLES,
    ROLE_PERMISSIONS,
    SEPARATED_PERMISSIONS,
    Permission,
    Principal,
    Role,
    can_assign_session,
    can_control_session,
    can_operate_session,
    can_read_report,
    can_read_session,
    is_assignable,
    permissions_for,
)


def principal(*roles: Role, subject_id: str = "operator-1") -> Principal:
    return Principal(user_id="u-1", subject_id=subject_id, roles=frozenset(roles))


def test_every_role_has_declared_permissions() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_permissions_of_several_roles_are_united() -> None:
    both = permissions_for({Role.TRAINEE, Role.EXPERT})

    assert both == ROLE_PERMISSIONS[Role.TRAINEE] | ROLE_PERMISSIONS[Role.EXPERT]
    assert Permission.SESSION_OPERATE in both
    assert Permission.PROPOSAL_REVIEW in both


def test_only_mvp_roles_are_assignable() -> None:
    assert set(MVP_ROLES) == {Role.TRAINEE, Role.INSTRUCTOR, Role.EXPERT, Role.SECURITY_ADMIN}
    for role in MVP_ROLES:
        assert is_assignable(role)
    for role in set(Role) - MVP_ROLES:
        assert not is_assignable(role)


# Требование: автор сценария не получает системные права автоматически вместе с
# правом на сценарии.
@pytest.mark.parametrize(
    "forbidden",
    [
        Permission.SAFETY_RULES_EDIT,
        Permission.SCORING_EDIT,
        Permission.RISK_MODEL_EDIT,
        Permission.RESULTS_DELETE,
        Permission.ACCOUNT_MANAGE,
    ],
)
def test_scenario_author_has_no_system_permissions(forbidden: Permission) -> None:
    assert forbidden not in ROLE_PERMISSIONS[Role.SCENARIO_AUTHOR]


def test_support_has_no_access_to_report_content() -> None:
    support = ROLE_PERMISSIONS[Role.SUPPORT]

    assert Permission.REPORT_READ_ANY not in support
    assert Permission.REPORT_READ_OWN not in support
    assert Permission.DATA_EXPORT not in support


def test_trainee_is_limited_to_own_training() -> None:
    trainee = ROLE_PERMISSIONS[Role.TRAINEE]

    assert trainee == {
        Permission.CATALOG_READ,
        Permission.SESSION_OPERATE,
        Permission.SESSION_READ_OWN,
        Permission.REPORT_READ_OWN,
    }


def test_instructor_runs_training_but_does_not_edit_configuration() -> None:
    instructor = ROLE_PERMISSIONS[Role.INSTRUCTOR]

    assert Permission.SESSION_CREATE in instructor
    assert Permission.SESSION_CONTROL in instructor
    assert (
        not {
            Permission.SCENARIO_EDIT,
            Permission.SAFETY_RULES_EDIT,
            Permission.SCORING_EDIT,
            Permission.RESULTS_DELETE,
        }
        & instructor
    )


def test_instructor_does_not_operate_console_instead_of_trainee() -> None:
    assert Permission.SESSION_OPERATE not in ROLE_PERMISSIONS[Role.INSTRUCTOR]


def test_expert_reviews_proposals_without_editing_scenario() -> None:
    expert = ROLE_PERMISSIONS[Role.EXPERT]

    assert Permission.PROPOSAL_REVIEW in expert
    assert Permission.SCENARIO_EDIT not in expert
    assert Permission.RISK_MODEL_EDIT not in expert


def test_security_admin_sees_audit_but_not_training_results() -> None:
    admin = ROLE_PERMISSIONS[Role.SECURITY_ADMIN]

    assert {Permission.AUDIT_READ, Permission.SECURITY_POLICY_MANAGE}.issubset(admin)
    assert Permission.REPORT_READ_ANY not in admin


def test_no_mvp_role_holds_every_separated_permission() -> None:
    """Ни одна роль не должна собирать все критичные права разом."""

    for role in MVP_ROLES:
        assert not SEPARATED_PERMISSIONS.issubset(ROLE_PERMISSIONS[role])


@pytest.mark.parametrize("permission", sorted(SEPARATED_PERMISSIONS))
def test_separated_permission_is_granted_deliberately(permission: Permission) -> None:
    """Критичное право выдано максимум одной роли MVP: иначе разделение мнимое."""

    holders = [role for role in MVP_ROLES if permission in ROLE_PERMISSIONS[role]]

    assert len(holders) <= 1


def test_own_session_is_visible_to_trainee_and_foreign_is_not() -> None:
    trainee = principal(Role.TRAINEE, subject_id="operator-1")

    assert can_read_session(trainee, "operator-1")
    assert not can_read_session(trainee, "operator-2")


def test_instructor_sees_any_session() -> None:
    instructor = principal(Role.INSTRUCTOR, subject_id="instructor-1")

    assert can_read_session(instructor, "operator-2")
    assert can_read_report(instructor, "operator-2")


def test_security_admin_sees_session_without_report() -> None:
    admin = principal(Role.SECURITY_ADMIN, subject_id="iso-1")

    assert can_read_session(admin, "operator-1")
    assert not can_read_report(admin, "operator-1")


def test_console_is_available_only_to_assigned_trainee() -> None:
    assert can_operate_session(principal(Role.TRAINEE, subject_id="operator-1"), "operator-1")
    assert not can_operate_session(principal(Role.TRAINEE, subject_id="operator-1"), "operator-2")
    assert not can_operate_session(principal(Role.INSTRUCTOR, subject_id="instructor-1"), "operator-1")


# --- самостоятельное прохождение ---------------------------------------


def test_guest_role_is_never_assignable_to_an_account() -> None:
    """Гостевую роль выдаёт себе сервер вместе с токеном.

    Если бы её можно было назначить учётной записи, постоянный пользователь получил
    бы право вести ход прохождения в обход инструктора — то самое разделение
    полномочий, ради которого SESSION_CONTROL отделён от работы за пультом.
    """

    assert Role.GUEST not in MVP_ROLES
    assert not is_assignable(Role.GUEST)


def test_guest_is_limited_to_own_training() -> None:
    guest = ROLE_PERMISSIONS[Role.GUEST]

    assert guest == {
        Permission.CATALOG_READ,
        Permission.SESSION_CREATE,
        Permission.SESSION_CONTROL_OWN,
        Permission.SESSION_OPERATE,
        Permission.SESSION_READ_OWN,
        Permission.REPORT_READ_OWN,
    }


def test_guest_runs_only_its_own_session() -> None:
    guest = principal(Role.GUEST, subject_id="guest-a1b2c3d4")

    assert can_control_session(guest, "guest-a1b2c3d4")
    assert not can_control_session(guest, "operator-1")


def test_instructor_runs_any_session() -> None:
    instructor = principal(Role.INSTRUCTOR, subject_id="instructor-1")

    assert can_control_session(instructor, "operator-2")


def test_trainee_with_instructor_does_not_run_the_session() -> None:
    """Обучаемый с учётной записью работает за пультом, но ход ведёт инструктор."""

    assert not can_control_session(principal(Role.TRAINEE, subject_id="operator-1"), "operator-1")


def test_session_is_assigned_to_others_only_by_instructor() -> None:
    guest = principal(Role.GUEST, subject_id="guest-a1b2c3d4")
    instructor = principal(Role.INSTRUCTOR, subject_id="instructor-1")

    assert can_assign_session(guest, "guest-a1b2c3d4")
    assert not can_assign_session(guest, "operator-1")
    assert can_assign_session(instructor, "operator-1")


def test_trainee_cannot_assign_training_even_to_itself() -> None:
    """Именное обучение назначает инструктор — иначе учебный план не его."""

    assert not can_assign_session(principal(Role.TRAINEE, subject_id="operator-1"), "operator-1")
