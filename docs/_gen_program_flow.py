"""One-shot: write docs/config-scanner-program-flow.html from SETTING_SPECS."""

from __future__ import annotations

from html import escape
from pathlib import Path

from config_scanner.setting_spec import SETTING_GROUPS, SETTING_SPECS

OUT = Path(__file__).resolve().parent / "config-scanner-program-flow.html"

# Settings Slot Setup / wizard recipe can actually patch (not merely probe).
WRITE_IDS = frozenset(
    {
        "sas.address",
        "sas.aft_enabled",
        "sas.aft_in_house",
        "sas.funds_transfer_type",
        "sas.lock_when_no_comms",
        "bill.protocol",
        "bill.tokens",
        "ticket.offline_enabled",
        "locale.target_market",
        "locale.culture_name",
        "locale.language",
        "locale.currency_name",
        "locale.currency_format",
        "locale.currency_short_symbol",
        "locale.hw_currency_name",
        "locale.jur_tag",
        "locale.jur_currency_symbol",
        "locale.jur_magic_wheel_limit",
        "id.machine_id",
        "id.network_hostname",
        "id.aurum_service_uri",
        "ui.inactivity_to_selector",
        "denom.list",
        "denom.credit_rate_values",
        "math.denomination_multiplier",
        "math.fixed_bet",
        "math.bet_multipliers",
        "math.denom_return_percent",
        "dallas.key_codes",
        "buttons.keyboard_map",
    }
)

FILE_LABEL = {
    "slot/themes/mgconfig.xml": "mgconfig.xml",
    "slot/themes/HardwareConfig.xml": "HardwareConfig.xml",
    "slot/themes/*/MathSettings.xml": "MathSettings.xml (per game)",
    "Services/aurum/config/SASControler1/SASsetupData.xml": "SASsetupData.xml",
    "Services/aurum/config/SASControler1/ClientsSet.xml": "ClientsSet.xml",
    "Services/aurum/config/AurumSetup.xml": "AurumSetup.xml",
    "bios/etc/application/slot/oticket.xml": "oticket.xml",
    "maintenance/config/configure-aurum.conf": "configure-aurum.conf",
    "slot/hwdrivers/QuixantHardware.xml": "QuixantHardware.xml",
    "bios/etc/application/system/soundvolume.xml": "soundvolume.xml",
    "Services/aurum/AurumServicesConfig.xml": "AurumServicesConfig.xml",
    "slot/themes/jurisdiction_config.xml": "jurisdiction_config.xml",
    "slot/hwdrivers/Keyboard.xml": "Keyboard.xml",
}


def _file_short(rel: str) -> str:
    return FILE_LABEL.get(rel.replace("\\", "/"), rel)


def settings_tables() -> str:
    chunks: list[str] = []
    by_group: dict[str, list] = {g: [] for g in SETTING_GROUPS}
    for spec in SETTING_SPECS:
        by_group.setdefault(spec.group, []).append(spec)
    n = 0
    for group in SETTING_GROUPS:
        specs = by_group.get(group) or []
        if not specs:
            continue
        n += len(specs)
        gid = escape(group.lower().replace(" ", "-"))
        chunks.append(f'<h3 id="g-{gid}">{escape(group)} <span class="count">{len(specs)}</span></h3>')
        chunks.append("<table class='catalog'><thead><tr>")
        chunks.append(
            "<th>Setting</th><th>Id</th><th>File</th><th>In CS pack</th><th>Role</th></tr></thead><tbody>"
        )
        for spec in specs:
            written = spec.id in WRITE_IDS
            role = "Compared and can be written" if written else "Compared only"
            role_cls = "write" if written else "probe"
            pack = "Usually shipped" if spec.cs_pack_delivers else "Only if that pack has the file"
            note = f'<div class="note">{escape(spec.notes)}</div>' if spec.notes else ""
            chunks.append(
                "<tr class='{role}' data-role='{role}' data-q='{q}'>"
                "<td><strong>{label}</strong>{note}</td>"
                "<td><code>{sid}</code></td>"
                "<td>{fil}</td>"
                "<td>{pack}</td>"
                "<td><span class='badge {role}'>{role_txt}</span></td>"
                "</tr>".format(
                    role=role_cls,
                    q=escape(
                        f"{spec.label} {spec.id} {spec.file_rel} {spec.group}".lower(),
                        quote=True,
                    ),
                    label=escape(spec.label),
                    note=note,
                    sid=escape(spec.id),
                    fil=escape(_file_short(spec.file_rel)),
                    pack=escape(pack),
                    role_txt=escape(role),
                )
            )
        chunks.append("</tbody></table>")
    assert n == len(SETTING_SPECS)
    return "\n".join(chunks)


def toc_groups() -> str:
    bits = []
    for group in SETTING_GROUPS:
        count = sum(1 for s in SETTING_SPECS if s.group == group)
        gid = escape(group.lower().replace(" ", "-"))
        bits.append(
            f'<a href="#g-{gid}">{escape(group)} <span>{count}</span></a>'
        )
    return "\n".join(bits)


def main() -> None:
    write_n = sum(1 for s in SETTING_SPECS if s.id in WRITE_IDS)
    probe_n = len(SETTING_SPECS) - write_n
    optional_n = sum(1 for s in SETTING_SPECS if not s.cs_pack_delivers)
    html = TEMPLATE.format(
        n_specs=len(SETTING_SPECS),
        n_write=write_n,
        n_probe=probe_n,
        n_optional=optional_n,
        n_groups=len(SETTING_GROUPS),
        toc_groups=toc_groups(),
        catalog=settings_tables(),
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Config Scanner — program flow and settings</title>
<style>
:root {{
  --ink: #1c2430;
  --muted: #5b6675;
  --line: #d8deea;
  --paper: #f7f5f0;
  --card: #ffffff;
  --gold: #b8892a;
  --gold-soft: #f4ead4;
  --green: #1f7a4d;
  --green-bg: #e6f5ec;
  --amber: #9a6b00;
  --amber-bg: #fff4d6;
  --red: #b42318;
  --red-bg: #fdecea;
  --gray: #667085;
  --gray-bg: #eef0f4;
  --navy: #16324f;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  font: 16px/1.5 "Segoe UI", Calibri, system-ui, sans-serif;
  color: var(--ink);
  background: var(--paper);
}}
header {{
  background: var(--navy);
  color: #fff;
  padding: 40px 28px 36px;
}}
header .kicker {{
  letter-spacing: .12em;
  text-transform: uppercase;
  font-size: 12px;
  opacity: .75;
  margin: 0 0 8px;
}}
header h1 {{
  font-size: 32px;
  font-weight: 650;
  margin: 0 0 10px;
  letter-spacing: -.02em;
}}
header p {{ margin: 0; max-width: 46rem; color: #d7e0ea; }}
.wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 28px 64px; }}
nav.toc {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: -18px auto 28px;
  max-width: 1100px;
  padding: 0 28px;
}}
nav.toc a {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  color: var(--navy);
  text-decoration: none;
}}
nav.toc a:hover {{ border-color: var(--gold); }}
h2 {{
  font-size: 22px;
  margin: 40px 0 12px;
  color: var(--navy);
}}
h3 {{
  font-size: 17px;
  margin: 28px 0 10px;
  color: var(--navy);
}}
h3 .count {{
  font-weight: 500;
  color: var(--muted);
  font-size: 13px;
}}
p, li {{ color: var(--ink); }}
.lead {{ font-size: 18px; max-width: 46rem; }}
.cards {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin: 20px 0;
}}
.card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 18px 20px;
}}
.card h3 {{ margin-top: 0; }}
.card ol {{ margin: 0; padding-left: 1.2rem; }}
.stats {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin: 20px 0 8px;
}}
.stat {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}}
.stat b {{ display: block; font-size: 28px; color: var(--navy); }}
.stat span {{ font-size: 13px; color: var(--muted); }}
.flow {{
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 8px;
  margin: 20px 0;
}}
.step {{
  flex: 1 1 140px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 14px 12px;
  min-width: 140px;
  position: relative;
}}
.step .n {{
  display: inline-block;
  width: 24px; height: 24px;
  border-radius: 50%;
  background: var(--gold-soft);
  color: var(--navy);
  font-size: 12px;
  font-weight: 700;
  text-align: center;
  line-height: 24px;
  margin-bottom: 8px;
}}
.step strong {{ display: block; margin-bottom: 4px; }}
.step span {{ font-size: 13px; color: var(--muted); }}
.arrow {{
  align-self: center;
  color: var(--gold);
  font-size: 22px;
  flex: 0 0 auto;
}}
.legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin: 12px 0 20px;
}}
.pill {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 13px;
}}
.pill i {{
  width: 10px; height: 10px; border-radius: 50%; display: inline-block;
}}
.ok {{ background: var(--green-bg); color: var(--green); }}
.warn {{ background: var(--amber-bg); color: var(--amber); }}
.bad {{ background: var(--red-bg); color: var(--red); }}
.na {{ background: var(--gray-bg); color: var(--gray); }}
.split {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}}
ul.plain {{ margin: 8px 0 0; padding-left: 1.15rem; }}
.never {{
  background: #fff;
  border-left: 4px solid var(--red);
  padding: 12px 16px;
  border-radius: 0 10px 10px 0;
}}
.toolbar {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin: 16px 0;
  position: sticky;
  top: 0;
  background: var(--paper);
  padding: 10px 0;
  z-index: 2;
}}
.toolbar input {{
  flex: 1 1 240px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font: inherit;
}}
.toolbar button {{
  border: 1px solid var(--line);
  background: var(--card);
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font: inherit;
}}
.toolbar button.active {{ background: var(--navy); color: #fff; border-color: var(--navy); }}
.group-nav {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}}
.group-nav a {{
  font-size: 12px;
  color: var(--navy);
  text-decoration: none;
  background: var(--gold-soft);
  padding: 4px 8px;
  border-radius: 6px;
}}
.group-nav a span {{ color: var(--muted); }}
table.catalog {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  font-size: 14px;
  margin-bottom: 8px;
}}
table.catalog th {{
  text-align: left;
  background: #eef2f7;
  padding: 8px 10px;
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted);
}}
table.catalog td {{
  padding: 8px 10px;
  border-top: 1px solid var(--line);
  vertical-align: top;
}}
table.catalog code {{ font-size: 12px; }}
.note {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
.badge {{
  display: inline-block;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  white-space: nowrap;
}}
.badge.write {{ background: var(--gold-soft); color: #6b4e12; }}
.badge.probe {{ background: var(--gray-bg); color: var(--gray); }}
tr.hidden {{ display: none; }}
footer {{
  margin-top: 48px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
}}
@media (max-width: 800px) {{
  .cards, .split, .stats {{ grid-template-columns: 1fr; }}
  .arrow {{ display: none; }}
}}
@media print {{
  header {{ background: #fff; color: #000; padding: 12px 0; }}
  header p {{ color: #333; }}
  nav.toc, .toolbar {{ display: none; }}
  .step, .card {{ break-inside: avoid; }}
  a {{ color: inherit; text-decoration: none; }}
}}
</style>
</head>
<body>
<header>
  <p class="kicker">GoldClub Config Scanner &middot; internal briefing</p>
  <h1>How country configuration works</h1>
  <p>A lab tool to pick the right GameStar country pack, check every important setting against the target market, and ship a client update. Restore applies that update on the cabinet.</p>
</header>
<nav class="toc wrap" style="margin-left:auto;margin-right:auto;">
  <a href="#jobs">Two jobs</a>
  <a href="#share">Lab share map</a>
  <a href="#flow">Create flow</a>
  <a href="#colors">Traffic lights</a>
  <a href="#layers">Compare vs write</a>
  <a href="#restore">Restore</a>
  <a href="#never">Never touch</a>
  <a href="#catalog">All settings</a>
</nav>
<div class="wrap">

<p class="lead">Official WinSystems country packs live on the lab share
<code>\\\\10.0.0.249\\WinSystems_SLOT</code>
(_B2U, GameStar 2.0.0, GameStar 2.0.1). The program does not invent a country from scratch. It starts from those packs, shows what they actually contain, and flags leftovers (for example Trinidad currency with a Puerto Rico culture tag). Create auto-picks the newest official overlay and hides Debug/Test packs.</p>

<div class="stats">
  <div class="stat"><b>{n_specs}</b><span>settings the program can read</span></div>
  <div class="stat"><b>{n_write}</b><span>settings it can also write</span></div>
  <div class="stat"><b>{n_probe}</b><span>compare-only (audit)</span></div>
  <div class="stat"><b>{n_optional}</b><span>only present in some packs</span></div>
</div>

<h2 id="jobs">1. Two jobs</h2>
<div class="cards">
  <div class="card">
    <h3>Create (lab)</h3>
    <ol>
      <li>Choose the market (Trinidad TTD, Jamaica JMD, Puerto Rico, Panama, Peru, &hellip;).</li>
      <li>Choose the official Country Selector pack and cabinet variant (denom, 2/3 screens, OL+SAS vs SAS-only).</li>
      <li>Review the traffic-light table against a live EGM if one is connected.</li>
      <li>Export a client <strong>.b2u</strong> update.</li>
    </ol>
  </div>
  <div class="card">
    <h3>Restore (cabinet)</h3>
    <ol>
      <li>Open Config Scanner on the machine.</li>
      <li>Point it at the update that Create produced.</li>
      <li>Pick the matching leaf (country / screens / denom).</li>
      <li>Apply. The overlay writes GoldClub config files, not Windows boot or serial-port maps.</li>
    </ol>
  </div>
</div>
<p>A third path, <strong>More tools</strong>, covers snapshots, companion packs (keyboards, bills, Clovers, offline ticket text, OneHand, TrialReset), and advanced Slot Setup. Country Selectors stay on the Create path.</p>

<h2 id="share">1b. What is on the lab share (and what this program uses)</h2>
<table class="catalog">
<thead><tr><th>Folder</th><th>What it is</th><th>In Config Scanner</th></tr></thead>
<tbody>
<tr><td><code>_B2U\\CS-Gamestar-*</code></td><td>Unpacked Country Selector overlays (Trinidad TRI/TT, Jamaica, Puerto Rico PR-00…06, Panama PANC, Peru PRU Debug)</td><td>Create — authoring</td></tr>
<tr><td><code>_B2U\\encrypted\\CS-Gamestar-PER-00.b2u</code></td><td>Official Peru overlay (do not confuse with Puerto Rico <code>PR-*</code>)</td><td>Create — authoring</td></tr>
<tr><td><code>GameStar 2.0.1\\Country Selectors</code></td><td>Trinidad TRI-01 / TT-00, Jamaica JAM-00/01, Puerto Rico PR-05. Panama folder is empty.</td><td>Create — default newest line</td></tr>
<tr><td><code>GameStar 2.0.0\\Country Selectors</code></td><td>Panama PANC-01, Puerto Rico PR-04</td><td>Create — Panama lives here, not on 2.0.1</td></tr>
<tr><td><code>GameStar+22</code> / <code>GameStar+30</code></td><td>CountrySelector <code>.zip</code> for Colombia, Guyana, Mexico, Panama, Peru, Trinidad</td><td>Listed grey — cabinet Restore only, not Create</td></tr>
<tr><td><code>GameStar 2.0.1\\Updates</code>, <code>_B2U</code> Bills/Keyboards/Dallas/OffLineTicket/MUX</td><td>Companion updates</td><td>More tools → companions</td></tr>
<tr><td><code>Keyboard Updates</code>, <code>_BILLS</code></td><td>Cabinet keyboard layouts; JCM vs MEI bill software</td><td>Companions / hardware, not CS</td></tr>
<tr><td><code>JinLong</code></td><td>Different product (<code>.ws</code> CountrySelector packages, jackpot controllers, <code>.mrimg</code>)</td><td>Out of scope</td></tr>
<tr><td><code>Poland</code>, <code>Netherlands</code>, Adventure / Colors / Fenghuang / L2W / …</td><td>Other brands, mechanical-counter zips, disk images, logs</td><td>Out of scope (Poland mechanical counters are a Hardware setting if a CS leaf has them)</td></tr>
<tr><td><code>*.mrimg</code>, loggers, WIBU xls, licences of another EGM</td><td>Images / secrets</td><td>Never treat as settings</td></tr>
</tbody>
</table>
<p>GameStar 3.0.0 on the share is empty. Gamestar+36 is a demo image, not a CS overlay tree.</p>

<h2 id="flow">2. Create flow</h2>
<p>Jurisdiction wizard — four steps the operator walks in order.</p>
<div class="flow">
  <div class="step"><div class="n">1</div><strong>Jurisdiction</strong><span>Load the market preset: currency, culture, recommended denoms, SAS / ticket expectations.</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">2</div><strong>Pack &amp; leaf</strong><span>Newest official overlay is pre-selected (2.0.1, then 2.0.0, then _B2U). Debug/Test hidden. Then the cabinet variant inside it.</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">3</div><strong>Review</strong><span>Every setting below is probed on the pack (and live EGM). Green / amber / red / gray.</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">4</div><strong>Export</strong><span>Encrypted Country Selector .b2u for the client. Optional recipe.json for Slot Setup.</span></div>
</div>

<div class="card">
  <h3>What “export” actually ships</h3>
  <p>The client update is the <strong>official country overlay</strong> (the leaf you picked), packed as a GameStar-style B2U. The traffic-light table does not rewrite all {n_specs} fields into that pack. If a recipe is included, Slot Setup can patch a smaller, safer set on top (currency, denoms, SAS address / AFT / lock, Dallas key, keyboard, offline ticket flag).</p>
</div>

<h2 id="colors">3. How a setting is judged</h2>
<div class="legend">
  <span class="pill ok"><i style="background:#1f7a4d"></i> Green — present and matches the market preset</span>
  <span class="pill warn"><i style="background:#9a6b00"></i> Amber — present, different value (leftover or mismatch)</span>
  <span class="pill bad"><i style="background:#b42318"></i> Red — expected, but missing on this tree</span>
  <span class="pill na"><i style="background:#667085"></i> Gray — this pack does not ship that file (or no opinion)</span>
</div>
<p>Extra consistency checks catch known pack leftovers even when a field is “present”: Trinidad TTD with CultureName <code>es-PR</code> / TargetMarket PuertoRico, Aurum processor locale <code>sl_SI</code> on every country, and jurisdiction_config Tag vs mgconfig TargetMarket.</p>

<h2 id="layers">4. Compare vs write</h2>
<div class="split">
  <div class="card">
    <h3>Read / compare ({n_specs})</h3>
    <p>Used in the review table so lab and field see the full picture: SAS chirping, Tubo service on/off, ticket layouts, UPS, processor locale, and so on.</p>
    <p>Some files exist only in later packs (Keyboard.xml, ClientsSet.xml, jurisdiction_config.xml). Those show gray on TRI-00 OL+SAS and light up when the chosen pack actually contains them.</p>
  </div>
  <div class="card">
    <h3>Write ({n_write})</h3>
    <p>Slot Setup and the optional export recipe only change settings we have a safe patcher for. Gold badges in the catalog below mark that set.</p>
    <ul class="plain">
      <li>Market, culture, currency, language, denoms</li>
      <li>SAS address, AFT, funds-transfer type, lock-when-no-comms</li>
      <li>Bill tokens and MEI/JCM protocol</li>
      <li>Offline ticket flag; copy of oticket.xml</li>
      <li>One Dallas key; keyboard map; MachineID / Aurum hostname</li>
      <li>Per-game bet multipliers / RTP when authored</li>
    </ul>
  </div>
</div>

<h2 id="restore">5. Restore on the cabinet</h2>
<div class="flow">
  <div class="step"><div class="n">1</div><strong>Detect pack</strong><span>Country, EGM setup, or companion update beside the exe or chosen folder.</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">2</div><strong>Choose leaf</strong><span>Same country / screens / denom the lab exported.</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">3</div><strong>Apply overlay</strong><span>Copies allowed GoldClub files onto C:\\Goldclub (or the live share).</span></div>
  <div class="arrow">&#8594;</div>
  <div class="step"><div class="n">4</div><strong>Done</strong><span>Game config is updated. Windows boot, BitLocker, and COM maps are left alone.</span></div>
</div>

<h2>6. Companion packs (optional extras)</h2>
<p>Not Country Selectors. Same lab share, used when a site needs a smaller overlay:</p>
<ul class="plain">
  <li>Keyboards — cabinet button layouts</li>
  <li>Bills / TTD — note acceptor mapping</li>
  <li>Dallas — OneHandConfigurer</li>
  <li>Theme overlay — Clovers disable, Tutankhamen config</li>
  <li>Offline ticket — oticket.xml text</li>
  <li>OneHand binary update</li>
  <li>Licences — explicit confirm only, never copied from another EGM by default</li>
  <li>Serial / MUX — G: drive only, extra confirmation (dangerous)</li>
</ul>

<h2 id="never">7. What this program never changes</h2>
<div class="never">
  <ul class="plain">
    <li>Windows boot (BCD, EFI, Shell Launcher, hives)</li>
    <li>Serial-port board maps (<code>layout.json</code> / <code>locations.json</code>)</li>
    <li>Another machine’s licence XML or <code>licence.dll</code></li>
    <li>mgconfig artwork / font / layout chrome</li>
  </ul>
</div>

<h2 id="catalog">8. Full settings catalog ({n_specs})</h2>
<p>Everything the review table can show, grouped the same way as in the program. Use search or the gold / gray filter. Generated from the live registry ({n_groups} groups).</p>

<div class="toolbar">
  <input id="q" type="search" placeholder="Filter by name, id, or file…" oninput="filterRows()">
  <button type="button" id="f-all" class="active" onclick="setFilter('all')">All</button>
  <button type="button" id="f-write" onclick="setFilter('write')">Can be written</button>
  <button type="button" id="f-probe" onclick="setFilter('probe')">Compare only</button>
</div>
<div class="group-nav">{toc_groups}</div>
{catalog}

<footer>
  Config Scanner internal briefing. Counts and labels are taken from
  <code>config_scanner/setting_spec.py</code>. Open this file in a browser; no network required.
</footer>
</div>
<script>
let FILTER = "all";
function setFilter(mode) {{
  FILTER = mode;
  document.getElementById("f-all").classList.toggle("active", mode === "all");
  document.getElementById("f-write").classList.toggle("active", mode === "write");
  document.getElementById("f-probe").classList.toggle("active", mode === "probe");
  filterRows();
}}
function filterRows() {{
  const q = (document.getElementById("q").value || "").toLowerCase().trim();
  document.querySelectorAll("table.catalog tbody tr").forEach((tr) => {{
    const role = tr.getAttribute("data-role");
    const hay = tr.getAttribute("data-q") || "";
    const okRole = FILTER === "all" || role === FILTER;
    const okQ = !q || hay.indexOf(q) !== -1;
    tr.classList.toggle("hidden", !(okRole && okQ));
  }});
}}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
