"""Architecture test: the keeper's field of view is the INPUT.

Run:  python3 test_architecture.py

Rule 1: only the data layer may read the raw match. Every other module gets
        the match through perception.PerceptionFilter. "Reading the raw match"
        means importing load_match or stream from replay, or naming
        match_events.json.
Rule 2: the missed log never reaches the agents. agents.py and pipeline.py may
        not touch PerceptionFilter.missed or PerceptionFilter.reveal().

The check reads each file's source (with Python's ast module) instead of
running it, so it needs no Azure access.
"""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent

# The data layer: these may read the raw match
DATA_LAYER = {"generate_match.py", "replay.py", "scoring.py", "vision.py", "perception.py"}
RAW_NAMES = {"load_match", "stream"}
RAW_FILE = "match_events.json"
# Modules the agents' input passes through: they must never see the missed log
AGENT_SIDE = {"agents.py", "pipeline.py"}
MISSED_LOG = {"missed", "reveal"}


def raw_access(path):
    """Every place a module reads the raw match, as readable strings."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "replay":
            found += [f"line {node.lineno}: from replay import {a.name}"
                      for a in node.names if a.name in RAW_NAMES or a.name == "*"]
        elif isinstance(node, ast.Attribute) and node.attr in RAW_NAMES \
                and isinstance(node.value, ast.Name) and node.value.id == "replay":
            found.append(f"line {node.lineno}: replay.{node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and RAW_FILE in node.value:
            found.append(f"line {node.lineno}: names {RAW_FILE}")
    return found


def missed_log_access(path):
    tree = ast.parse(path.read_text())
    return [f"line {node.lineno}: .{node.attr}" for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in MISSED_LOG]


def consumer_modules():
    """Every module outside the data layer, tests and this file included out."""
    return sorted(p.name for p in ROOT.glob("*.py")
                  if p.name not in DATA_LAYER and not p.name.startswith("test_"))


class ArchitectureTest(unittest.TestCase):

    def assert_no_raw_access(self, name):
        found = raw_access(ROOT / name)
        self.assertEqual(found, [], f"{name} reads the raw match: {found}")

    # Rule 1, module by module, so a failure names the module
    def test_agents_reads_only_perception(self):
        self.assert_no_raw_access("agents.py")

    def test_pipeline_reads_only_perception(self):
        self.assert_no_raw_access("pipeline.py")

    def test_insights_reads_only_perception(self):
        self.assert_no_raw_access("insights.py")

    # app.py used to be the one marked expected failure: it loaded the raw match
    # for the old Broadcast view. Since the interface rework it reads only from
    # PerceptionFilter (through insights.py and perception.py), so it is now
    # checked like every other consumer.
    def test_app_reads_only_perception(self):
        self.assert_no_raw_access("app.py")

    def test_every_other_module_reads_only_perception(self):
        """Catches modules added later, too."""
        checked = {"agents.py", "pipeline.py", "insights.py", "app.py"}
        for name in consumer_modules():
            if name not in checked:
                with self.subTest(module=name):
                    self.assert_no_raw_access(name)

    # Rule 2
    def test_missed_log_never_reaches_the_agents(self):
        for name in sorted(AGENT_SIDE):
            with self.subTest(module=name):
                found = missed_log_access(ROOT / name)
                self.assertEqual(found, [], f"{name} touches the missed log: {found}")

    def test_the_check_itself_works(self):
        """Guard against a check that always passes: it must flag code that
        reads the raw match, and the data layer really does read it."""
        import tempfile
        self.assertTrue(raw_access(ROOT / "perception.py"))
        samples = {
            "import": "from replay import load_match\n",
            "attribute": "import replay\nreplay.stream(1, 2)\n",
            "file name": "open('match_events.json')\n",
        }
        with tempfile.TemporaryDirectory() as folder:
            for name, source in samples.items():
                path = pathlib.Path(folder) / "sample.py"
                path.write_text(source)
                self.assertTrue(raw_access(path), f"a {name} should be flagged")
            path.write_text("from replay import clock\n")
            self.assertEqual(raw_access(path), [], "importing clock is fine")
            path.write_text("agent.missed\nfilter.reveal()\n")
            self.assertEqual(len(missed_log_access(path)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
