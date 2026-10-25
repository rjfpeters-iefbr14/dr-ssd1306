from PIL import Image

from dr_ssd1306.server import cli
from dr_ssd1306.server.model import Engine
from dr_ssd1306.server.render import colorize, render


def test_all_states_and_max_values_render(clock):
    engine = Engine(clock=clock)
    engine.update({"event_id": "XYZ-999", "baseline_kw": 99.9, "demand_kw": 0, "requested_kw": 0.1})
    images = []
    for action in ("ready", "schedule", "start", "complete", "link-lost"):
        image = render(engine.action(action))
        assert image.size == (128, 64)
        assert image.mode == "1"
        assert image.getbbox() is not None
        images.append(image.tobytes())
    assert len(set(images)) == 5


def test_color_is_fixed_by_physical_row():
    colored = colorize(Image.new("1", (128, 64), 1))
    assert colored.getpixel((20, 15)) == (255, 216, 48)
    assert colored.getpixel((20, 16)) == (40, 185, 255)
    assert colorize(Image.new("1", (128, 64))).getbbox() is None


def test_rotation_keeps_physical_color_regions_fixed():
    image = Image.new("1", (128, 64))
    image.putpixel((0, 0), 1)
    assert colorize(image, rotation=180).getpixel((127, 63)) == (40, 185, 255)


def test_render_command_saves_a_still(tmp_path):
    for raw, mode in ((False, "RGB"), (True, "1")):
        output = tmp_path / f"screen-{raw}.png"
        cli.main(["render", "--output", str(output)] + (["--raw"] if raw else []))
        with Image.open(output) as image:
            assert (image.size, image.mode) == ((128, 64), mode)
