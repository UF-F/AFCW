"""
AFC Wimbledon U16 - Match Dashboard
Run with:  streamlit run app.py
"""

import base64
import html
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import charts

# ============================================================
# SETTINGS - change these once
# ============================================================
CLUB = "AFC Wimbledon"
TEAM_SHORT = "AFCW"          # used in chart legends
TEAM_NAME = "Wimbledon"      # used on the infographics
AGE_GROUP_DEFAULT = "U16"
CREDIT = "@Neil_barretto"

DATA_DIR = Path("data")
XML_DIR = DATA_DIR / "xml"
DB_PATH = DATA_DIR / "games.json"
ASSETS_DIR = Path("assets")
OPP_LOGO_DIR = ASSETS_DIR / "opponents"
XML_DIR.mkdir(parents=True, exist_ok=True)
OPP_LOGO_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title=f"{CLUB} Match Dashboard", page_icon="⚽", layout="wide")

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2rem; }}
      h1, h2, h3 {{ color: {charts.NAVY}; }}
      [data-testid="stSidebar"] {{ background: {charts.NAVY}; }}
      [data-testid="stSidebar"] * {{ color: white !important; }}
      [data-testid="stMetricValue"] {{ color: {charts.NAVY}; }}

      /* ---- scoreboard ---- */
      .scoreboard {{ display:flex; align-items:center; justify-content:center; gap:2.5rem;
                     background:linear-gradient(135deg,{charts.NAVY} 0%,#143059 100%);
                     border-radius:18px; padding:1.6rem 1rem; margin:0.5rem 0 0.4rem 0; }}
      .sb-team {{ display:flex; flex-direction:column; align-items:center; gap:.6rem; width:220px; text-align:center; }}
      .sb-name {{ color:white; font-weight:700; font-size:1.1rem; line-height:1.2; }}
      .sb-score {{ display:flex; align-items:center; gap:1rem; color:{charts.GOLD};
                   font-size:4rem; font-weight:800; letter-spacing:.05em; }}
      .sb-dash {{ color:white; opacity:.5; font-weight:400; }}
      .crest {{ width:84px; height:84px; object-fit:contain; }}
      .crest-fallback {{ display:flex; align-items:center; justify-content:center; border-radius:50%;
                         background:rgba(255,255,255,.1); color:white; font-weight:800; font-size:1.4rem; }}
      .sb-meta {{ text-align:center; color:#6B7280; font-size:.9rem; margin-bottom:1rem; }}

      /* ---- stat comparison card ---- */
      .stats-card {{ background:{charts.NAVY}; border-radius:18px; padding:1.2rem 1.6rem 1.4rem 1.6rem; }}
      .stats-head {{ display:flex; justify-content:space-between; font-weight:800; letter-spacing:.08em;
                     font-size:.85rem; margin-bottom:.4rem; }}
      .stats-head .l {{ color:{charts.GOLD}; }}
      .stats-head .r {{ color:{charts.BLUE_GREY}; }}
      .stat-row {{ padding:.55rem 0 .35rem 0; border-bottom:1px solid rgba(255,255,255,.07); }}
      .stat-row:last-child {{ border-bottom:none; }}
      .stat-line {{ display:grid; grid-template-columns:1fr 1.7fr 1fr; align-items:center; }}
      .stat-label {{ text-align:center; color:#CBD5E1; font-weight:600; font-size:.95rem; }}
      .stat-val {{ color:white; font-weight:700; font-size:1rem; }}
      .stat-val.left {{ justify-self:start; }}
      .stat-val.right {{ justify-self:end; }}
      .pill-t {{ background:{charts.GOLD}; color:{charts.NAVY}; border-radius:999px; padding:.15rem .9rem; }}
      .pill-o {{ background:{charts.BLUE_GREY}; color:white; border-radius:999px; padding:.15rem .9rem; }}
      .split {{ display:flex; height:4px; border-radius:4px; overflow:hidden; margin-top:.5rem; gap:3px; }}
      .split-t {{ background:{charts.GOLD}; border-radius:4px; }}
      .split-o {{ background:{charts.BLUE_GREY}; border-radius:4px; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# STORAGE (games.json + one XML file per game)
# ============================================================
def load_games():
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text())
    return []


def save_games(games):
    DB_PATH.write_text(json.dumps(games, indent=2))


def xml_bytes_for(game):
    return (XML_DIR / game["xml_file"]).read_bytes()


def match_ctx(game):
    age = game.get("age_group", AGE_GROUP_DEFAULT)
    return {
        "match_label": f"{CLUB} {age} vs {game['opponent']} {age}",
        "credit": CREDIT,
        "team_short": TEAM_SHORT,
        "team_name": TEAM_NAME,
        "opponent_name": game["opponent"].upper(),
    }


@st.cache_data(show_spinner=False)
def parse_cached(xml_bytes, codes_json):
    return charts.parse_match(xml_bytes, json.loads(codes_json))


@st.cache_data(show_spinner="Rendering charts...")
def render_cached(xml_bytes, codes_json, ctx_json):
    m = parse_cached(xml_bytes, codes_json)
    return charts.render_all(m, json.loads(ctx_json))


def parsed(game):
    return parse_cached(xml_bytes_for(game), json.dumps(game["codes"], sort_keys=True))


def score_of(m):
    s = charts.summarize(m)
    return s["team"]["Goals"], s["opp"]["Goals"]


def game_label(game):
    gf, ga = score_of(parsed(game))
    return f"{game['date']}  |  vs {game['opponent']}  ({gf}-{ga})"


# ============================================================
# LOGOS + HTML COMPONENTS
# ============================================================
def b64_uri(path):
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".svg": "image/svg+xml"}.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def club_logo_uri():
    """Looks for assets/logo.png (or .jpg/.jpeg/.webp/.svg)."""
    for ext in ("png", "jpg", "jpeg", "webp", "svg"):
        p = ASSETS_DIR / f"logo.{ext}"
        if p.exists():
            return b64_uri(p)
    return None


def opp_logo_uri(game):
    f = game.get("opp_logo")
    if f and (OPP_LOGO_DIR / f).exists():
        return b64_uri(OPP_LOGO_DIR / f)
    return None


def crest_html(uri, fallback_text):
    if uri:
        return f'<img class="crest" src="{uri}">'
    return f'<div class="crest crest-fallback">{html.escape(fallback_text[:3].upper())}</div>'


def scoreboard_html(game, gf, ga):
    age = game.get("age_group", AGE_GROUP_DEFAULT)
    return (
        '<div class="scoreboard">'
        f'<div class="sb-team">{crest_html(club_logo_uri(), TEAM_SHORT)}<div class="sb-name">{html.escape(CLUB)} {html.escape(age)}</div></div>'
        f'<div class="sb-score"><span>{gf}</span><span class="sb-dash">-</span><span>{ga}</span></div>'
        f'<div class="sb-team">{crest_html(opp_logo_uri(game), game["opponent"])}<div class="sb-name">{html.escape(game["opponent"])}</div></div>'
        '</div>'
    )


def stats_card_html(game, summ):
    t, o = summ["team"], summ["opp"]

    def acc(s):
        return round(100 * s["Shots on target"] / s["Total shots"]) if s["Total shots"] else 0

    rows = [
        ("Goals", t["Goals"], o["Goals"], str(t["Goals"]), str(o["Goals"])),
        ("Total shots", t["Total shots"], o["Total shots"], str(t["Total shots"]), str(o["Total shots"])),
        ("Shots on target", t["Shots on target"], o["Shots on target"], str(t["Shots on target"]), str(o["Shots on target"])),
        ("Shots off target", t["Shots off target"], o["Shots off target"], str(t["Shots off target"]), str(o["Shots off target"])),
        ("Shots blocked", t["Shots blocked"], o["Shots blocked"], str(t["Shots blocked"]), str(o["Shots blocked"])),
        ("Shot accuracy", acc(t), acc(o), f"{acc(t)}%", f"{acc(o)}%"),
        ("Penalty box entries", t["Penalty box entries"], o["Penalty box entries"], str(t["Penalty box entries"]), str(o["Penalty box entries"])),
        ("Final third entries", t["Final third entries"], o["Final third entries"], str(t["Final third entries"]), str(o["Final third entries"])),
    ]
    out = [f'<div class="stats-card"><div class="stats-head"><span class="l">{TEAM_SHORT}</span>'
           f'<span class="r">{html.escape(game["opponent"]).upper()}</span></div>']
    for label, tv, ov, td, od in rows:
        lcls = "stat-val left" + (" pill-t" if tv > ov else "")
        rcls = "stat-val right" + (" pill-o" if ov > tv else "")
        total = tv + ov
        pct = 100 * tv / total if total else 50
        out.append(
            '<div class="stat-row"><div class="stat-line">'
            f'<span class="{lcls}">{td}</span><span class="stat-label">{label}</span><span class="{rcls}">{od}</span>'
            f'</div><div class="split"><div class="split-t" style="width:{pct:.1f}%"></div>'
            f'<div class="split-o" style="width:{100 - pct:.1f}%"></div></div></div>'
        )
    out.append("</div>")
    return "".join(out)


# ============================================================
# PAGE: MATCH CENTRE
# ============================================================
def page_match_centre():
    games = sorted(load_games(), key=lambda g: g["date"], reverse=True)
    if not games:
        st.info("No games yet - head to **Add Game** to upload your first Sportscode XML.")
        return

    st.title("Match Centre")
    game = st.selectbox("Select game", games, format_func=game_label)
    m = parsed(game)
    summ = charts.summarize(m)
    gf, ga = summ["team"]["Goals"], summ["opp"]["Goals"]
    age = game.get("age_group", AGE_GROUP_DEFAULT)

    st.markdown(scoreboard_html(game, gf, ga), unsafe_allow_html=True)
    bits = [game["date"], game.get("competition"), game.get("venue")]
    st.markdown(f'<div class="sb-meta">{"  •  ".join(html.escape(b) for b in bits if b)}</div>', unsafe_allow_html=True)
    if game.get("notes"):
        st.caption(game["notes"])

    st.markdown(stats_card_html(game, summ), unsafe_allow_html=True)
    with st.expander("Full stats table"):
        st.dataframe(pd.DataFrame({TEAM_SHORT: summ["team"], game["opponent"]: summ["opp"]}), width="stretch")
    st.write("")

    ctx = match_ctx(game)
    pngs = render_cached(xml_bytes_for(game), json.dumps(game["codes"], sort_keys=True), json.dumps(ctx))

    def show(name, key):
        st.image(pngs[name], width="stretch")
        fname = f"{game['date']}_{game['opponent'].replace(' ', '_')}_{name.replace(' ', '_')}.png"
        st.download_button("Download PNG", pngs[name], file_name=fname, mime="image/png", key=key)

    tab_pb, tab_f3, tab_shots, tab_info, tab_goals = st.tabs(
        ["Penalty box entries", "Final third entries", "Shots", "Final third infographics", "Goals & data check"])

    with tab_pb:
        show("Penalty Box Entries", f"dl_pb_{game['id']}")
    with tab_f3:
        show("Final Third Entries", f"dl_f3_{game['id']}")
    with tab_shots:
        show("Shots by Outcome", f"dl_sh_{game['id']}")
    with tab_info:
        c1, c2 = st.columns(2)
        with c1:
            show("Team Final Third Infographic", f"dl_i1_{game['id']}")
        with c2:
            show("Opposition Final Third Infographic", f"dl_i2_{game['id']}")
    with tab_goals:
        st.caption("Minutes are estimated from video time (kick-off + half-time gap) and ignore stoppage time. "
                   "Check them against what you remember.")
        if not m["halftime_found"]:
            st.warning("No half-time gap detected, so second-half minutes may be off.")
        if m["goals"]:
            gdf = pd.DataFrame(m["goals"])
            gdf["side"] = gdf["side"].map({"team": TEAM_SHORT, "opp": game["opponent"]})
            gdf.columns = ["Scored by", "Minute", "15-min bucket"]
            st.dataframe(gdf, width="stretch", hide_index=True)
        else:
            st.write("No goals detected.")
        zt, tt = m["zones"]["team"]
        zo, to = m["zones"]["opp"]
        st.subheader("Final third entries by channel")
        st.dataframe(pd.DataFrame({f"{TEAM_SHORT} ({tt})": zt, f"{game['opponent']} ({to})": zo}),
                     width="stretch")

    with st.expander("Delete this game"):
        if st.checkbox("Yes, delete this game permanently", key=f"del_chk_{game['id']}"):
            if st.button("Delete", type="primary", key=f"del_btn_{game['id']}"):
                (XML_DIR / game["xml_file"]).unlink(missing_ok=True)
                if game.get("opp_logo"):
                    (OPP_LOGO_DIR / game["opp_logo"]).unlink(missing_ok=True)
                save_games([g for g in load_games() if g["id"] != game["id"]])
                st.cache_data.clear()
                st.rerun()


# ============================================================
# PAGE: SEASON OVERVIEW
# ============================================================
def page_season():
    games = sorted(load_games(), key=lambda g: g["date"])
    if not games:
        st.info("No games yet - add one first.")
        return

    st.title("Season Overview")
    chosen = st.multiselect("Games included", games, default=games, format_func=game_label)
    if not chosen:
        st.warning("Select at least one game.")
        return

    rows, matches = [], []
    for g in chosen:
        m = parsed(g)
        matches.append(m)
        s = charts.summarize(m)
        rows.append({
            "Date": g["date"], "Opponent": g["opponent"], "Competition": g.get("competition", ""),
            "GF": s["team"]["Goals"], "GA": s["opp"]["Goals"],
            "Shots": s["team"]["Total shots"], "Shots Agst": s["opp"]["Total shots"],
            "SOT": s["team"]["Shots on target"], "SOT Agst": s["opp"]["Shots on target"],
            "PB Entries": s["team"]["Penalty box entries"], "PB Agst": s["opp"]["Penalty box entries"],
            "F3 Entries": s["team"]["Final third entries"], "F3 Agst": s["opp"]["Final third entries"],
        })
    df = pd.DataFrame(rows)

    w = (df.GF > df.GA).sum()
    d = (df.GF == df.GA).sum()
    l = (df.GF < df.GA).sum()
    c = st.columns(5)
    c[0].metric("Record (W-D-L)", f"{w}-{d}-{l}")
    c[1].metric("Goals for / against", f"{df.GF.sum()} / {df.GA.sum()}")
    c[2].metric("Shots per game", f"{df.Shots.mean():.1f}", delta=f"{df.Shots.mean() - df['Shots Agst'].mean():+.1f} vs opp")
    c[3].metric("PB entries per game", f"{df['PB Entries'].mean():.1f}", delta=f"{df['PB Entries'].mean() - df['PB Agst'].mean():+.1f} vs opp")
    c[4].metric("F3 entries per game", f"{df['F3 Entries'].mean():.1f}", delta=f"{df['F3 Entries'].mean() - df['F3 Agst'].mean():+.1f} vs opp")

    st.dataframe(df, width="stretch", hide_index=True)

    st.subheader("Aggregated 15-minute windows (all selected games)")
    agg = charts.aggregate(matches)
    ctx = {
        "match_label": f"{CLUB} {AGE_GROUP_DEFAULT} - {len(chosen)} games",
        "credit": CREDIT, "team_short": TEAM_SHORT,
        "team_name": TEAM_NAME, "opponent_name": "Opposition",
    }
    which = st.radio("Chart", ["Penalty box entries", "Final third entries", "Shots by outcome"], horizontal=True)
    if which == "Penalty box entries":
        png = charts.fig_to_png(charts.make_bucket_chart(agg, ctx, "pb", "Penalty Box Entries",
                                                         f"{TEAM_SHORT} PB Entries", "Opp PB Entries"))
    elif which == "Final third entries":
        png = charts.fig_to_png(charts.make_bucket_chart(agg, ctx, "f3", "Final Third Entries",
                                                         f"{TEAM_SHORT} F3 Entries", "Opp F3 Entries"))
    else:
        png = charts.fig_to_png(charts.make_shots_chart(agg, ctx))
    st.image(png, width="stretch")
    st.download_button("Download PNG", png, file_name=f"season_{which.replace(' ', '_')}.png", mime="image/png")


# ============================================================
# PAGE: ADD GAME
# ============================================================
def page_add_game():
    st.title("Add Game")
    st.write("Upload the Sportscode XML export and fill in the match details.")

    with st.form("add_game", clear_on_submit=False):
        c1, c2 = st.columns(2)
        opponent = c1.text_input("Opponent *", placeholder="e.g. Cambridge UTD")
        match_date = c2.date_input("Match date", value=date.today())
        c3, c4, c5 = st.columns(3)
        competition = c3.selectbox("Competition", ["League", "Cup", "Friendly", "Tournament", "Other"])
        venue = c4.selectbox("Venue", ["Home", "Away", "Neutral"])
        age_group = c5.text_input("Age group", value=AGE_GROUP_DEFAULT)
        notes = st.text_area("Notes (optional)", height=80)
        xml_file = st.file_uploader("Sportscode XML *", type=["xml"])
        opp_logo_file = st.file_uploader("Opponent crest (optional)", type=["png", "jpg", "jpeg", "webp"])

        with st.expander("Sportscode code names (only change if your XML uses different names)"):
            codes = {}
            cols = st.columns(2)
            for i, (k, v) in enumerate(charts.DEFAULT_CODES.items()):
                codes[k] = cols[i % 2].text_input(k, value=v)

        submitted = st.form_submit_button("Save game", type="primary")

    if not submitted:
        return
    if not opponent.strip() or xml_file is None:
        st.error("Opponent name and an XML file are both required.")
        return

    xml_bytes = xml_file.getvalue()
    try:
        m = charts.parse_match(xml_bytes, codes)
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't read that XML: {e}")
        return

    summ = charts.summarize(m)
    nothing_matched = all(v == 0 for side in summ.values() for v in side.values())
    if nothing_matched:
        st.error("None of your code names were found in this XML, so nothing was saved.")
        st.write("Codes found in the file:")
        st.dataframe(pd.DataFrame(sorted(m["codes_found"].items(), key=lambda kv: -kv[1]),
                                  columns=["Code", "Count"]), hide_index=True)
        return

    game_id = uuid.uuid4().hex[:8]
    fname = f"{game_id}.xml"
    (XML_DIR / fname).write_bytes(xml_bytes)
    games = load_games()
    games.append({
        "id": game_id, "date": match_date.isoformat(), "opponent": opponent.strip(),
        "competition": competition, "venue": venue, "age_group": age_group.strip() or AGE_GROUP_DEFAULT,
        "notes": notes.strip(), "xml_file": fname, "codes": codes,
    })
    if opp_logo_file is not None:
        logo_name = f"{game_id}{Path(opp_logo_file.name).suffix.lower()}"
        (OPP_LOGO_DIR / logo_name).write_bytes(opp_logo_file.getvalue())
        games[-1]["opp_logo"] = logo_name
    save_games(games)
    st.cache_data.clear()

    gf, ga = summ["team"]["Goals"], summ["opp"]["Goals"]
    st.success(f"Saved: {CLUB} {gf}-{ga} {opponent.strip()}. Open **Match Centre** to see the charts.")
    st.caption("Sanity check - detected goal minutes (video-time based, no stoppage time):")
    if m["goals"]:
        st.write(", ".join(f"{g['minute']}' ({TEAM_SHORT if g['side'] == 'team' else 'Opp'})" for g in m["goals"]))
    else:
        st.write("No goals detected.")


# ============================================================
# ROUTER
# ============================================================
_logo = club_logo_uri()
if _logo:
    st.sidebar.markdown(f'<img src="{_logo}" style="width:90px;margin-bottom:.5rem">', unsafe_allow_html=True)
st.sidebar.title(CLUB)
st.sidebar.caption(f"{AGE_GROUP_DEFAULT} match analysis")
page = st.sidebar.radio("Navigate", ["Match Centre", "Season Overview", "Add Game"], label_visibility="collapsed")
{"Match Centre": page_match_centre, "Season Overview": page_season, "Add Game": page_add_game}[page]()
