// Panel registry. Order here is the order on the page (phone: top to bottom).
// Each worker owns the module file named here, inside its own folder.
// span: "full" = full width on tablet and up, "2" = two of three columns on desktop.

export const PANELS = [
  { id: "radar",   title: "Story Radar",       worker: 3, module: "../radar/radar-panel.js",     span: "full", hero: true },
  { id: "x",       title: "X Breaking",        worker: 2, module: "../x/x-panel.js" },
  { id: "youtube", title: "On YouTube",        worker: 4, module: "../youtube/coverage-panel.js" },
  { id: "ideas",   title: "Video Ideas",       worker: 3, module: "../radar/ideas-panel.js" },
  { id: "dev",     title: "Claude Dev Corner", worker: 5, module: "../ops/devcorner-panel.js" },
  { id: "stats",   title: "My Stats",          worker: 4, module: "../youtube/stats-panel.js" },
  { id: "runlog",  title: "Run Log",           worker: 5, module: "../ops/runlog-panel.js",      span: "2" },
];

// Every data file the page loads (data/<name>.json). Matches shell/schema/.
export const DATA_FILES = ["meta", "x", "stories", "youtube", "radar", "ideas", "stats", "devcorner", "runlog"];
