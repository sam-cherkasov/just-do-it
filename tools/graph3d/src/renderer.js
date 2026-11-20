import {
  Scene, PerspectiveCamera, WebGLRenderer, SphereGeometry, OctahedronGeometry,
  MeshStandardMaterial, Mesh, AmbientLight, DirectionalLight, Vector2, Vector3,
  Raycaster, BufferGeometry, LineBasicMaterial, Line, Box3
} from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Deliberately event-driven. No physics or perpetual render loop.
export function create(host, {onSelect, onError, colors}) {
  let disposed = false, frame = 0, graph = {nodes: [], links: []}, selectedId = null;
  let renderCount = 0;
  const scene = new Scene();
  const camera = new PerspectiveCamera(44, 1, 1, 18000);
  const renderer = new WebGLRenderer({antialias: true, alpha: true, powerPreference: 'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.domElement.setAttribute('aria-label', '3D life map. Drag to rotate; scroll to zoom. Use the node list for keyboard navigation.');
  renderer.domElement.setAttribute('role', 'img');
  host.append(renderer.domElement);
  const labels = document.createElement('div');
  labels.className = 'map-labels';
  host.append(labels);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  controls.enablePan = true;
  controls.minDistance = 70;
  controls.maxDistance = 12000;
  controls.maxPolarAngle = Math.PI * 0.87;
  const light = new DirectionalLight(0xffffff, 2.3);
  light.position.set(200, 600, 800);
  scene.add(new AmbientLight(0xffffff, 2), light);
  const sphere = new SphereGeometry(1, 16, 10), diamond = new OctahedronGeometry(1);
  const meshes = new Map(), edges = [], buttons = new Map();
  const materials = new Set(), geometries = new Set();
  const raycaster = new Raycaster(), pointer = new Vector2();
  const abort = new AbortController();
  const listen = (target, event, fn) => target.addEventListener(event, fn, {signal: abort.signal});

  function color(n) {
    if (n.stale) return colors.amber;
    if (n.status === 'waiting') return colors.amber;
    if (['done', 'dropped', 'superseded'].includes(n.status)) return colors.muted;
    return n.type === 'task' ? colors.blue : colors.teal;
  }

  function draw() {
    frame = 0;
    if (disposed || document.hidden || !host.isConnected) return;
    renderer.render(scene, camera);
    renderCount++;
    // Sparse HTML labels stay sharp at every zoom. Full content remains in the side panel/list.
    const neighbors = new Set([selectedId]);
    for (const l of graph.links) if (l.source === selectedId || l.target === selectedId) {
      neighbors.add(l.source); neighbors.add(l.target);
    }
    const candidates = [...graph.nodes].sort((a, b) => (b.id === selectedId) - (a.id === selectedId) ||
      Number(neighbors.has(b.id)) - Number(neighbors.has(a.id)) || a.depth - b.depth);
    const occupied = [];
    for (const button of buttons.values()) button.hidden = true;
    for (const n of candidates) {
      if (graph.nodes.length > 15 && !neighbors.has(n.id) && !['area', 'goal'].includes(n.type)) continue;
      const point = new Vector3(n.x, n.y, n.z).project(camera);
      const x = (point.x + 1) * host.clientWidth / 2, y = (-point.y + 1) * host.clientHeight / 2 + 17;
      const width = n.id === selectedId ? 174 : 146, height = 50;
      if (point.z > 1 || point.z < -1 || x < width / 2 || x > host.clientWidth - width / 2 || y < 0 || y > host.clientHeight - height) continue;
      const rect = {x: x - width / 2, y, width, height};
      if (n.id !== selectedId && occupied.some(r => rect.x < r.x + r.width + 5 && rect.x + width + 5 > r.x && rect.y < r.y + r.height && rect.y + height > r.y)) continue;
      occupied.push(rect);
      const button = buttons.get(n.id);
      button.hidden = false;
      button.style.width = width + 'px';
      button.style.transform = `translate(${Math.round(rect.x)}px, ${Math.round(y)}px)`;
      button.classList.toggle('selected', n.id === selectedId);
    }
  }
  function requestRender() {
    if (!disposed && !document.hidden && !frame) frame = requestAnimationFrame(draw);
  }
  function resize() {
    if (!host.clientWidth || disposed) return;
    camera.aspect = host.clientWidth / host.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight);
    requestRender();
  }
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  controls.addEventListener('change', requestRender);
  listen(document, 'visibilitychange', () => {
    if (document.hidden && frame) { cancelAnimationFrame(frame); frame = 0; }
    else requestRender();
  });
  listen(renderer.domElement, 'webglcontextlost', event => {
    event.preventDefault();
    if (!disposed) onError('3D недоступен. Карта и задачи доступны в режиме 2D.');
  });
  let down = null;
  listen(renderer.domElement, 'pointerdown', event => { down = [event.clientX, event.clientY]; });
  listen(renderer.domElement, 'pointerup', event => {
    if (!down || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 6) return;
    down = null;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects([...meshes.values()])[0];
    if (hit) onSelect(hit.object.userData.id);
  });

  function clearGraph() {
    for (const object of [...meshes.values(), ...edges]) scene.remove(object);
    for (const material of materials) material.dispose();
    for (const geometry of geometries) geometry.dispose();
    meshes.clear(); edges.length = 0; materials.clear(); geometries.clear(); buttons.clear(); labels.replaceChildren();
  }
  function update(next) {
    clearGraph();
    graph = next;
    const positions = new Map(graph.nodes.map(n => [n.id, n]));
    const palette = new Map();
    for (const n of graph.nodes) {
      const tone = color(n);
      if (!palette.has(tone)) {
        const material = new MeshStandardMaterial({color: tone, roughness: 0.6, metalness: 0});
        palette.set(tone, material); materials.add(material);
      }
      const mesh = new Mesh(n.type === 'task' ? diamond : sphere, palette.get(tone));
      const radius = {area: 15, goal: 11, strategy: 9, outcome: 7, experiment: 7, task: 7}[n.type] || 7;
      mesh.scale.setScalar(radius);
      mesh.position.set(n.x, n.y, n.z);
      mesh.userData = {id: n.id, radius};
      scene.add(mesh); meshes.set(n.id, mesh);
      const label = document.createElement('button');
      label.type = 'button'; label.className = 'map-node-label';
      label.textContent = n.title + (n.hiddenChildren ? ` (+${n.hiddenChildren})` : '');
      label.title = n.title; label.dataset.nodeId = n.id;
      // Accessible list is the keyboard interface; projected labels are pointer shortcuts.
      label.tabIndex = -1;
      label.addEventListener('click', () => onSelect(n.id));
      buttons.set(n.id, label); labels.append(label);
    }
    for (const link of graph.links) {
      const a = positions.get(link.source), b = positions.get(link.target);
      if (!a || !b) continue;
      const geometry = new BufferGeometry().setFromPoints([new Vector3(a.x, a.y, a.z), new Vector3(b.x, b.y, b.z)]);
      const material = new LineBasicMaterial({color: colors.line, transparent: true, opacity: 0.65});
      const line = new Line(geometry, material);
      line.userData = link;
      scene.add(line); edges.push(line); materials.add(material); geometries.add(geometry);
    }
    select(selectedId);
    requestRender();
  }
  function select(id) {
    selectedId = id;
    for (const mesh of meshes.values()) mesh.scale.setScalar(mesh.userData.radius * (mesh.userData.id === id ? 1.4 : 1));
    for (const edge of edges) {
      const active = edge.userData.source === id || edge.userData.target === id;
      edge.material.color.set(active ? colors.teal : colors.line);
      edge.material.opacity = active ? 1 : 0.55;
    }
    requestRender();
  }
  function fit(ids = null) {
    const chosen = graph.nodes.filter(n => !ids || ids.has(n.id));
    if (!chosen.length) return;
    const bounds = new Box3().setFromPoints(chosen.map(n => new Vector3(n.x, n.y, n.z)));
    const center = bounds.getCenter(new Vector3()), size = bounds.getSize(new Vector3());
    const distance = size.z / 2 + Math.max(size.y + 100, (size.x + 210) / camera.aspect, 260) / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.15;
    controls.maxDistance = Math.max(12000, distance * 3);
    controls.target.copy(center);
    camera.position.copy(center).add(new Vector3(distance * 0.11, distance * 0.11, distance));
    controls.update(); requestRender();
  }
  resize();
  return {
    update, select, fit,
    stats: () => ({renders: renderCount, nodes: meshes.size, disposed, geometries: renderer.info.memory.geometries}),
    destroy() {
      if (disposed) return;
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect(); abort.abort();
      controls.removeEventListener('change', requestRender); controls.dispose();
      clearGraph(); sphere.dispose(); diamond.dispose(); renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove(); labels.remove();
    }
  };
}
