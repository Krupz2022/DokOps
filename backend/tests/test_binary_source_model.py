from app.models.blueprint import BlueprintSource


def test_source_encoding_defaults_utf8(isolated_session):
    s = BlueprintSource(blueprint_id="b1", name="x", content="hi")
    isolated_session.add(s); isolated_session.commit(); isolated_session.refresh(s)
    assert s.encoding == "utf-8"


def test_source_encoding_base64(isolated_session):
    s = BlueprintSource(blueprint_id="b1", name="z.bin", content="QUJD", encoding="base64")
    isolated_session.add(s); isolated_session.commit(); isolated_session.refresh(s)
    assert s.encoding == "base64"
