"""The deployed app has no key and no Azure login: it must serve the cache and never call the agents.

Run:  python3 test_cache_only.py
Each scenario runs in its own Python process, with the Azure settings removed and the agent
libraries made unimportable (as in the slim container), then drives the app and checks:
  - it starts and never hangs;
  - a cached text shows as "AI insight";
  - a cache miss shows the "Quick insight" template, with no call to Azure.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AZURE_SETTINGS = ("PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY",
                  "AZURE_OPENAI_DEPLOYMENT", "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_SECRET")
SECONDS_LIMIT = 60


def child(live_flag, empty_cache):
    """Runs inside the subprocess: the app, as the container would run it."""
    class NoAgents:                       # the slim image has none of these libraries
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in ("agent_framework", "azure", "openai"):
                raise ImportError(f"{name} is not installed in this container")
    sys.meta_path.insert(0, NoAgents())
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    import dotenv
    dotenv.load_dotenv = lambda *a, **k: False          # the container has no .env file to load
    from streamlit.testing.v1 import AppTest
    import insights
    from insights import filter_for, replay_to
    from perception import match_info

    asked = []                            # every attempt to reach the agents is recorded
    for name in ("generate_event_text", "generate_moment_text", "generate_report_text"):
        real = getattr(insights, name)
        setattr(insights, name, lambda *a, _name=name, _real=real, **k: (asked.append(_name), _real(*a, **k))[1])

    cache_file = insights.CACHE_PATH
    if empty_cache:                       # same match fingerprint, no texts: every request is a miss
        cache_file = os.path.join(tempfile.mkdtemp(), "empty_cache.json")
        with open(cache_file, "w") as f:
            json.dump({"_match": insights.cache_fingerprint()}, f)
        insights.CACHE_PATH = cache_file
    match = match_info()
    home = match["home"]
    moments = [m for m in replay_to(match, None, 10 ** 6)[2] if m["keeper_team"] == home]
    cache = json.load(open(os.path.join(HERE, "insight_cache.json")))
    cached = [m for m in moments if insights.moment_key(m["event_id"], "casual", home, "en", "eyes") in cache]
    target = (moments if empty_cache else cached)[0]

    started = time.time()
    at = AppTest.from_file(os.path.join(HERE, "app.py"), default_timeout=SECONDS_LIMIT)
    at.session_state.match_sec = 10 ** 6
    at.run()
    assert not at.exception, at.exception
    at.button(key=f"show_{target['event_id']}").click().run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    if empty_cache:
        assert "Quick insight" in text and "AI insight" not in text, "a miss must show the quick insight"
    else:
        assert "AI insight" in text, "a cached text must show as an AI insight"
    assert not asked, f"the app tried to reach the agents: {asked}"
    for name in ("agent_framework", "azure", "pipeline", "agents"):
        assert name not in sys.modules, f"{name} was imported: the agents were called"
    assert time.time() - started < SECONDS_LIMIT, "the app took too long"
    print("child ok")


def run_scenario(label, live_flag, empty_cache):
    env = {k: v for k, v in os.environ.items() if k not in AZURE_SETTINGS}
    env.pop("LAST_LINE_LIVE_AGENTS", None)
    if live_flag is not None:
        env["LAST_LINE_LIVE_AGENTS"] = live_flag
    started = time.time()
    done = subprocess.run([sys.executable, __file__, "child", "empty" if empty_cache else "real"],
                          env=env, capture_output=True, text=True, timeout=SECONDS_LIMIT * 2)
    assert done.returncode == 0 and "child ok" in done.stdout, (label, done.stdout[-500:], done.stderr[-1500:])
    print(f"ok  {label} ({time.time() - started:.0f} s)")


def main():
    run_scenario("LIVE_AGENTS=0, no Azure settings: a cached text is an AI insight", "0", False)
    run_scenario("LIVE_AGENTS=0, no Azure settings: a cache miss is the quick insight", "0", True)
    run_scenario("LIVE_AGENTS on but no PROJECT_ENDPOINT (a misconfigured container): cache works", None, False)
    run_scenario("LIVE_AGENTS on but no PROJECT_ENDPOINT: a miss is the quick insight, nothing is called", None, True)
    print("all cache-only tests passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(None, sys.argv[2] == "empty")
    else:
        main()
