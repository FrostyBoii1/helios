// Animated topographic backdrop — ONE WebGL system, two variants.
//
//   variant="hero"    -> the approved /login background (source of truth).
//   variant="ambient" -> the SAME system for the logged-in app shell, much
//                        more restrained: far slower morph, much lower opacity
//                        (CSS), a flat even field (no vignette), steel only (no
//                        orange), no sensor-sweep lines, cheaper res/fps. It
//                        stays gray/charcoal and never competes with content,
//                        yet still visibly re-forms if you watch a few seconds.
//
// A single fullscreen-triangle WebGL fragment shader computes a domain-warped,
// time-advected 4-octave FBM HEIGHT FIELD that slowly MORPHS, then extracts
// crisp anti-aliased ISO-LINES (real contour lines) with fract()/fwidth().
// Steel-gray lines form the base map; a DOUBLE-GATED sparse solar-orange
// highlight (gated by u_accent) marks "accent paths"; a baked radial vignette
// (gated by u_vignette) frames a centered card. The two gates are what let the
// hero and the ambient app-shell share the exact same shader.
//
// On top of the canvas (hero only): 2 hand-authored inline-SVG orange
// FIELD-LINES whose stroke-dashoffset animates a slow "sensor-sweep" light-trace.
//
// Cheap by construction (every brief guard):
//   - DPR IGNORED; internal backing store at variant resScale, hard-capped width
//   - 4 FBM octaves max
//   - variant fps via a rAF time-gate (acc accumulator => no time-jump on resume)
//   - rAF PAUSED on tab-hidden (visibilitychange) and CANCELLED on unmount
//   - low-power context, alpha/depth/stencil/antialias all off; context released
//     by GC on real unmount (we deliberately do NOT force-lose it in cleanup —
//     that poisons the canvas for React StrictMode / HMR / navigate-back remounts)
//   - prefers-reduced-motion => render ONE static frame, no loop, SVG trace parked lit
//   - no WebGL / no OES_standard_derivatives / compile|link fail => canvas hidden,
//     the premium layered CSS .contour-fallback (always painted underneath) shows
//
// Decorative + inert: aria-hidden, pointer-events:none, fixed inset behind content.

import { useEffect, useId, useRef, useState } from 'react'

export type ContourVariant = 'hero' | 'ambient'

interface VariantConfig {
  resScale: number // backing store vs CSS px (DPR ignored)
  maxBackingW: number // hard cap on internal width (px)
  fps: number
  timeScale: number // shader time units advanced per real second
  vignette: number // 0..1 — 1 frames a centered card, 0 = flat even field
  accent: number // 0..1 — orange accent strength (1 = hero, 0 = steel only)
  sweeps: boolean // render the orange sensor-sweep SVG field-lines
  rootClass: string
}

// Hero = the approved /login look (DO NOT change these values).
// Ambient = restrained app-shell variant (opacity lives in .contour-root--ambient).
const VARIANTS: Record<ContourVariant, VariantConfig> = {
  hero: {
    resScale: 0.55,
    maxBackingW: 1100,
    fps: 30,
    timeScale: 1.0,
    vignette: 1.0,
    accent: 1.0,
    sweeps: true,
    rootClass: 'contour-root',
  },
  ambient: {
    resScale: 0.4, // lower internal res — it's faint, never pixel-inspected
    maxBackingW: 900,
    fps: 18, // morph is slow, so a low frame rate is plenty (cheaper, battery)
    timeScale: 0.35, // ~3x slower than hero — calm, but alive if you watch
    vignette: 0.0, // flat even field across the whole shell (no card to frame)
    accent: 0.0, // steel only — orange is a hero signature; never compete
    sweeps: false,
    rootClass: 'contour-root contour-root--ambient',
  },
}

const VERT = `
attribute vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
`

// Palette: Helios tokens as 0..1 vec3 (sRGB):
//   bg #0F1011  steel ~#8A929C  orange #F2871E / #F7A23F
const FRAG = `
precision highp float;

uniform vec2  u_res;      // backing-store resolution (px)
uniform float u_time;     // advected time
uniform float u_vignette; // 0..1 vignette strength (1 hero, 0 flat field)
uniform float u_accent;   // 0..1 orange accent strength (1 hero, 0 steel only)

const vec3 BG        = vec3(0.059, 0.063, 0.066); // #0F1011
const vec3 BG_TOP    = vec3(0.082, 0.086, 0.094); // subtle top lift #15161A
const vec3 STEEL     = vec3(0.541, 0.573, 0.612); // ~#8A929C
const vec3 ORANGE    = vec3(0.949, 0.529, 0.118); // #F2871E (brand-500)
const vec3 ORANGE_HI = vec3(0.969, 0.635, 0.247); // #F7A23F (brand-400)

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 345.45));
  p += dot(p, p + 34.345);
  return fract(p.x * p.y);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(i + vec2(0.0, 0.0));
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// FBM: exactly 4 octaves (brief max).
float fbm(vec2 p) {
  float v = 0.0;
  float amp = 0.5;
  mat2 rot = mat2(0.80, -0.60, 0.60, 0.80);
  for (int i = 0; i < 4; i++) {
    v += amp * vnoise(p);
    p = rot * p * 2.0;
    amp *= 0.5;
  }
  return v;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5 * u_res) / u_res.y; // aspect-correct, centered
  float t = u_time;

  vec2 p = uv * 2.6; // very low frequency = large, calm landforms

  // Domain warp, advected in time => the terrain MORPHS (flows), not translates.
  vec2 q = vec2(
    fbm(p + vec2(0.0, 0.0) + t * 0.06),
    fbm(p + vec2(5.2, 1.3) - t * 0.05)
  );
  float height = fbm(p + 1.6 * q + t * 0.012);

  // ---- ISO-LINES (contours) ----
  float bandPhase = t * 0.05;       // bands advance => rings flow outward
  float dens = 7.0;                 // DENS: contour density (raise spacing if busy)
  float h = height * dens - bandPhase;
  float fr = fract(h);
  float dline = min(fr, 1.0 - fr);  // distance to nearest band edge
  float aa = fwidth(h) * 1.2;       // screen-space AA (constant device-px width)
  float line = 1.0 - smoothstep(0.0, aa, dline);

  // ---- ACCENT MASK (sparse orange: contour AND independent low-freq high) ----
  float accentField = fbm(uv * 1.1 + vec2(13.0, 7.0) - t * 0.03);
  float accent = smoothstep(0.62, 0.74, accentField); // accent gate
  accent *= u_accent;                                  // off entirely for ambient

  // ---- compose ----
  vec3 base = mix(BG, BG_TOP, smoothstep(-0.45, 0.55, uv.y));
  float ridge = smoothstep(0.45, 0.85, height);
  vec3 steelCol  = mix(STEEL * 0.72, STEEL, ridge);
  vec3 orangeCol = mix(ORANGE, ORANGE_HI, ridge);
  vec3 lineCol   = mix(steelCol, orangeCol, accent);

  float strength = mix(0.34, 0.62, accent); // steel subtle, accent a touch stronger
  vec3 col = base + lineCol * line * strength;
  col += ORANGE_HI * line * accent * 0.18;  // faint glow exactly on accent lines

  // ---- RADIAL VIGNETTE (gated: hero frames the card, ambient stays flat) ----
  float r = length(uv * vec2(1.0, 1.3));
  float centerDim = 1.0 - 0.40 * smoothstep(0.0, 0.55, 0.55 - r); // dim middle
  float edgeDim   = 1.0 - 0.55 * smoothstep(0.75, 1.6, r);        // dim corners
  float vig = mix(1.0, centerDim * edgeDim, u_vignette);
  col = mix(BG, col, vig);

  gl_FragColor = vec4(col, 1.0);
}
`

function compile(gl: WebGLRenderingContext, type: number, src: string) {
  const sh = gl.createShader(type)
  if (!sh) return null
  gl.shaderSource(sh, src)
  gl.compileShader(sh)
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    gl.deleteShader(sh)
    return null
  }
  return sh
}

export function ContourBackground({
  variant = 'hero',
}: {
  variant?: ContourVariant
} = {}) {
  const cfg = VARIANTS[variant]
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const uid = useId().replace(/:/g, '') // safe, unique gradient/filter ids
  // Resolve reduced-motion once, synchronously, so the SVG traces render parked.
  const [reduced] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const FRAME_MS = 1000 / cfg.fps

    const gl =
      (canvas.getContext('webgl', {
        antialias: false,
        depth: false,
        stencil: false,
        alpha: false,
        powerPreference: 'low-power',
        preserveDrawingBuffer: false,
      }) as WebGLRenderingContext | null) ||
      (canvas.getContext('experimental-webgl') as WebGLRenderingContext | null)

    // No WebGL -> the premium CSS .contour-fallback underneath shows through.
    if (!gl) {
      canvas.style.display = 'none'
      return
    }
    // fwidth() needs the derivatives extension on WebGL1.
    if (!gl.getExtension('OES_standard_derivatives')) {
      canvas.style.display = 'none'
      return
    }

    const program = gl.createProgram()
    const vs = compile(gl, gl.VERTEX_SHADER, VERT)
    const fs = compile(
      gl,
      gl.FRAGMENT_SHADER,
      '#extension GL_OES_standard_derivatives : enable\n' + FRAG,
    )
    if (!program || !vs || !fs) {
      canvas.style.display = 'none'
      return
    }
    gl.attachShader(program, vs)
    gl.attachShader(program, fs)
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      canvas.style.display = 'none'
      return
    }
    gl.useProgram(program)

    // fullscreen triangle (covers the quad with one fewer vertex, no seam)
    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW,
    )
    const aPos = gl.getAttribLocation(program, 'a_pos')
    gl.enableVertexAttribArray(aPos)
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0)

    const uRes = gl.getUniformLocation(program, 'u_res')
    const uTime = gl.getUniformLocation(program, 'u_time')
    // Per-variant constants — set once; they persist on the program.
    gl.uniform1f(gl.getUniformLocation(program, 'u_vignette'), cfg.vignette)
    gl.uniform1f(gl.getUniformLocation(program, 'u_accent'), cfg.accent)

    let backingW = 0
    let backingH = 0
    function resize() {
      const cssW = canvas!.clientWidth || window.innerWidth
      const cssH = canvas!.clientHeight || window.innerHeight
      let w = Math.max(2, Math.round(cssW * cfg.resScale))
      let h = Math.max(2, Math.round(cssH * cfg.resScale))
      if (w > cfg.maxBackingW) {
        const k = cfg.maxBackingW / w
        w = cfg.maxBackingW
        h = Math.max(2, Math.round(h * k))
      }
      if (w === backingW && h === backingH) return
      backingW = w
      backingH = h
      canvas!.width = w
      canvas!.height = h
      gl!.viewport(0, 0, w, h)
    }
    resize()

    function draw(timeUnits: number) {
      gl!.uniform2f(uRes, backingW, backingH)
      gl!.uniform1f(uTime, timeUnits)
      gl!.drawArrays(gl!.TRIANGLES, 0, 3)
    }

    // Reduced motion: paint exactly one settled frame, no loop.
    if (reduced) {
      draw(120.0)
      const onResizeStatic = () => {
        resize()
        draw(120.0)
      }
      window.addEventListener('resize', onResizeStatic)
      return () => {
        window.removeEventListener('resize', onResizeStatic)
      }
    }

    let raf = 0
    let running = true
    let last = performance.now()
    let lastDraw = 0
    let acc = 0 // accumulated time units (pause/resume never jumps)

    function loop(now: number) {
      if (!running) return
      raf = requestAnimationFrame(loop)
      if (now - lastDraw < FRAME_MS) return // fps gate
      // Capture elapsed AFTER the gate so skipped frames don't lose time
      // (keeps the morph at its true speed; resume never time-jumps).
      const dt = now - last
      last = now
      lastDraw = now
      acc += (dt / 1000) * cfg.timeScale // fps-independent speed
      draw(acc)
    }
    function start() {
      if (running && raf) return
      running = true
      last = performance.now()
      lastDraw = 0
      raf = requestAnimationFrame(loop)
    }
    function stop() {
      running = false
      if (raf) cancelAnimationFrame(raf)
      raf = 0
    }
    function onVisibility() {
      if (document.hidden) stop()
      else start()
    }
    function onResize() {
      resize()
    }

    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('resize', onResize)
    start()

    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', onResize)
    }
  }, [reduced, cfg])

  return (
    <div className={cfg.rootClass} aria-hidden>
      {/* Premium layered static fallback — painted FIRST; the canvas covers it
          when WebGL works, and it shows through on any WebGL failure. */}
      <div className="contour-fallback" />

      {/* Morphing topographic shader. */}
      <canvas ref={canvasRef} className="contour-canvas" />

      {/* Hero only: two sparse solar-orange field-lines with a slow sensor-sweep
          trace. pathLength=100 normalises dash speed across browsers; gradient
          endstops at 0 opacity make each trace fade in/out (never a solid line).
          Parked at a lit segment under reduced-motion (handled in CSS). */}
      {cfg.sweeps && (
        <svg
          className={`contour-lines${reduced ? ' is-static' : ''}`}
          viewBox="0 0 1440 900"
          preserveAspectRatio="xMidYMid slice"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
        >
          <defs>
            <linearGradient id={`cg-${uid}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#D9740F" stopOpacity="0" />
              <stop offset="0.5" stopColor="#F2871E" stopOpacity="1" />
              <stop offset="1" stopColor="#F7A23F" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            className="contour-line contour-line--1"
            pathLength={100}
            stroke={`url(#cg-${uid})`}
            d="M-40,300 C220,250 360,470 620,430 C880,390 1010,180 1260,250 C1400,290 1460,360 1520,350"
          />
          <path
            className="contour-line contour-line--2"
            pathLength={100}
            stroke={`url(#cg-${uid})`}
            d="M-40,640 C260,690 420,540 700,600 C940,650 1080,790 1340,720 C1430,696 1480,672 1520,690"
          />
        </svg>
      )}
    </div>
  )
}
