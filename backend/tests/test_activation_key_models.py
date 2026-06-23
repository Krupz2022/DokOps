from app.models.activation_key import ActivationKey, KeyBlueprint  # noqa: F401
from app.models.minion import Minion
from app.models.blueprint import Blueprint  # noqa: F401


def test_activation_key_roundtrip(isolated_session):
    k = ActivationKey(name="win-web", value_hash="HASH", run_on_attach=True, created_by="admin")
    isolated_session.add(k)
    isolated_session.commit()
    isolated_session.refresh(k)
    isolated_session.add(KeyBlueprint(key_id=k.id, blueprint_id="bp1", position=0))
    isolated_session.commit()
    assert k.id and k.run_on_attach is True and k.enabled is True


def test_minion_has_bootstrapped_default_false(isolated_session):
    m = Minion(id="m1", hostname="m1")
    isolated_session.add(m)
    isolated_session.commit()
    isolated_session.refresh(m)
    assert m.bootstrapped is False
