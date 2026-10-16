"""The S4-minor documentation and tooling issues (#249 #250 #251 #266 #267 #268 #273).

Where an issue is a pointer or a statement in prose, the test pins it against the thing it
points at, so it fails when either side moves.
"""
import re

from gym_continuousDoubleAuction.envs.layout_version import check_layout_stamp, layout_stamp


def _section_title(doc, number):
    for line in open(doc, encoding="utf-8"):
        match = re.match(rf"^## {number}\. (.+)$", line)
        if match:
            return match.group(1)
    return None


class TestTheLayoutMismatchPointer:
    """#273: the refusal pointed at doc/05 section 1 ("Shape at a glance"); the text about
    checkpoints and layout stamps is section 10."""

    @staticmethod
    def _message():
        stamp = layout_stamp()
        stamp["observation_version"] = 1
        try:
            check_layout_stamp({"layout": stamp}, "ckpt")
        except ValueError as error:
            return str(error)
        raise AssertionError("a v1 stamp was accepted")

    def test_it_names_section_10(self):
        assert "doc/05 section 10" in self._message()

    def test_that_section_is_the_compatibility_one(self):
        number = re.search(r"doc/05 section (\d+)", self._message()).group(1)
        assert _section_title("doc/05_observation_space.md", number) == "Compatibility"
