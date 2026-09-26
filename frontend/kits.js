/* kits.js — shared shirt rendering used by lineup, optimize, rate-squad, transfers */
(function () {

  const TEAM_COLOURS = {
    ARS: ['#EF0107', '#9E000A'],
    AVL: ['#670E36', '#3D081E'],
    BOU: ['#DA291C', '#891100'],
    BRE: ['#E30613', '#8B0000'],
    BHA: ['#0057B8', '#003D82'],
    CHE: ['#034694', '#012240'],
    COV: ['#59CBE8', '#005B80'],
    CRY: ['#C4122E', '#8A0D1F'],
    EVE: ['#003399', '#002266'],
    FUL: ['#E0E0E0', '#1A1A1A'],
    HUL: ['#F5A623', '#A35500'],
    IPS: ['#0044A9', '#002D72'],
    LEE: ['#EEEEEE', '#1D428A'],
    LIV: ['#C8102E', '#8B0A1E'],
    MCI: ['#6CABDD', '#1C2C5B'],
    MUN: ['#DA291C', '#8B0000'],
    NEW: ['#1C1C1C', '#000000'],
    NFO: ['#DD0000', '#8B0000'],
    SUN: ['#EB172B', '#8B0A20'],
    TOT: ['#EEEEEE', '#132257'],
  };

  // All GKPs wear black regardless of club
  const GKP_COLOURS = ['#1a1a1a', '#000000'];

  const POS_FALLBACK = {
    DEF: ['#3b82f6', '#1e40af'],
    MID: ['#22c55e', '#15803d'],
    FWD: ['#ef4444', '#b91c1c'],
  };

  function isLight(hex) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return 0.299 * r + 0.587 * g + 0.114 * b > 155;
  }

  function teamColours(player) {
    if (player.position === 'GKP') return GKP_COLOURS;
    return TEAM_COLOURS[player.team_short_name]
      || POS_FALLBACK[player.position]
      || ['#64748b', '#334155'];
  }

  function abbr(name) {
    const parts = name.trim().split(/\s+/);
    return (parts[parts.length - 1] || parts[0]).substring(0, 4).toUpperCase();
  }

  function shirtSvg(fill, stroke, label) {
    const textFill    = isLight(fill) ? '#1a1a1a' : '#ffffff';
    const collarColour = isLight(fill) ? stroke : 'white';
    return `<svg viewBox="0 0 40 44" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M13,3 C16,9 24,9 27,3 L35,7 L40,17 L34,21 L34,44 L6,44 L6,21 L0,17 L5,7 Z" fill="${fill}"/>
      <path d="M13,3 C16,9 24,9 27,3 L35,7 L40,17 L34,21 L34,44 L6,44 L6,21 L0,17 L5,7 Z"
            fill="none" stroke="${stroke}" stroke-width="1.25" opacity="0.55"/>
      <path d="M14,4 C17,9 23,9 26,4" fill="none" stroke="${collarColour}" stroke-width="1.25" opacity="0.5"/>
      <line x1="6" y1="29" x2="34" y2="29" stroke="${stroke}" stroke-width="0.75" opacity="0.2"/>
      <text x="20" y="39" text-anchor="middle"
            font-size="7.5" font-weight="700" fill="${textFill}" opacity="0.92"
            font-family="Inter,system-ui,sans-serif">${label}</text>
    </svg>`;
  }

  // Distribute n players evenly across a pitch row; margins tighten for fewer players
  const MARGINS = { 1: 50, 2: 28, 3: 22, 4: 15, 5: 10 };
  function spreadX(count, i) {
    if (count === 1) return 50;
    const m = MARGINS[count] ?? 10;
    return m + (i / (count - 1)) * (100 - 2 * m);
  }

  // The pitch SVG lines (200×300 viewBox) — same on every pitch page
  const PITCH_SVG = `<svg class="pitch-lines" viewBox="0 0 200 300" fill="none" aria-hidden="true">
    <line x1="0" y1="150" x2="200" y2="150" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <circle cx="100" cy="150" r="28"  stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <circle cx="100" cy="150" r="2"   fill="rgba(255,255,255,.45)"/>
    <rect x="41"  y="0"   width="118" height="47" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <rect x="72"  y="0"   width="56"  height="18" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <circle cx="100" cy="32"  r="2"   fill="rgba(255,255,255,.45)"/>
    <path d="M80,47 A20,20 0 0,0 120,47"   stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <rect x="41"  y="253" width="118" height="47" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <rect x="72"  y="282" width="56"  height="18" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <circle cx="100" cy="268" r="2"   fill="rgba(255,255,255,.45)"/>
    <path d="M80,253 A20,20 0 0,1 120,253" stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <path d="M4,0 A4,4 0 0,0 0,4"          stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <path d="M196,0 A4,4 0 0,1 200,4"      stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <path d="M200,296 A4,4 0 0,1 196,300"  stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
    <path d="M0,296 A4,4 0 0,0 4,300"      stroke="rgba(255,255,255,.28)" stroke-width="1.5"/>
  </svg>`;

  window.FPLKits = { teamColours, abbr, shirtSvg, spreadX, PITCH_SVG, isLight, TEAM_COLOURS };
})();
