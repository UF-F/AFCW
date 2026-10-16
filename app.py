"""
AFC Wimbledon U16 - Match Dashboard
Run with:  streamlit run app.py
"""

import base64
import hmac
import html
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
import storage

# ============================================================
# SETTINGS - change these once
# ============================================================
CLUB = "AFC Wimbledon"
TEAM_SHORT = "AFCW"          # used in chart legends
TEAM_NAME = "Wimbledon"      # used on the infographics
AGE_GROUP_DEFAULT = "U16"
CREDIT = "@Neil_barretto"

BASE_DIR = Path(__file__).resolve().parent  # always next to app.py, wherever you launch from
ASSETS_DIR = BASE_DIR / "assets"   # club logo lives here (committed with the app)

st.set_page_config(page_title=f"{CLUB} Match Dashboard", page_icon="⚽", layout="wide")

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2rem; }}
      h1, h2, h3 {{ color: {charts.NAVY}; }}
      [data-testid="stSidebar"] {{ background: {charts.NAVY}; }}
      [data-testid="stSidebar"] * {{ color: white !important; }}
      [data-testid="stMetric"] {{ background:{charts.NAVY}; border-radius:14px; padding:.9rem 1.1rem; }}
      [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{ color:white !important; }}
      [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{ color:#CBD5E1 !important; }}

      /* ---- sidebar navigation ---- */
      [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {{
          background:transparent; border:1px solid transparent; justify-content:flex-start;
          padding:.55rem .9rem; border-radius:10px; }}
      [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]:hover {{
          background:rgba(255,255,255,.10); border-color:transparent; }}
      [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
          background:{charts.GOLD}; border:1px solid {charts.GOLD}; justify-content:flex-start;
          padding:.55rem .9rem; border-radius:10px; }}
      [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] * {{
          color:{charts.NAVY} !important; font-weight:700; }}

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
# STORAGE - private GitHub repo on Streamlit Cloud, local folder otherwise
# ============================================================
def _make_store():
    try:
        cfg = st.secrets["github"]
    except Exception:  # noqa: BLE001  (no secrets configured -> run locally)
        return storage.LocalStorage(BASE_DIR / "data")
    try:
        return storage.GitHubStorage(cfg["token"], cfg["repo"], cfg.get("branch", "main"), cfg.get("folder", ""))
    except KeyError as e:
        st.error(f"Your [github] secrets are missing {e}. They need at least `token` and `repo`.")
        st.stop()


store = _make_store()


@st.cache_data(ttl=60, show_spinner=False)
def storage_status():
    return store.check()


@st.cache_data(show_spinner=False, ttl=600)
def load_games():
    raw = store.read("games.json")
    return json.loads(raw) if raw else []


def save_games(games):
    store.write("games.json", json.dumps(games, indent=2).encode(), "Update games list")
    st.cache_data.clear()


@st.cache_data(show_spinner="Loading game data...")
def read_xml(xml_file):
    data = store.read(f"xml/{xml_file}")
    if data is None:
        raise FileNotFoundError(f"xml/{xml_file} is missing from storage")
    return data


@st.cache_data(show_spinner=False)
def read_logo(name):
    return store.read(f"opponents/{name}")


def xml_bytes_for(game):
    return read_xml(game["xml_file"])


def is_admin():
    """Editing is open to everyone unless an `admin_password` secret is set.
    With it set, only people who log in as admin can add/delete games or edit code names."""
    try:
        st.secrets["admin_password"]
    except Exception:  # noqa: BLE001
        return True
    return bool(st.session_state.get("is_admin"))


OLD_DEFAULTS = {"team_corner": "CORNER", "opp_corner": "OPP CORNER"}  # earlier guesses, since corrected


def codes_for(game):
    """The game's saved code names, filled in with defaults and with stale guesses upgraded."""
    codes = {**charts.DEFAULT_CODES, **game.get("codes", {})}
    for k, old in OLD_DEFAULTS.items():
        if codes.get(k) == old:
            codes[k] = charts.DEFAULT_CODES[k]
    return codes


def match_ctx(game):
    age = game.get("age_group", AGE_GROUP_DEFAULT)
    return {
        "match_label": f"{CLUB} {age} vs {game['opponent']} {age}",
        "credit": CREDIT,
        "team_short": TEAM_SHORT,
        "team_name": TEAM_NAME,
        "opponent_name": game["opponent"].upper(),
    }


CACHE_VERSION = 2  # bump when charts.py parsing changes


@st.cache_data(show_spinner=False)
def parse_cached(xml_bytes, codes_json, _v=CACHE_VERSION):
    return charts.parse_match(xml_bytes, json.loads(codes_json))


@st.cache_data(show_spinner="Rendering charts...")
def render_cached(xml_bytes, codes_json, ctx_json, _v=CACHE_VERSION):
    m = parse_cached(xml_bytes, codes_json)
    return charts.render_all(m, json.loads(ctx_json))


def parsed(game):
    return parse_cached(xml_bytes_for(game), json.dumps(codes_for(game), sort_keys=True))


def pct(a, b):
    return round(100 * a / b, 1) if b else 0.0


def score_of(m):
    s = charts.summarize(m)
    return s["team"]["Goals"], s["opp"]["Goals"]


def game_label(game):
    gf, ga = score_of(parsed(game))
    return f"{game['date']}  |  vs {game['opponent']}  ({gf}-{ga})"


# ============================================================
# LOGOS + HTML COMPONENTS
# ============================================================
MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".svg": "image/svg+xml"}


def bytes_uri(data, suffix):
    mime = MIME_BY_EXT.get(suffix.lower(), "image/png")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def b64_uri(path):
    return bytes_uri(path.read_bytes(), path.suffix)


def club_logo_uri():
    """Looks for assets/logo.png (or .jpg/.jpeg/.webp/.svg)."""
    for ext in ("png", "jpg", "jpeg", "webp", "svg"):
        p = ASSETS_DIR / f"logo.{ext}"
        if p.exists():
            return b64_uri(p)
    return None


def opp_logo_uri(game):
    f = game.get("opp_logo")
    if not f:
        return None
    data = read_logo(f)
    return bytes_uri(data, Path(f).suffix) if data else None


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
        ("Corners", t["Corners"], o["Corners"], str(t["Corners"]), str(o["Corners"])),
        ("Offsides", t["Offsides"], o["Offsides"], str(t["Offsides"]), str(o["Offsides"])),
        ("Crosses", t["Crosses"], o["Crosses"], str(t["Crosses"]), str(o["Crosses"])),
        ("Successful crosses", t["Successful crosses"], o["Successful crosses"], str(t["Successful crosses"]), str(o["Successful crosses"])),
        ("Cross accuracy", pct(t["Successful crosses"], t["Crosses"]), pct(o["Successful crosses"], o["Crosses"]),
         f'{pct(t["Successful crosses"], t["Crosses"]):.0f}%', f'{pct(o["Successful crosses"], o["Crosses"]):.0f}%'),
    ]
    lower_is_better = {"Offsides"}
    out = [f'<div class="stats-card"><div class="stats-head"><span class="l">{TEAM_SHORT}</span>'
           f'<span class="r">{html.escape(game["opponent"]).upper()}</span></div>']
    for label, tv, ov, td, od in rows:
        t_wins, o_wins = (tv < ov, ov < tv) if label in lower_is_better else (tv > ov, ov > tv)
        lcls = "stat-val left" + (" pill-t" if t_wins else "")
        rcls = "stat-val right" + (" pill-o" if o_wins else "")
        total = tv + ov
        share = 100 * tv / total if total else 50
        out.append(
            '<div class="stat-row"><div class="stat-line">'
            f'<span class="{lcls}">{td}</span><span class="stat-label">{label}</span><span class="{rcls}">{od}</span>'
            f'</div><div class="split"><div class="split-t" style="width:{share:.1f}%"></div>'
            f'<div class="split-o" style="width:{100 - share:.1f}%"></div></div></div>'
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
    pngs = render_cached(xml_bytes_for(game), json.dumps(codes_for(game), sort_keys=True), json.dumps(ctx))

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
        with st.expander("Codes found in this XML (use these exact names in the code settings)"):
            st.dataframe(pd.DataFrame(sorted(m["codes_found"].items(), key=lambda kv: -kv[1]),
                                      columns=["Code", "Count"]), hide_index=True, width="stretch")
        zt, tt = m["zones"]["team"]
        zo, to = m["zones"]["opp"]
        st.subheader("Final third entries by channel")
        st.dataframe(pd.DataFrame({f"{TEAM_SHORT} ({tt})": zt, f"{game['opponent']} ({to})": zo}),
                     width="stretch")

    if is_admin():
        with st.expander("Edit Sportscode code names for this game"):
            new_codes = {}
            ccols = st.columns(2)
            for i, (k, v) in enumerate(charts.DEFAULT_CODES.items()):
                new_codes[k] = ccols[i % 2].text_input(k, value=codes_for(game).get(k, v), key=f"code_{k}_{game['id']}")
            if st.button("Save code names", key=f"save_codes_{game['id']}"):
                all_games = load_games()
                for g in all_games:
                    if g["id"] == game["id"]:
                        g["codes"] = new_codes
                save_games(all_games)
                st.cache_data.clear()
                st.rerun()

        with st.expander("Delete this game"):
            if st.checkbox("Yes, delete this game permanently", key=f"del_chk_{game['id']}"):
                if st.button("Delete", type="primary", key=f"del_btn_{game['id']}"):
                    try:
                        save_games([g for g in load_games() if g["id"] != game["id"]])
                        store.delete(f"xml/{game['xml_file']}", f"Delete game vs {game['opponent']}")
                        if game.get("opp_logo"):
                            store.delete(f"opponents/{game['opp_logo']}", f"Delete crest vs {game['opponent']}")
                    except storage.StorageError as e:
                        st.error(str(e))
                        st.stop()
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

    rows, matches, summs = [], [], []
    for g in chosen:
        m = parsed(g)
        matches.append(m)
        s = charts.summarize(m)
        summs.append((g, s))
        rows.append({
            "Date": g["date"], "Opponent": g["opponent"], "Competition": g.get("competition", ""),
            "GF": s["team"]["Goals"], "GA": s["opp"]["Goals"],
            "Shots": s["team"]["Total shots"], "Shots Agst": s["opp"]["Total shots"],
            "SOT": s["team"]["Shots on target"], "SOT Agst": s["opp"]["Shots on target"],
            "PB Entries": s["team"]["Penalty box entries"], "PB Agst": s["opp"]["Penalty box entries"],
            "F3 Entries": s["team"]["Final third entries"], "F3 Agst": s["opp"]["Final third entries"],
            "Corners": s["team"]["Corners"], "Offsides": s["team"]["Offsides"],
            "Crosses": s["team"]["Crosses"], "Succ. Crosses": s["team"]["Successful crosses"],
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

    # ---- percentages ----
    st.subheader("Percentages")
    tot = {side: {k: sum(s[side][k] for _, s in summs) for k in summs[0][1][side]} for side in ("team", "opp")}

    def three(side):
        x = tot[side]
        return (pct(x["Successful crosses"], x["Crosses"]),
                pct(x["Shots on target"], x["Total shots"]),
                pct(x["Penalty box entries"], x["Final third entries"]))

    tc, ts, tp = three("team")
    oc, os_, op = three("opp")
    p1, p2, p3 = st.columns(3)
    p1.metric("Cross accuracy %", f"{tc:.1f}%", delta=f"{tc - oc:+.1f} pts vs opp")
    p2.metric("Shot accuracy %", f"{ts:.1f}%", delta=f"{ts - os_:+.1f} pts vs opp")
    p3.metric("Penalty box entry %", f"{tp:.1f}%", delta=f"{tp - op:+.1f} pts vs opp")
    st.caption("Cross accuracy = successful crosses / crosses. Shot accuracy = shots on target (incl. goals) / total shots. "
               "Penalty box entry % = penalty box entries / final third entries. Season figures use totals across the "
               "selected games, not an average of each game's percentage.")

    pdf = pd.DataFrame([{
        "Game": f"{g['date']} {g['opponent']}",
        "Cross %": pct(s["team"]["Successful crosses"], s["team"]["Crosses"]),
        "Shot %": pct(s["team"]["Shots on target"], s["team"]["Total shots"]),
        "PB entry %": pct(s["team"]["Penalty box entries"], s["team"]["Final third entries"]),
        "Opp Cross %": pct(s["opp"]["Successful crosses"], s["opp"]["Crosses"]),
        "Opp Shot %": pct(s["opp"]["Shots on target"], s["opp"]["Total shots"]),
        "Opp PB entry %": pct(s["opp"]["Penalty box entries"], s["opp"]["Final third entries"]),
    } for g, s in summs])

    # ---- one stat, game by game ----
    metrics = {}
    for stat in ["Goals", "Total shots", "Shots on target", "Shots off target", "Shots blocked",
                 "Penalty box entries", "Final third entries", "Corners", "Offsides",
                 "Crosses", "Successful crosses"]:
        metrics[stat] = ([s["team"][stat] for _, s in summs], [s["opp"][stat] for _, s in summs], False,
                         round(sum(s["team"][stat] for _, s in summs) / len(summs), 1),
                         round(sum(s["opp"][stat] for _, s in summs) / len(summs), 1))
    metrics["Cross accuracy %"] = ([pct(s["team"]["Successful crosses"], s["team"]["Crosses"]) for _, s in summs],
                                   [pct(s["opp"]["Successful crosses"], s["opp"]["Crosses"]) for _, s in summs], True, tc, oc)
    metrics["Shot accuracy %"] = ([pct(s["team"]["Shots on target"], s["team"]["Total shots"]) for _, s in summs],
                                  [pct(s["opp"]["Shots on target"], s["opp"]["Total shots"]) for _, s in summs], True, ts, os_)
    metrics["Penalty box entry %"] = ([pct(s["team"]["Penalty box entries"], s["team"]["Final third entries"]) for _, s in summs],
                                      [pct(s["opp"]["Penalty box entries"], s["opp"]["Final third entries"]) for _, s in summs], True, tp, op)

    st.subheader("Game by game")
    cc1, cc2 = st.columns([3, 1])
    pick = cc1.selectbox("Choose a stat", list(metrics), index=list(metrics).index("Cross accuracy %"))
    with_opp = cc2.checkbox("Show opposition", value=True)
    tv, ov, is_pct, avg_t, avg_o = metrics[pick]
    short = []
    for g, _ in summs:
        d = date.fromisoformat(g["date"]).strftime("%d %b")
        opp = g["opponent"] if len(g["opponent"]) <= 14 else g["opponent"][:13] + "."
        short.append(f"{d}\n{opp}")
    gpng = charts.fig_to_png(charts.make_game_metric_chart(
        short, tv, ov, pick, is_pct,
        {"credit": CREDIT, "team_short": TEAM_SHORT}, show_opp=with_opp, avg_team=avg_t, avg_opp=avg_o))
    st.image(gpng, width="stretch")
    st.download_button("Download PNG", gpng, file_name=f"season_{pick.replace(' ', '_').replace('%', 'pct')}.png",
                       mime="image/png", key="dl_game_metric")
    st.dataframe(pdf, width="stretch", hide_index=True)

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
    if not is_admin():
        st.warning("Only the admin can add games.")
        return
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

    with st.expander("Backup & restore"):
        st.write("Your games are stored in " + ("a private GitHub repo." if store.name == "github"
                 else "the `data` folder next to `app.py`.") + " A zip backup is still a good safety copy.")
        if st.button("Prepare backup zip", key="prep_backup"):
            with st.spinner("Collecting files..."):
                st.session_state["backup_zip"] = storage.build_backup_zip(store)
        if st.session_state.get("backup_zip"):
            st.download_button("Download backup (zip)", st.session_state["backup_zip"],
                               file_name="afcw_dashboard_backup.zip", mime="application/zip")
        restore_file = st.file_uploader("Restore games from a backup zip", type=["zip"], key="restore_zip")
        if restore_file is not None and st.button("Restore games from this zip", key="restore_btn"):
            try:
                with st.spinner("Restoring..."):
                    added, skipped = storage.restore_backup_zip(store, restore_file.getvalue())
                st.cache_data.clear()
                st.success(f"Restored {added} game(s)." + (f" {skipped} skipped (XML missing from the zip)." if skipped else ""))
            except Exception as e:  # noqa: BLE001
                st.error(f"Couldn't restore: {e}")

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
    game_rec = {
        "id": game_id, "date": match_date.isoformat(), "opponent": opponent.strip(),
        "competition": competition, "venue": venue, "age_group": age_group.strip() or AGE_GROUP_DEFAULT,
        "notes": notes.strip(), "xml_file": fname, "codes": codes,
    }
    try:
        with st.spinner("Saving..."):
            store.write(f"xml/{fname}", xml_bytes, f"Add game vs {opponent.strip()}")
            if opp_logo_file is not None:
                logo_name = f"{game_id}{Path(opp_logo_file.name).suffix.lower()}"
                store.write(f"opponents/{logo_name}", opp_logo_file.getvalue(), f"Add crest vs {opponent.strip()}")
                game_rec["opp_logo"] = logo_name
            games = load_games()
            games.append(game_rec)
            save_games(games)  # games.json is written last, so a failure never leaves a half-added game listed
    except storage.StorageError as e:
        st.error(f"Couldn't save the game: {e}")
        return

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
def require_password():
    try:
        pw = st.secrets["app_password"]
    except Exception:  # noqa: BLE001
        return
    if st.session_state.get("authed"):
        return
    st.title(f"{CLUB} Match Dashboard")
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), str(pw).encode()):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()


require_password()

_ok, _msg = storage_status()
if not _ok:
    st.error(_msg)
    st.stop()
if _msg.startswith("WARNING"):
    st.warning(_msg)

_logo = club_logo_uri()
if _logo:
    st.sidebar.markdown(f'<img src="{_logo}" style="width:90px;margin-bottom:.5rem">', unsafe_allow_html=True)
st.sidebar.title(CLUB)
st.sidebar.caption(f"{AGE_GROUP_DEFAULT} match analysis  |  Storage: {store.label}")
ALL_PAGES = {"Match Centre": page_match_centre, "Season Overview": page_season, "Add Game": page_add_game}
PAGES = ALL_PAGES if is_admin() else {k: v for k, v in ALL_PAGES.items() if k != "Add Game"}
if st.session_state.get("page") not in PAGES:
    st.session_state.page = "Match Centre"


def go_to(name):
    st.session_state.page = name


st.sidebar.write("")
for name in PAGES:
    st.sidebar.button(name, key=f"nav_{name}", on_click=go_to, args=(name,), width="stretch",
                      type="primary" if st.session_state.page == name else "secondary")

def admin_login_box():
    try:
        admin_pw = st.secrets["admin_password"]
    except Exception:  # noqa: BLE001
        return
    if st.session_state.get("is_admin"):
        st.sidebar.write("")
        if st.sidebar.button("Log out of admin", key="admin_logout"):
            st.session_state["is_admin"] = False
            st.session_state["page"] = "Match Centre"
            st.rerun()
        return
    st.sidebar.write("")
    with st.sidebar.expander("Admin login"):
        entered = st.text_input("Admin password", type="password", key="admin_pw_input")
        if entered:
            if hmac.compare_digest(entered.encode(), str(admin_pw).encode()):
                st.session_state["is_admin"] = True
                st.rerun()
            st.error("Wrong password.")


admin_login_box()

try:
    PAGES[st.session_state.page]()
except storage.StorageError as e:
    st.error(str(e))
