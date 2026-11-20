"""Render an offline, read-only snapshot without external assets."""

import json
from pathlib import Path

from .store import atomic_write, fingerprint, now
from .connections import summary


def render(engine):
    web = Path(__file__).resolve().parent.parent / "web"
    with engine.store.lock(), engine.store.read_snapshot():
        records = [engine.public(r, history=True) for r in engine.store.records()]
        snapshot = {"generated_at": now(), "revision": fingerprint([(r["id"], r["revision"]) for r in records])[:12],
                    "config": engine.store.config(), "records": records, "source_health": summary(records)}
        # Prevent source text from closing the inert JSON script element.
        data = json.dumps(snapshot, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        html = web.joinpath("explorer.html").read_text()
        html = html.replace("/* INLINE_STYLE */", web.joinpath("explorer.css").read_text() + "\n" + web.joinpath("life-map.css").read_text())
        for marker, source in (("INLINE_SCRIPT", "explorer.js"),
                               ("INLINE_GRAPH_MODEL", "life-graph-model.js"),
                               ("INLINE_GRAPH_3D", "vendor/graph3d.bundle.js"),
                               ("INLINE_LIFE_MAP", "life-map.js")):
            # Bundled dependency text must not terminate its inline script.
            script = web.joinpath(source).read_text().replace("</script", "<\\/script")
            html = html.replace("/* " + marker + " */", script)
        html = html.replace("__SNAPSHOT_JSON__", data)
        path = engine.store.safe(engine.store.root / ".local" / "overview.html")
        atomic_write(path, html)
        return path
