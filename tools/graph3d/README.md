# Personal OS 3D renderer

Development-only tools. Python snapshot generation embeds the checked-in `web/vendor/graph3d.bundle.js`; users need neither Node nor network to open the result.

```sh
npm ci --prefix tools/graph3d
npm run build --prefix tools/graph3d
node --test tests/graph-model.test.cjs
python3 -B -m unittest discover -s tests -v
python3 -B scripts/demo_graph.py
```

The package lock pins Three.js 0.186.1 and esbuild 0.28.2. The bundle is an IIFE exposed as `PersonalOs3D`; `web/vendor/THIRD-PARTY-LICENSES.txt` preserves Three.js's MIT license. esbuild is a build tool and is not shipped inside the viewer. Rebuild the bundle after renderer edits. No personal records are bundled.

Pure graph semantics live in `web/life-graph-model.js`; DOM controls/card/list in `web/life-map.js`; renderer lifecycle and Three.js imports in `src/renderer.js`. Renderer inputs are derived projection objects, never the canonical record objects.

`demo_graph.py` produces a separate, explicitly synthetic diagnostics HTML with 100-node/300-link and 500-node/1,000-link workloads, a visible resize-driven render benchmark and a WebGL loss button. View it in a real browser at the current window size. The benchmark measures the render rate during resize interaction, not general hardware performance or behavioral usefulness. It never reads personal records or writes to calendar/project sources.
