// Starry night background: a few hundred stars on a canvas, with a slow twinkle.
// Static when the viewer prefers reduced motion.

export function startStars(canvas) {
  if (!canvas?.getContext) return;
  const ctx = canvas.getContext("2d");
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let stars = [];
  let w = 0, h = 0, dpr = 1;

  function seed() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.round((w * h) / 2600);
    stars = Array.from({ length: count }, () => {
      const big = Math.random() < 0.06;
      return {
        x: Math.random() * w,
        y: Math.random() * h,
        r: big ? 1.1 + Math.random() * 0.8 : 0.35 + Math.random() * 0.7,
        a: 0.25 + Math.random() * 0.6,
        s: 0.4 + Math.random() * 1.4,
        p: Math.random() * Math.PI * 2,
        warm: Math.random() < 0.12,
      };
    });
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    for (const s of stars) {
      const tw = still ? 1 : 0.65 + 0.35 * Math.sin(t / 1000 * s.s + s.p);
      ctx.globalAlpha = s.a * tw;
      ctx.fillStyle = s.warm ? "#f3c9b5" : "#faf9f5";
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    if (!still) requestAnimationFrame(draw);
  }

  seed();
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => { seed(); if (still) draw(0); }, 150); });
  if (still) draw(0); else requestAnimationFrame(draw);
}
