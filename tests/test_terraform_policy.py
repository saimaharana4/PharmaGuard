import pytest

from ci.terraform_policy import check


def resource(actions, kind="google_compute_instance"):
    return {
        "resource_changes": [
            {"address": "module.app.vm", "type": kind, "change": {"actions": actions}}
        ]
    }


def test_update_and_create_are_permitted_but_destroy_and_secrets_are_not():
    for actions in [["create"], ["update"], ["no-op"]]:
        assert check(resource(actions))[0]["actions"] == actions
    for actions in [["delete"], ["delete", "create"], ["create", "delete"]]:
        with pytest.raises(ValueError, match="prohibited"):
            check(resource(actions))
    for kind in ["google_secret_manager_secret_version", "google_sql_database_instance"]:
        with pytest.raises(ValueError):
            check(resource(["create"], kind))
