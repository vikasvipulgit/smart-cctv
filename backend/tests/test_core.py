"""Run with:  cd backend && pytest -q"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DETECTOR", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config_store import CameraConfig, RuleConfig, TimeWindow, Zone  # noqa: E402
from app.detection.color import hsv_to_name  # noqa: E402
from app.detection.detector import Detection  # noqa: E402
from app.detection.plates import looks_like_indian_plate, plate_matches  # noqa: E402
from app.rules.engine import RuleEngine, in_time_window, point_in_polygon  # noqa: E402
from app.search.prompt import parse_keywords, rule_from_prompt  # noqa: E402

SQUARE = [[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0]]
CAM = CameraConfig(id="gate", name="Gate", source="synthetic", zones=[Zone(name="gate_area", points=SQUARE)])


def det(x1, y1, x2, y2, label="person", tid=1, **kw):
    d = Detection(label=label, confidence=0.9, bbox=(x1, y1, x2, y2), track_id=tid, **kw)
    d.zones = RuleEngine.zones_for(d, CAM, 100, 100)
    return d


def test_point_in_polygon():
    assert point_in_polygon(0.75, 0.75, SQUARE)
    assert not point_in_polygon(0.25, 0.25, SQUARE)


def test_zone_rule_fires_once_then_cools_down():
    engine = RuleEngine([RuleConfig(id="r", name="R", classes=["person"], zone="gate_area", cooldown_seconds=30)])
    inside = det(60, 60, 80, 90)
    assert len(engine.evaluate(CAM, [inside], 100.0)) == 1
    assert len(engine.evaluate(CAM, [inside], 110.0)) == 0  # cooldown
    assert len(engine.evaluate(CAM, [inside], 131.0)) == 1


def test_outside_zone_and_wrong_class_ignored():
    engine = RuleEngine([RuleConfig(id="r", name="R", classes=["car"], zone="gate_area")])
    assert engine.evaluate(CAM, [det(10, 10, 20, 20, label="car")], 1.0) == []
    assert engine.evaluate(CAM, [det(60, 60, 80, 90, label="person")], 1.0) == []


def test_dwell_time():
    engine = RuleEngine([RuleConfig(id="r", name="R", zone="gate_area", min_dwell_seconds=5)])
    d = det(60, 60, 80, 90)
    assert engine.evaluate(CAM, [d], 0.0) == []
    assert engine.evaluate(CAM, [d], 3.0) == []
    assert len(engine.evaluate(CAM, [d], 6.0)) == 1


def test_colour_and_plate_rules():
    engine = RuleEngine([
        RuleConfig(id="white", name="W", classes=["car"], colors=["white"]),
        RuleConfig(id="plate", name="P", classes=["car"], plates=["MH12AB1234"]),
    ])
    car = det(60, 60, 80, 90, label="car", color="white", plate="MH12A81234")  # OCR read 8 for B
    fired = {m.rule.id for m in engine.evaluate(CAM, [car], 1.0)}
    assert fired == {"white", "plate"}


def test_time_window_overnight():
    assert in_time_window(datetime(2026, 1, 1, 23, 30), "22:00", "06:00")
    assert in_time_window(datetime(2026, 1, 1, 2, 0), "22:00", "06:00")
    assert not in_time_window(datetime(2026, 1, 1, 12, 0), "22:00", "06:00")
    engine = RuleEngine([RuleConfig(id="n", name="N", time_window=TimeWindow(start="22:00", end="06:00"))])
    assert engine.evaluate(CAM, [det(60, 60, 80, 90)], 1.0, datetime(2026, 1, 1, 12, 0)) == []


def test_plates():
    assert looks_like_indian_plate("MH 12 AB 1234")
    assert looks_like_indian_plate("22BH1234AA")
    assert plate_matches("MH12AB1Z34", ["MH12AB1234"]) == "MH12AB1234"
    assert plate_matches("KA01XY9999", ["MH12AB1234"]) is None


def test_colour_names():
    assert hsv_to_name(0, 0, 240) == "white"
    assert hsv_to_name(0, 0, 20) == "black"
    assert hsv_to_name(110, 200, 200) == "blue"


def test_prompt_parser():
    now = datetime(2026, 11, 25, 12, 0)
    f = parse_keywords("show every white SUV at the gate yesterday after 6 pm", now)
    assert f.labels == ["car"] and f.colors == ["white"]
    assert f.since == datetime(2026, 11, 24) and f.until == datetime(2026, 11, 25)
    assert f.hour_from == 18
    f2 = parse_keywords("trucks in the last 2 hours", now)
    assert f2.labels == ["truck"] and f2.since == datetime(2026, 11, 25, 10, 0)


def test_rule_from_prompt():
    r = rule_from_prompt("Alert me on telegram if anyone loiters after 11 pm for more than 20 seconds")
    assert r.classes == ["person"]
    assert r.time_window.start == "23:00"
    assert r.min_dwell_seconds == 20
    assert "telegram" in r.channels
    r2 = rule_from_prompt("Alert me if anyone is near the gate after midnight")
    assert r2.time_window.start == "00:00" and r2.time_window.end == "06:00"


# ------------------------------------------------------------------ zone editor (save to cameras.yaml)
import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.config_store import load_cameras, normalise_zones, save_camera_zones  # noqa: E402

CAMERAS_YAML = """# Header comment stays.
cameras:
  - id: gate
    name: Gate
    source: "${GATE_RTSP_URL}"   # password lives in .env
    zones:
      - name: gate_area
        points: [[0.10, 0.50], [0.90, 0.50], [0.90, 0.98]]

  # comment between cameras
  - id: yard
    name: Yard
    source: "synthetic"
    zones:
      - name: yard
        points: [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]

  # - id: example
  #   name: Commented-out example camera
"""


def test_normalise_zones_validates_and_clamps():
    zones = normalise_zones([Zone(name=" drive ", points=[[-0.2, 0.5], [1.3, 0.5], [0.123456, 0.9]])])
    assert zones[0].name == "drive"
    assert zones[0].points == [[0.0, 0.5], [1.0, 0.5], [0.1235, 0.9]]
    for bad in (
        [Zone(name="", points=SQUARE)],
        [Zone(name="a", points=SQUARE[:2])],
        [Zone(name="a", points=SQUARE), Zone(name="A", points=SQUARE)],
        [Zone(name="a", points=[[0.1, 0.2, 0.3], [0, 0], [1, 1]])],
    ):
        with pytest.raises(ValueError):
            normalise_zones(bad)


def test_save_camera_zones_keeps_comments_and_other_cameras(tmp_path, monkeypatch):
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML)
    monkeypatch.setattr(settings, "cameras_file", path)

    new = [Zone(name="drive", points=[[0.2, 0.2], [0.8, 0.2], [0.5, 0.9]])]
    save_camera_zones("gate", new)
    save_camera_zones("yard", [])  # last camera, empty list
    text = path.read_text()
    for kept in ("# Header comment stays.", "# password lives in .env", "# comment between cameras",
                 "#   name: Commented-out example camera", 'source: "${GATE_RTSP_URL}"'):
        assert kept in text, kept
    cams = {c.id: c for c in load_cameras()}
    assert [z.name for z in cams["gate"].zones] == ["drive"]
    assert cams["yard"].zones == []
    assert cams["gate"].source == "${GATE_RTSP_URL}"  # never resolved into the file

    save_camera_zones("yard", [Zone(name="yard", points=SQUARE)])  # empty -> zones again
    assert "#   name: Commented-out example camera" in path.read_text()
    with pytest.raises(KeyError):
        save_camera_zones("missing", new)


def test_new_zones_apply_to_detection():
    cam = CameraConfig(id="c", name="C", source="synthetic", zones=[Zone(name="left", points=[[0, 0], [0.5, 0], [0.5, 1], [0, 1]])])
    d = Detection(label="person", confidence=0.9, bbox=(60, 10, 80, 90), track_id=1)
    assert RuleEngine.zones_for(d, cam, 100, 100) == []
    cam.zones = normalise_zones([Zone(name="right", points=[[0.5, 0], [1, 0], [1, 1], [0.5, 1]])])
    assert RuleEngine.zones_for(d, cam, 100, 100) == ["right"]


# ------------------------------------------------------------------ camera on/off switch
from app.config_store import save_camera_enabled  # noqa: E402


def test_save_camera_enabled_keeps_file(tmp_path, monkeypatch):
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML.replace('    source: "synthetic"\n', '    source: "synthetic"\n    enabled: true\n'))
    monkeypatch.setattr(settings, "cameras_file", path)
    save_camera_enabled("yard", False)
    save_camera_enabled("gate", False)  # no enabled key yet: inserted after source, not at the end
    cams = {c.id: c for c in load_cameras()}
    assert not cams["gate"].enabled and not cams["yard"].enabled
    text = path.read_text()
    assert text.index("enabled: false") < text.index("# password lives in .env") + 40
    for kept in ("# Header comment stays.", "# comment between cameras", "#   name: Commented-out example camera"):
        assert kept in text
    save_camera_enabled("yard", True)
    assert {c.id: c.enabled for c in load_cameras()} == {"gate": False, "yard": True}


def test_pipeline_set_enabled_starts_and_stops_one_camera(monkeypatch):
    from app.pipeline import manager as m

    class FakeWorker:
        def __init__(self, cam, *a):
            self.cam, self.started, self.stopped = cam, False, False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        @property
        def status(self):
            return {"id": self.cam.id, "enabled": True}

    monkeypatch.setattr(m, "CameraWorker", FakeWorker)
    p = m.PipelineManager()
    p.cameras = [CameraConfig(id="a", name="A", source="synthetic"),
                 CameraConfig(id="b", name="B", source="0", enabled=False)]
    p._start_worker(p.cameras[0])
    a = p.workers["a"]
    p.set_enabled("b", True)
    assert p.workers["b"].started and p.cameras[1].enabled
    p.set_enabled("a", False)
    assert a.stopped and "a" not in p.workers and not p.cameras[0].enabled
    assert p.workers["b"].started and not p.workers["b"].stopped  # other camera untouched
    status = {s["id"]: s for s in p.camera_status() if s["id"] == "a"}
    assert status["a"]["enabled"] is False and status["a"]["source"] == "synthetic"
    with pytest.raises(KeyError):
        p.set_enabled("nope", True)


# ------------------------------------------------------------------ text/number rules, arrival mode, messages
from app.rules.engine import render_message  # noqa: E402


def text_det(value, conf=0.9):
    d = Detection(label="text", confidence=conf, bbox=(60, 60, 90, 80), text=value)
    d.zones = RuleEngine.zones_for(d, CAM, 100, 100)
    return d


def test_text_rule_reads_numbers_and_alerts_per_number():
    rule = RuleConfig(id="num", name="Number seen", text_pattern=r"\d{2,}", cooldown_seconds=60, classes=["person"])
    eng = RuleEngine([rule])
    m = eng.evaluate(CAM, [text_det("Room 4721"), text_det("A"), text_det("7")], 0)
    assert [x.matched_text for x in m] == ["4721"]  # classes ignored for text rules; "7" too short
    assert eng.evaluate(CAM, [text_det("4721")], 10) == []  # same number: cooldown
    assert [x.matched_text for x in eng.evaluate(CAM, [text_det("88")], 11)] == ["88"]  # new number alerts
    assert len(eng.evaluate(CAM, [text_det("4721")], 61)) == 1  # cooldown over
    assert eng.evaluate(CAM, [det(60, 60, 90, 90)], 70) == []  # people don't match a text rule
    assert eng.needs_text("gate") and not RuleEngine([RuleConfig(id="p", name="P")]).needs_text("gate")


def test_text_readings_never_match_object_rules():
    any_object = RuleEngine([RuleConfig(id="any", name="Anything", cooldown_seconds=0)])
    assert any_object.evaluate(CAM, [text_det("1234")], 0) == []


def test_invalid_text_pattern_rejected():
    with pytest.raises(ValueError):
        RuleConfig(id="bad", name="Bad", text_pattern="(")
    assert RuleConfig(id="e", name="E", text_pattern="").text_pattern is None


def test_per_camera_rule_alerts_once_per_arrival():
    eng = RuleEngine([RuleConfig(id="arr", name="Person seen", classes=["person"], per_camera=True, cooldown_seconds=30)])
    assert len(eng.evaluate(CAM, [det(60, 60, 90, 90, tid=1), det(10, 10, 20, 20, tid=2)], 0)) == 1
    for t, tid in ((5, 3), (20, 4), (45, 5)):  # tracker keeps giving new ids while the person stays
        assert eng.evaluate(CAM, [det(60, 60, 90, 90, tid=tid)], t) == []
    assert eng.evaluate(CAM, [], 50) == []  # person leaves...
    assert eng.evaluate(CAM, [det(60, 60, 90, 90, tid=6)], 70) == []  # ...back after 25 s: same visit
    assert len(eng.evaluate(CAM, [det(60, 60, 90, 90, tid=7)], 101)) == 1  # gone > 30 s: new arrival


def test_render_message():
    assert render_message("Number seen: {text} on {camera}", {"text": "4721", "camera": "Mac webcam"}) == "Number seen: 4721 on Mac webcam"
    assert render_message("{text.__class__} {missing}", {"text": "1"}) == "{text.__class__} {missing}"
    assert render_message(None, {"text": "1"}) is None


def test_missing_columns_added_to_old_database(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text
    import app.db as db

    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:  # an events table from before text/message existed
        conn.execute(text("CREATE TABLE events (id INTEGER PRIMARY KEY, camera_id VARCHAR(64), rule_id VARCHAR(64), "
                          "rule_name VARCHAR(128), label VARCHAR(64), acknowledged BOOLEAN)"))
    monkeypatch.setattr(db, "engine", old)
    db.init_db()
    cols = {c["name"] for c in inspect(old).get_columns("events")}
    assert {"text", "message", "plate", "snapshot_path"} <= cols


def test_ack_all_clears_open_alerts(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    import app.db as db
    from app.api.events import acknowledge_all
    from app.models import Event

    eng = create_engine(f"sqlite:///{tmp_path / 'ev.db'}")
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    s = sessionmaker(bind=eng)()
    s.add_all([Event(camera_id=c, rule_id="r", rule_name="R", label="person") for c in ("a", "a", "b")])
    s.commit()
    assert acknowledge_all(camera="b", session=s) == {"cleared": 1}
    assert acknowledge_all(session=s) == {"cleared": 2}
    assert all(s.scalars(select(Event.acknowledged)).all())


# ------------------------------------------------------------------ zone anchor modes
def test_zone_anchor_modes_for_webcam_close_ups():
    top_right = [[0.65, 0.09], [0.98, 0.09], [0.97, 0.55], [0.65, 0.54]]  # like zone_1 on the webcam
    # a person leaning into the top-right, cut off at the bottom of a 1280x720 frame
    leaning = Detection(label="person", confidence=0.9, bbox=(800, 80, 1260, 715))
    # a person sitting in the middle (the real box from the webcam: x 0.13-0.87, y 0.18-0.99)
    sitting = Detection(label="person", confidence=0.9, bbox=(166, 130, 1114, 713))
    def zones(anchor, d):
        cam = CameraConfig(id="w", name="W", source="0", zones=[Zone(name="zone_1", points=top_right, anchor=anchor)])
        return RuleEngine.zones_for(d, cam, 1280, 720)
    assert zones("bottom", leaning) == [] and zones("bottom", sitting) == []  # feet are off-screen
    assert zones("overlap", leaning) == ["zone_1"]
    assert zones("overlap", sitting) == []  # only a corner of the box touches the zone
    assert zones("center", Detection(label="cup", confidence=0.9, bbox=(1000, 150, 1100, 250))) == ["zone_1"]


def test_zone_anchor_saved_and_validated(tmp_path, monkeypatch):
    path = tmp_path / "cameras.yaml"
    path.write_text(CAMERAS_YAML)
    monkeypatch.setattr(settings, "cameras_file", path)
    save_camera_zones("gate", normalise_zones([Zone(name="z", points=SQUARE, anchor="overlap"), Zone(name="f", points=SQUARE)]))
    assert "anchor: overlap" in path.read_text() and path.read_text().count("anchor:") == 1  # default not written
    assert [z.anchor for z in load_cameras()[0].zones] == ["overlap", "bottom"]
    with pytest.raises(ValueError):
        Zone(name="x", points=SQUARE, anchor="head")
