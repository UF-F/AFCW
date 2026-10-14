"""
Parsing + chart functions for the AFC Wimbledon match dashboard.

This is your original chart-pack script refactored so that:
  - nothing runs at import time
  - every chart takes parsed match data and RETURNS a matplotlib figure
  - the Sportscode code names are configurable per game
"""

import io
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from mplsoccer import Pitch, grid

# ============================================================
# CONFIG
# ============================================================
BUCKET_SIZE = 15
MATCH_LENGTH = 90
HALFTIME_GAP_THRESHOLD = 300  # seconds

DEFAULT_CODES = {
    "team_pb": "PB ENTRY",
    "opp_pb": "OPP PB ENTRY",
    "team_f3": "FINAL 3RD",
    "opp_f3": "OPP FINAL 3RD",
    "team_shot_on": "SHOTS ON",
    "team_shot_off": "SHOTS OFF",
    "team_shot_blocked": "SHOTS BLOCKED",
    "opp_shot_on": "OPP SHOT ON",
    "opp_shot_off": "OPP SHOT OFF",
    "opp_shot_blocked": "OPP SHOT BLOCKED",
    "team_goal": "GOAL",
    "opp_goal": "OPP GOAL",
    "team_offside": "OFFSIDE",
    "opp_offside": "OPP OFFSIDE",
    "team_corner": "ATT CORNER",
    "opp_corner": "DEF CORNER",
    "team_cross": "CROSS",
    "opp_cross": "OPP CROSS",
    "team_cross_success": "SUCCESSFUL CROSS",
    "opp_cross_success": "OPP SUCCESSFUL CROSS",
    "cross_label_group": "CROSSES",
    "cross_success_text": "SUCCESSFUL",
    "kickoff": "KICK-OFF",
    "label_group": "FINAL 3RD ENTRIES",
}

ZONE_LABELS = ["LEFT", "CENTRE", "RIGHT"]
OUTCOME_ORDER = ["Blocked", "Off Target", "On Target", "Goal"]  # bottom-to-top

# dark bucket-chart colours
NAVY = "#0B1F3A"
GOLD = "#FFC72C"
RED = "#E74C3C"
GREY = "#9E9E9E"
GREEN = "#00E676"
BLUE_GREY = "#5B7BA6"
OUTCOME_STYLE = {"Blocked": GREY, "Off Target": RED, "On Target": GOLD, "Goal": GREEN}

# light infographic colours
NAVY_TEXT = "#111111"
BLUE = "#2151E5"
GREY_TEXT = "#6B7280"
LIGHT_RULE = "#E3E3E3"
PITCH_FACE = "#F2F2F0"
PITCH_LINE = "#BDBDBD"
FINAL_THIRD_SHADE = "#DCE6FA"

FIG_HEIGHT = 8
AX_ASPECT = 2.15


def bucket_labels():
    n = MATCH_LENGTH // BUCKET_SIZE
    return [f"{i * BUCKET_SIZE}-{(i + 1) * BUCKET_SIZE}" for i in range(n)]


# ============================================================
# PARSING
# ============================================================
def _parse_zone_entries(instances, entry_code, label_group):
    zone_counts = {z: 0 for z in ZONE_LABELS}
    total = 0
    for inst in instances:
        code = inst.find("code")
        if code is None or code.text != entry_code:
            continue
        total += 1
        texts = []
        for lab in inst.findall("label"):
            group, text = lab.find("group"), lab.find("text")
            if group is not None and text is not None and group.text == label_group:
                texts.append(text.text)
        for z in ZONE_LABELS:
            if z in texts:
                zone_counts[z] += 1
    return zone_counts, total


def _count_labelled(instances, code, group, text):
    """Counts instances of `code` that carry a label (group, text). An instance counts once."""
    n = 0
    for inst in instances:
        c = inst.find("code")
        if c is None or c.text != code:
            continue
        for lab in inst.findall("label"):
            g, t = lab.find("group"), lab.find("text")
            if g is not None and t is not None and g.text == group and t.text == text:
                n += 1
                break
    return n


def _find_halftime_gap(rows):
    prev_end = rows[0][1]
    best_gap, best_size = (0, 0), 0
    for s, e, _ in rows:
        gap = s - prev_end
        if gap > best_size:
            best_size, best_gap = gap, (prev_end, s)
        prev_end = max(prev_end, e)
    return best_gap if best_size > HALFTIME_GAP_THRESHOLD else None


def _build_minute_converter(rows, kickoff_code):
    kickoff = next((s for s, _, c in rows if c == kickoff_code), rows[0][0])
    gap = _find_halftime_gap(rows)
    if gap is None:
        return (lambda start: (start - kickoff) / 60), False
    gap_start, gap_end = gap

    def to_minute(start):
        if start < gap_start:
            return (start - kickoff) / 60
        return 45 + (start - gap_end) / 60

    return to_minute, True


def _bucket_for(minute):
    minute = max(0, min(minute, MATCH_LENGTH - 0.01))
    lo = int(minute // BUCKET_SIZE) * BUCKET_SIZE
    return f"{lo}-{lo + BUCKET_SIZE}"


def parse_match(xml_bytes, codes=None):
    """Parse a Sportscode XML export into a plain dict of match data."""
    codes = {**DEFAULT_CODES, **(codes or {})}
    root = ET.fromstring(xml_bytes)
    container = root.find("ALL_INSTANCES")
    if container is None:
        raise ValueError("No <ALL_INSTANCES> found - is this a Sportscode XML export?")
    instances = container.findall("instance")

    rows = []
    for inst in instances:
        try:
            rows.append((float(inst.find("start").text),
                         float(inst.find("end").text),
                         inst.find("code").text))
        except (AttributeError, TypeError, ValueError):
            continue
    if not rows:
        raise ValueError("The XML contains no usable instances.")
    rows.sort(key=lambda r: r[0])

    to_minute, halftime_found = _build_minute_converter(rows, codes["kickoff"])
    labels = bucket_labels()

    def zeros():
        return {b: 0 for b in labels}

    m = {
        "buckets": labels,
        "pb": {"team": zeros(), "opp": zeros()},
        "f3": {"team": zeros(), "opp": zeros()},
        "shots": {
            "team": {o: zeros() for o in OUTCOME_ORDER},
            "opp": {o: zeros() for o in OUTCOME_ORDER},
        },
        "goals": [],
        "extras": {s_: {"Offsides": 0, "Corners": 0, "Crosses": 0, "Successful crosses": 0}
                   for s_ in ("team", "opp")},
        "halftime_found": halftime_found,
        "codes_found": {},
    }

    shot_map = {
        codes["team_shot_blocked"]: ("team", "Blocked"),
        codes["team_shot_off"]: ("team", "Off Target"),
        codes["team_shot_on"]: ("team", "On Target"),
        codes["team_goal"]: ("team", "Goal"),
        codes["opp_shot_blocked"]: ("opp", "Blocked"),
        codes["opp_shot_off"]: ("opp", "Off Target"),
        codes["opp_shot_on"]: ("opp", "On Target"),
        codes["opp_goal"]: ("opp", "Goal"),
    }

    extras_map = {
        codes["team_offside"]: ("team", "Offsides"), codes["opp_offside"]: ("opp", "Offsides"),
        codes["team_corner"]: ("team", "Corners"), codes["opp_corner"]: ("opp", "Corners"),
        codes["team_cross"]: ("team", "Crosses"), codes["opp_cross"]: ("opp", "Crosses"),
        codes["team_cross_success"]: ("team", "Successful crosses"),
        codes["opp_cross_success"]: ("opp", "Successful crosses"),
    }

    for start, _, code in rows:
        m["codes_found"][code] = m["codes_found"].get(code, 0) + 1
        minute = to_minute(start)
        b = _bucket_for(minute)
        if code == codes["team_pb"]:
            m["pb"]["team"][b] += 1
        elif code == codes["opp_pb"]:
            m["pb"]["opp"][b] += 1
        elif code == codes["team_f3"]:
            m["f3"]["team"][b] += 1
        elif code == codes["opp_f3"]:
            m["f3"]["opp"][b] += 1
        elif code in extras_map:
            side, stat = extras_map[code]
            m["extras"][side][stat] += 1
        elif code in shot_map:
            side, outcome = shot_map[code]
            m["shots"][side][outcome][b] += 1
            if outcome == "Goal":
                m["goals"].append({"side": side, "minute": round(minute, 1), "bucket": b})

    # Successful crosses: a label on the cross instance (e.g. CROSSES > SUCCESSFUL),
    # on top of any separate "successful cross" code if you use one.
    for side, cross_code in (("team", codes["team_cross"]), ("opp", codes["opp_cross"])):
        m["extras"][side]["Successful crosses"] += _count_labelled(
            instances, cross_code, codes["cross_label_group"], codes["cross_success_text"])

    m["goals"].sort(key=lambda g: g["minute"])
    m["zones"] = {
        "team": _parse_zone_entries(instances, codes["team_f3"], codes["label_group"]),
        "opp": _parse_zone_entries(instances, codes["opp_f3"], codes["label_group"]),
    }
    return m


def summarize(m):
    """Headline numbers per side."""
    out = {}
    for side in ("team", "opp"):
        s = m["shots"][side]
        tot = lambda d: sum(d.values())
        goals, on, off, blocked = tot(s["Goal"]), tot(s["On Target"]), tot(s["Off Target"]), tot(s["Blocked"])
        total_shots = goals + on + off + blocked
        out[side] = {
            "Goals": goals,
            "Total shots": total_shots,
            "Shots on target": goals + on,
            "Shots off target": off,
            "Shots blocked": blocked,
            "Penalty box entries": tot(m["pb"][side]),
            "Final third entries": tot(m["f3"][side]),
            **m.get("extras", {}).get(side, {"Offsides": 0, "Corners": 0, "Crosses": 0, "Successful crosses": 0}),
        }
    return out


def aggregate(matches):
    """Sum several parsed matches into one (for the season view)."""
    labels = bucket_labels()
    agg = {
        "buckets": labels,
        "pb": {s: {b: 0 for b in labels} for s in ("team", "opp")},
        "f3": {s: {b: 0 for b in labels} for s in ("team", "opp")},
        "shots": {s: {o: {b: 0 for b in labels} for o in OUTCOME_ORDER} for s in ("team", "opp")},
        "goals": [],
    }
    for m in matches:
        for s in ("team", "opp"):
            for b in labels:
                agg["pb"][s][b] += m["pb"][s][b]
                agg["f3"][s][b] += m["f3"][s][b]
                for o in OUTCOME_ORDER:
                    agg["shots"][s][o][b] += m["shots"][s][o][b]
        agg["goals"].extend(m["goals"])
    return agg


# ============================================================
# CHARTS - dark 15-minute bucket charts
# ============================================================
def _title_and_endnote(axs, ctx, subtitle):
    axs["title"].axis(False)
    axs["title"].text(0.5, 0.65, ctx["match_label"], color="white", fontsize=17,
                      fontweight="bold", ha="center", va="center",
                      transform=axs["title"].transAxes)
    axs["title"].text(0.5, 0.15, subtitle, color=GOLD, fontsize=12,
                      ha="center", va="center", transform=axs["title"].transAxes)
    axs["endnote"].axis(False)
    axs["endnote"].text(1.0, 0.5, ctx["credit"], color="white", fontsize=9,
                        ha="right", va="center", alpha=0.6,
                        transform=axs["endnote"].transAxes)


def make_bucket_chart(m, ctx, metric, title, team_label, opp_label):
    """metric is 'pb' or 'f3'."""
    labels = m["buckets"]
    team_vals, opp_vals = m[metric]["team"], m[metric]["opp"]
    team_goals, opp_goals = m["shots"]["team"]["Goal"], m["shots"]["opp"]["Goal"]
    x, width = range(len(labels)), 0.38

    fig, axs = grid(ax_aspect=AX_ASPECT, figheight=FIG_HEIGHT, grid_height=0.75, grid_width=0.92,
                    title_height=0.12, title_space=0.02, endnote_height=0.05, endnote_space=0.01,
                    axis=False, grid_key="bars")
    fig.set_facecolor(NAVY)
    ax = axs["bars"]
    ax.set_facecolor(NAVY)
    ax.axis(True)

    team_bars = ax.bar([i - width / 2 for i in x], [team_vals[b] for b in labels],
                       width=width, color=GOLD, label=team_label, zorder=3)
    opp_bars = ax.bar([i + width / 2 for i in x], [opp_vals[b] for b in labels],
                      width=width, color=BLUE_GREY, label=opp_label, zorder=3)

    for bars in (team_bars, opp_bars):
        for rect in bars:
            h = rect.get_height()
            if h > 0:
                ax.text(rect.get_x() + rect.get_width() / 2, h + 0.15, str(int(h)),
                        ha="center", va="bottom", color="white", fontsize=9, fontweight="bold")

    star_gap = max([max(team_vals.values()), max(opp_vals.values())] + [1]) * 0.16
    for i, b in enumerate(labels):
        base = max(team_vals[b], opp_vals[b]) + star_gap
        for g in range(team_goals[b]):
            ax.scatter(i - width / 2, base + g * star_gap, marker="*", s=260,
                       color=GREEN, edgecolors="white", linewidth=1, zorder=5)
        for g in range(opp_goals[b]):
            ax.scatter(i + width / 2, base + g * star_gap, marker="*", s=260,
                       color=RED, edgecolors="white", linewidth=1, zorder=5)

    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{b}'" for b in labels], color="white", fontsize=10)
    ax.tick_params(axis="y", colors="white")
    ax.spines[:].set_color("white")
    ax.grid(axis="y", color="white", alpha=0.15, zorder=0)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.15)

    bar_legend = ax.legend(loc="upper left", facecolor=NAVY, edgecolor="white",
                           labelcolor="white", fontsize=10)
    ax.add_artist(bar_legend)
    goal_handles = [
        mpatches.Patch(facecolor=GREEN, edgecolor="white", label=f"{ctx['team_short']} Goal"),
        mpatches.Patch(facecolor=RED, edgecolor="white", label="Opp Goal"),
    ]
    goal_legend = ax.legend(handles=goal_handles, loc="upper right", facecolor=NAVY,
                            edgecolor="white", labelcolor="white", fontsize=9,
                            title="Goals", title_fontsize=9)
    goal_legend.get_title().set_color("white")

    _title_and_endnote(axs, ctx, f"{title} — 15-minute windows")
    return fig


def make_shots_chart(m, ctx):
    labels = m["buckets"]
    x, width = list(range(len(labels))), 0.38

    fig, axs = grid(ax_aspect=AX_ASPECT, figheight=FIG_HEIGHT, grid_height=0.75, grid_width=0.92,
                    title_height=0.12, title_space=0.02, endnote_height=0.06, endnote_space=0.01,
                    axis=False, grid_key="bars")
    fig.set_facecolor(NAVY)
    ax = axs["bars"]
    ax.set_facecolor(NAVY)
    ax.axis(True)

    def plot_stack(offset, shot_dict):
        bottoms = [0] * len(labels)
        for outcome in OUTCOME_ORDER:
            vals = [shot_dict[outcome][b] for b in labels]
            bars = ax.bar([i + offset for i in x], vals, width=width, bottom=bottoms,
                          color=OUTCOME_STYLE[outcome], edgecolor=NAVY, linewidth=0.6, zorder=3)
            for rect, v, bot in zip(bars, vals, bottoms):
                if v > 0:
                    ax.text(rect.get_x() + rect.get_width() / 2, bot + v / 2, str(v),
                            ha="center", va="center", color=NAVY, fontsize=8, fontweight="bold")
            bottoms = [b + v for b, v in zip(bottoms, vals)]
        for i, tot in enumerate(bottoms):
            if tot > 0:
                ax.text(i + offset, tot + 0.15, str(tot), ha="center", va="bottom",
                        color="white", fontsize=9, fontweight="bold")
        return bottoms

    team_totals = plot_stack(-width / 2, m["shots"]["team"])
    opp_totals = plot_stack(width / 2, m["shots"]["opp"])
    top = max(max(team_totals), max(opp_totals), 1)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{b}'" for b in labels], color="white", fontsize=10)
    for i in x:
        ax.text(i - width / 2, -top * 0.09, ctx["team_short"], ha="center", va="top",
                color=GOLD, fontsize=7.5, fontweight="bold")
        ax.text(i + width / 2, -top * 0.09, "OPP", ha="center", va="top",
                color=BLUE_GREY, fontsize=7.5, fontweight="bold")

    ax.tick_params(axis="y", colors="white")
    ax.spines[:].set_color("white")
    ax.grid(axis="y", color="white", alpha=0.15, zorder=0)
    ax.set_ylim(0, top * 1.18)

    handles = [mpatches.Patch(facecolor=OUTCOME_STYLE[o], edgecolor=NAVY, label=o)
               for o in OUTCOME_ORDER]
    ax.legend(handles=handles, loc="upper left", ncol=4, facecolor=NAVY, edgecolor="white",
              labelcolor="white", fontsize=9, columnspacing=1.0, handlelength=1.4)

    _title_and_endnote(axs, ctx, "Shots by Outcome — 15-minute windows")
    return fig


# ============================================================
# CHARTS - light final-third infographics
# ============================================================
def make_infographic(zone_counts, total_count, ctx, *, reversed_orientation,
                     heading, big_name, sub_name, attacking_direction_label):
    fig = plt.figure(figsize=(14, 8), facecolor="white")
    LX, LX2 = 0.045, 0.335

    fig.text(LX, 0.93, heading, fontsize=14, fontweight="bold", color=BLUE, ha="left", va="center")
    fig.text(LX, 0.845, big_name, fontsize=32, fontweight="bold", color=NAVY_TEXT, ha="left", va="center")
    fig.text(LX, 0.775, sub_name, fontsize=18, color=GREY_TEXT, ha="left", va="center")
    fig.add_artist(Line2D([LX, LX2], [0.735, 0.735], color=LIGHT_RULE, linewidth=1.2))

    fig.text(LX, 0.665, f"{total_count}", fontsize=38, fontweight="bold", color=NAVY_TEXT, ha="left", va="center")
    fig.text(LX, 0.615, "TOTAL ENTRIES", fontsize=12, color=GREY_TEXT, ha="left", va="center")
    fig.add_artist(Line2D([LX, LX2], [0.565, 0.565], color=LIGHT_RULE, linewidth=1.2))

    primary_zone = max(zone_counts, key=zone_counts.get)
    zone_phrase = "flank" if primary_zone in ("LEFT", "RIGHT") else "channel"
    line1 = f"{primary_zone.title()} {zone_phrase} was the"
    if not reversed_orientation:
        lines = [line1, "primary route into the", "final third, with",
                 f"{zone_counts[primary_zone]} of {total_count} entries", "coming through it."]
    else:
        lines = [line1, "primary route into", f"{ctx['team_name']}'s final third,",
                 f"with {zone_counts[primary_zone]} of {total_count}", "entries coming through it."]
    for y, line in zip([0.49, 0.445, 0.40, 0.355, 0.31], lines):
        fig.text(LX, y, line, fontsize=14, color=GREY_TEXT, ha="left", va="center")
    fig.text(LX, 0.045, ctx["credit"], fontsize=9, color=GREY_TEXT, ha="left", va="center", alpha=0.7)

    pitch = Pitch(pitch_type="statsbomb", pitch_color=PITCH_FACE, line_color=PITCH_LINE,
                  linewidth=1.6, corner_arcs=True, pad_top=6, pad_bottom=6, pad_left=3, pad_right=3)
    ax = fig.add_axes([0.375, 0.155, 0.595, 0.72])
    pitch.draw(ax=ax)
    pitch_len, pitch_wid = 120, 80

    if not reversed_orientation:
        third_x = pitch_len * 2 / 3
        ax.axvspan(third_x, pitch_len, color=FINAL_THIRD_SHADE, zorder=0)
        label_x = (third_x + pitch_len) / 2
        arrow_start, arrow_end = 24, 46
        count_ha, label_ha, count_off, label_off = "right", "left", -5, 5
        ad_xy, ad_xytext = (0.97, 0.5), (0.03, 0.5)
    else:
        third_x = pitch_len / 3
        ax.axvspan(0, third_x, color=FINAL_THIRD_SHADE, zorder=0)
        label_x = third_x / 2
        arrow_start, arrow_end = pitch_len - 24, pitch_len - 46
        count_ha, label_ha, count_off, label_off = "left", "right", 5, -5
        ad_xy, ad_xytext = (0.03, 0.5), (0.97, 0.5)

    ax.plot([third_x, third_x], [0, pitch_wid], color=BLUE, linestyle=(0, (5, 4)), linewidth=2.2, zorder=1)
    ax.text(label_x, -6, "FINAL THIRD", fontsize=13, fontweight="bold", color=BLUE, ha="center", va="center")

    band_y = {"LEFT": pitch_wid / 6, "CENTRE": pitch_wid / 2, "RIGHT": pitch_wid * 5 / 6}
    for zone in ZONE_LABELS:
        y = band_y[zone]
        ax.annotate("", xy=(arrow_end, y), xytext=(arrow_start, y),
                    arrowprops=dict(arrowstyle="-|>", color=BLUE, linewidth=8,
                                    mutation_scale=32, shrinkA=0, shrinkB=0), zorder=3)
        ax.text(arrow_start + count_off, y, f"{zone_counts[zone]}", fontsize=22, fontweight="bold",
                color=NAVY_TEXT, ha=count_ha, va="center", zorder=3)
        ax.text(arrow_end + label_off, y, zone, fontsize=15, fontweight="bold",
                color=NAVY_TEXT, ha=label_ha, va="center", zorder=3)

    ad_ax = fig.add_axes([0.375, 0.075, 0.595, 0.035])
    ad_ax.axis("off")
    ad_ax.set_xlim(0, 1)
    ad_ax.set_ylim(0, 1)
    ad_ax.annotate("", xy=ad_xy, xytext=ad_xytext,
                   arrowprops=dict(arrowstyle="-|>", color=GREY_TEXT, linewidth=1.6, mutation_scale=18))
    fig.text(0.6725, 0.045, attacking_direction_label, fontsize=11, color=GREY_TEXT,
             ha="center", va="center")
    return fig


# ============================================================
# RENDER EVERYTHING -> PNG BYTES
# ============================================================
def fig_to_png(fig, tight=True):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor=fig.get_facecolor(),
                bbox_inches="tight" if tight else None)
    plt.close(fig)
    return buf.getvalue()


def render_all(m, ctx, include_infographics=True):
    """Returns {chart name: PNG bytes}."""
    out = {
        "Penalty Box Entries": fig_to_png(make_bucket_chart(
            m, ctx, "pb", "Penalty Box Entries", f"{ctx['team_short']} PB Entries", "Opp PB Entries")),
        "Final Third Entries": fig_to_png(make_bucket_chart(
            m, ctx, "f3", "Final Third Entries", f"{ctx['team_short']} F3 Entries", "Opp F3 Entries")),
        "Shots by Outcome": fig_to_png(make_shots_chart(m, ctx)),
    }
    if include_infographics:
        tz, tt = m["zones"]["team"]
        oz, ot = m["zones"]["opp"]
        out["Team Final Third Infographic"] = fig_to_png(make_infographic(
            tz, tt, ctx, reversed_orientation=False, heading="FINAL THIRD ENTRIES",
            big_name=ctx["team_name"], sub_name=f"vs {ctx['opponent_name']}",
            attacking_direction_label="ATTACKING DIRECTION"), tight=False)
        out["Opposition Final Third Infographic"] = fig_to_png(make_infographic(
            oz, ot, ctx, reversed_orientation=True, heading="OPPOSITION FINAL THIRD ENTRIES",
            big_name=ctx["opponent_name"], sub_name=f"vs {ctx['team_name']}",
            attacking_direction_label="OPPOSITION ATTACKING DIRECTION"), tight=False)
    return out
