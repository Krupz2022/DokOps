from app.models.blueprint import Blueprint, BlueprintSource, BlueprintAssignment, BlueprintRun, ResourceResult  # noqa: F401


def test_blueprint_models_roundtrip(isolated_session):
    sf = Blueprint(name="nginx", yaml_body="resources: []")
    isolated_session.add(sf)
    isolated_session.commit()
    isolated_session.refresh(sf)

    src = BlueprintSource(blueprint_id=sf.id, name="nginx.conf", content="server {}")
    asn = BlueprintAssignment(blueprint_id=sf.id, scope_type="group", scope_id="g1")
    isolated_session.add(src)
    isolated_session.add(asn)
    isolated_session.commit()

    assert sf.id
    assert src.blueprint_id == sf.id
    assert asn.scope_type == "group"
