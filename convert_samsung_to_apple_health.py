#!/usr/bin/env python3
"""
Samsung Health export  ->  CSV files that Health CSV Importer writes into Apple Health.

    python3 convert_samsung_to_apple_health.py /path/to/samsunghealth_<user>_<timestamp> -o apple_health_import

Samsung Health > Settings > Download personal data gives you a zip; unzip it and point this script
at the folder that holds the com.samsung.*.csv files and the jsons/ directory.

Output follows the published format of Lionheart Software's Health CSV Importer (iOS):
    header:      start datetime,end datetime,<type header> (<unit>)
    timestamps:  ISO 8601 with the ORIGINAL local UTC offset taken from Samsung's time_offset column.
                 Samsung stores start_time/end_time in UTC; the offset column (e.g. UTC+0100) gives local time.

Nothing leaves your machine. The script reads the export, writes CSVs, and prints a reconciliation log.
"""
import argparse
import collections
import csv
import datetime as dt
import glob
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

__version__ = "1.0.0"
UTC = dt.timezone.utc

# --------------------------------------------------------------------------- mappings
# Samsung exercise_type codes -> Health CSV Importer activity names
EXERCISE = {
    0: "other", 1001: "walking", 1002: "running", 2001: "baseball", 2002: "softball", 2003: "cricket",
    3001: "golf", 3002: "other", 3003: "bowling", 4001: "hockey", 4002: "rugby", 4003: "basketball",
    4004: "soccer", 4005: "handball", 4006: "american football", 5001: "volleyball", 5002: "volleyball",
    6001: "squash", 6002: "tennis", 6003: "badminton", 6004: "table tennis", 6005: "racquetball",
    7001: "tai chi", 7002: "boxing", 7003: "martial arts", 8001: "barre", 8002: "dance", 8003: "social dance",
    9001: "pilates", 9002: "yoga", 10001: "stretching", 10002: "jump rope", 10003: "other", 10004: "strength",
    10005: "strength", 10006: "core", 10007: "cross training", 10008: "core", 10009: "mixed cardio",
    10010: "hiit", 10011: "strength", 10012: "strength", 10013: "strength", 10014: "strength",
    10015: "strength", 10016: "strength", 10017: "strength", 10018: "strength", 10019: "strength",
    10020: "strength", 10021: "strength", 10022: "strength", 10023: "core", 10024: "core", 10025: "core",
    10026: "strength", 10027: "strength", 11001: "skating", 11002: "other", 11003: "other", 11004: "archery",
    11005: "equestrian", 11007: "cycling", 11008: "disc", 11009: "skating", 12001: "mixed cardio",
    13001: "hiking", 13002: "climbing", 13003: "hiking", 13004: "cycling", 13005: "other", 14001: "swimming",
    14002: "water fitness", 14003: "paddle", 14004: "sailing", 14005: "underwater diving",
    14006: "underwater diving", 14007: "paddle", 14008: "surfing", 14009: "paddle", 14010: "rowing",
    14011: "surfing", 14012: "sailing", 14013: "water sports", 15001: "stair climbing", 15002: "strength",
    15003: "cycling", 15004: "rowing", 15005: "running", 15006: "elliptical", 16001: "cross country skiing",
    16002: "downhill skiing", 16003: "skating", 16004: "skating", 16006: "hockey", 16007: "snowboarding",
    16008: "downhill skiing", 16009: "snow sports",
}
# Samsung sleep_stage codes -> Apple sleep analysis values (Samsung "light" is Apple "core")
SLEEP_STAGE = {"40001": "awake", "40002": "core", "40003": "deep", "40004": "rem"}

H_START, H_END = "start datetime", "end datetime"


# --------------------------------------------------------------------------- small helpers
class Row(dict):
    """A CSV row that answers '' for columns this export version does not have."""
    def __missing__(self, key):
        return ""


def parse_ts(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_offset(s):
    m = re.fullmatch(r"UTC([+-])(\d\d)(\d\d)", (s or "").strip())
    if not m:
        return None
    d = dt.timedelta(hours=int(m[2]), minutes=int(m[3]))
    return -d if m[1] == "-" else d


def fmt_local(t_local):
    s = t_local.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]


def num(x, nd=1):
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return ""


def default_timezone():
    """Best guess at the machine's zone (used only for daily totals on days with no timestamped samples)."""
    name = os.environ.get("TZ")
    if not name:
        try:
            link = os.readlink("/etc/localtime")
            name = link.split("zoneinfo/")[-1]
        except OSError:
            name = None
    try:
        return ZoneInfo(name) if name else UTC
    except Exception:
        return UTC


# --------------------------------------------------------------------------- the converter
class Converter:
    def __init__(self, src, out, tz=None, hr_bin_minutes=10, split_by_year=True, log=print):
        self.src, self.out = src, out
        self.ref = os.path.join(out, "reference_only")
        self.tz = tz or default_timezone()
        self.hr_bin = max(0, int(hr_bin_minutes))
        self.split = split_by_year
        self._log = log
        self.lines = []          # conversion log
        self.written = []        # (relative path, header, rows)
        self.dropped = collections.Counter()
        self.day_offsets = collections.defaultdict(collections.Counter)
        self.json_index = {}
        for root, _, files in os.walk(os.path.join(src, "jsons")):
            for f in files:
                self.json_index[f] = os.path.join(root, f)

    def note(self, s):
        self._log(s)
        self.lines.append(s)

    # ---- reading
    def table(self, name):
        pat = re.compile(re.escape(name) + r"\.\d+\.csv$")
        paths = [p for p in glob.glob(os.path.join(self.src, f"{name}.*.csv")) if pat.search(os.path.basename(p))]
        if not paths:
            return []
        with open(paths[0], encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        if len(rows) < 2:
            return []
        header = rows[1]
        n = len(header)
        out = []
        for r in rows[2:]:
            if len(r) < n:
                r = r + [""] * (n - len(r))
            out.append(Row(zip(header, r[:n])))
        return out

    def jload(self, name):
        p = self.json_index.get(name or "")
        if not p:
            return None
        try:
            with open(p) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    # ---- time handling
    def learn_offsets(self, rows, tcol, ocol):
        for r in rows:
            t, o = parse_ts(r[tcol]), parse_offset(r[ocol])
            if t and o is not None:
                self.day_offsets[(t + o).date()][o] += 1

    def iso(self, t_utc, offset):
        if t_utc is None:
            return ""
        if offset is None:
            offset = self.tz.utcoffset(t_utc) or dt.timedelta(0)
        return fmt_local(t_utc.astimezone(dt.timezone(offset)))

    def day_bounds(self, day_str):
        d = dt.datetime.strptime(day_str[:10], "%Y-%m-%d").date()
        c = self.day_offsets.get(d)
        off = c.most_common(1)[0][0] if c else (self.tz.utcoffset(dt.datetime(d.year, d.month, d.day, 12)) or dt.timedelta(0))
        tz = dt.timezone(off)
        return (dt.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz),
                dt.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz), tz)

    @staticmethod
    def latest_per_day(rows, daycol, updcol):
        best = {}
        for r in rows:
            k = r[daycol][:10]
            if k not in best or r[updcol] > best[k][updcol]:
                best[k] = r
        return best

    # ---- writing
    def write(self, fname, header, rows, folder=None):
        keep, seen = [], set()
        for r in rows:
            if r[0] < "2000":
                self.dropped[f"{fname} (no timestamp in source)"] += 1
                continue
            if tuple(r) in seen:
                self.dropped[f"{fname} (exact duplicate)"] += 1
                continue
            seen.add(tuple(r))
            keep.append(r)
        keep.sort(key=lambda r: r[0])
        path = os.path.join(folder or self.out, fname)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(keep)
        rel = os.path.relpath(path, self.out)
        self.written.append((rel, header, len(keep)))
        self.note(f"  wrote {rel:34s} {len(keep):>8,} rows")
        return len(keep)

    def write_split(self, prefix, header, rows):
        if not self.split:
            return self.write(f"{prefix}.csv", header, rows)
        by = collections.defaultdict(list)
        for r in rows:
            by[r[0][:4]].append(r)
        return sum(self.write(f"{prefix}_{y}.csv", header, v) for y, v in sorted(by.items()))

    # ---- sections
    def find_combined_device(self):
        for r in self.table("com.samsung.health.device_profile"):
            if (r["model"] or r["name"]).strip().lower() == "combined":
                return r["deviceuuid"]
        for r in self.table("com.samsung.shealth.step_daily_trend"):
            if r["source_type"] == "-2":
                return r["deviceuuid"]
        return None

    def steps_and_distance(self):
        self.note("Steps / distance")
        day = self.table("com.samsung.shealth.tracker.pedometer_day_summary")
        combined = self.find_combined_device()
        if combined:
            best = self.latest_per_day([r for r in day if r["deviceuuid"] == combined], "day_time", "update_time")
        else:
            best = {}
            self.note("  no 'Combined' device found; using the highest single-device total per day")
        for d in {r["day_time"][:10] for r in day} - set(best):
            best[d] = max((r for r in day if r["day_time"][:10] == d), key=lambda r: float(r["step_count"] or 0))
        steps, dist, hourly_days, daily_days = [], [], 0, 0
        for d, r in sorted(best.items()):
            s0, e0, tz = self.day_bounds(d)
            total = int(float(r["step_count"] or 0))
            dtot = float(r["distance"] or 0)
            bins = self.jload(r["binning_data"]) if r["deviceuuid"] == combined else None
            hours = collections.defaultdict(lambda: [0, 0.0])
            if isinstance(bins, list):
                for i, b in enumerate(bins):
                    if not isinstance(b, dict):
                        continue
                    unit = int(b.get("mTimeUnit") or 600000)
                    t = (dt.datetime.fromtimestamp(b["mStartTime"] / 1000, tz) if b.get("mStartTime")
                         else s0 + dt.timedelta(milliseconds=i * unit))
                    h = t.replace(minute=0, second=0, microsecond=0)
                    hours[h][0] += int(b.get("mStepCount") or 0)
                    hours[h][1] += float(b.get("mDistance") or 0)
            if hours and sum(v[0] for v in hours.values()) == total and total > 0:
                hourly_days += 1
                for h, (sc, dm) in sorted(hours.items()):
                    if sc > 0:
                        e = h + dt.timedelta(minutes=59, seconds=59)
                        steps.append([fmt_local(h), fmt_local(e), str(sc)])
                        if dm > 0:
                            dist.append([fmt_local(h), fmt_local(e), num(dm)])
            elif total > 0:
                daily_days += 1
                steps.append([fmt_local(s0), fmt_local(e0), str(total)])
                if dtot > 0:
                    dist.append([fmt_local(s0), fmt_local(e0), num(dtot)])
        self.note(f"  {hourly_days} days written as hourly samples, {daily_days} as one daily total")
        self.write("steps.csv", [H_START, H_END, "steps (count)"], steps)
        self.write("distance_walking_running.csv", [H_START, H_END, "distance (m)"], dist)

    def heart_rate(self):
        self.note("Heart rate")
        P = "com.samsung.health.heart_rate."
        rows = self.table("com.samsung.shealth.tracker.heart_rate")
        self.learn_offsets(rows, P + "start_time", P + "time_offset")
        out, pts_n, spot = [], 0, 0
        bins, bin_off = collections.defaultdict(list), {}
        bin_ms = self.hr_bin * 60000 or 60000
        for r in rows:
            o = parse_offset(r[P + "time_offset"])
            pts = self.jload(r[P + "binning_data"])
            if isinstance(pts, list) and pts:
                for p in pts:
                    if isinstance(p, dict) and p.get("heart_rate") and p["heart_rate"] > 0 and p.get("start_time"):
                        k = p["start_time"] // bin_ms
                        bins[k].append(p)
                        bin_off.setdefault(k, o)
                        pts_n += 1
            else:
                try:
                    v = float(r[P + "heart_rate"])
                except ValueError:
                    continue
                if v > 0:
                    spot += 1
                    s = parse_ts(r[P + "start_time"])
                    out.append([self.iso(s, o), self.iso(parse_ts(r[P + "end_time"]) or s, o), str(round(v))])
        for k, ps in bins.items():
            s = dt.datetime.fromtimestamp(k * bin_ms / 1000, UTC)
            e = dt.datetime.fromtimestamp(max(p.get("end_time") or p["start_time"] for p in ps) / 1000, UTC)
            out.append([self.iso(s, bin_off[k]), self.iso(e, bin_off[k]), str(round(sum(p["heart_rate"] for p in ps) / len(ps)))])
        self.note(f"  {pts_n:,} continuous points -> {len(bins):,} samples of {self.hr_bin or 1} min; {spot} spot readings kept as-is")
        self.write_split("heart_rate", [H_START, H_END, "heart rate (count/min)"], out)

    def hrv(self):
        self.note("Heart rate variability (SDNN)")
        out = []
        for r in self.table("com.samsung.health.hrv"):
            pts = self.jload(r["binning_data"]) or []
            vals = [p["sdnn"] for p in pts if isinstance(p, dict) and p.get("sdnn")]
            if vals:
                o = parse_offset(r["time_offset"])
                out.append([self.iso(parse_ts(r["start_time"]), o), self.iso(parse_ts(r["end_time"]), o), num(sum(vals) / len(vals))])
        self.write("heart_rate_variability.csv", [H_START, H_END, "variability (ms)"], out)

    def sleep(self):
        self.note("Sleep")
        P = "com.samsung.health.sleep."
        sessions = self.table("com.samsung.shealth.sleep")
        self.learn_offsets(sessions, P + "start_time", P + "time_offset")
        stages = collections.defaultdict(list)
        for s in self.table("com.samsung.health.sleep_stage"):
            stages[s["sleep_id"]].append(s)
        out, nostage, unknown = [], 0, collections.Counter()
        for r in sessions:
            o = parse_offset(r[P + "time_offset"])
            s, e = parse_ts(r[P + "start_time"]), parse_ts(r[P + "end_time"])
            if not (s and e) or e <= s:
                continue
            out.append([self.iso(s, o), self.iso(e, o), "in bed"])
            st = stages.get(r[P + "datauuid"])
            if st:
                for g in st:
                    v = SLEEP_STAGE.get(g["stage"])
                    if not v:
                        unknown[g["stage"]] += 1
                        continue
                    go = parse_offset(g["time_offset"])
                    gs, ge = parse_ts(g["start_time"]), parse_ts(g["end_time"])
                    if gs and ge and ge > gs:
                        out.append([self.iso(gs, go if go is not None else o), self.iso(ge, go if go is not None else o), v])
            else:
                nostage += 1
                out.append([self.iso(s, o), self.iso(e, o), "asleep"])
        self.note(f"  {len(sessions)} sessions; {nostage} without stage data written as 'asleep'; unknown stage codes: {dict(unknown) or 'none'}")
        self.write_split("sleep", [H_START, H_END, "sleep"], out)

    def workouts(self):
        self.note("Workouts")
        P = "com.samsung.health.exercise."
        rows = self.table("com.samsung.shealth.exercise")
        self.learn_offsets(rows, P + "start_time", P + "time_offset")
        out, unknown, seen = [], collections.Counter(), collections.Counter()
        for r in rows:
            s, o = parse_ts(r[P + "start_time"]), parse_offset(r[P + "time_offset"])
            if not s:
                continue
            e = parse_ts(r[P + "end_time"])
            if not e and r[P + "duration"]:
                e = s + dt.timedelta(milliseconds=float(r[P + "duration"]))
            if not e or e <= s:
                continue
            try:
                code = int(float(r[P + "exercise_type"]))
            except ValueError:
                code = -1
            act = EXERCISE.get(code)
            if act is None:
                unknown[code] += 1
                act = "other"
            seen[act] += 1
            out.append([self.iso(s, o), self.iso(e, o), act,
                        num(r[P + "calorie"]) if r[P + "calorie"] else "",
                        num(r[P + "distance"]) if r[P + "distance"] else ""])
        self.note(f"  activity types: {dict(seen)}; unmapped Samsung codes written as 'other': {dict(unknown) or 'none'}")
        self.write("workouts.csv", [H_START, H_END, "activity", "energy burned (kcal)", "distance (m)"], out)

    def body_and_vitals(self):
        self.note("Body, vitals, nutrition")
        def point(r, tcol="start_time", ocol="time_offset"):
            return self.iso(parse_ts(r[tcol]), parse_offset(r[ocol]))
        def span(r, scol, ecol, ocol):
            o = parse_offset(r[ocol]); s = parse_ts(r[scol])
            return [self.iso(s, o), self.iso(parse_ts(r[ecol]) or s, o)]

        self.write("weight.csv", [H_START, H_END, "weight (kg)", "body fat (percent)"],
                   [[point(r)] * 2 + [num(r["weight"], 2), num(r["body_fat"]) if r["body_fat"] else ""]
                    for r in self.table("com.samsung.health.weight") if r["weight"]])
        self.write("height.csv", [H_START, H_END, "height (m)"],
                   [[point(r)] * 2 + [num(float(r["height"]) / 100, 3)]
                    for r in self.table("com.samsung.health.height") if r["height"]])
        P = "com.samsung.health.oxygen_saturation."
        self.write("oxygen_saturation.csv", [H_START, H_END, "oxygen (percent)"],
                   [span(r, P + "start_time", P + "end_time", P + "time_offset") + [num(r[P + "spo2"])]
                    for r in self.table("com.samsung.shealth.tracker.oxygen_saturation") if r[P + "spo2"]])
        rr = self.table("com.samsung.health.respiratory_rate")
        outl = sum(1 for r in rr if r["is_outlier"] == "1")
        self.write("respiratory_rate.csv", [H_START, H_END, "respiratory rate (count/min)"],
                   [span(r, "start_time", "end_time", "time_offset") + [num(r["average"])]
                    for r in rr if r["average"] and r["is_outlier"] != "1"])
        if outl:
            self.note(f"  {outl} respiratory-rate rows Samsung flagged as outliers were left out")
        P = "com.samsung.health.blood_pressure."
        self.write("blood_pressure.csv", [H_START, H_END, "systolic (mmHg)", "diastolic (mmHg)"],
                   [[point(r, P + "start_time", P + "time_offset")] * 2
                    + [str(round(float(r[P + "systolic"]))), str(round(float(r[P + "diastolic"])))]
                    for r in self.table("com.samsung.shealth.blood_pressure") if r[P + "systolic"] and r[P + "diastolic"]])
        self.write("water.csv", [H_START, H_END, "water (L)"],
                   [[point(r)] * 2 + [num(float(r["amount"]) / 1000, 3)]
                    for r in self.table("com.samsung.health.water_intake") if r["amount"]])
        self.write("dietary_energy.csv", [H_START, H_END, "energy consumed (kcal)"],
                   [[point(r)] * 2 + [num(r["calorie"])]
                    for r in self.table("com.samsung.health.food_intake") if r["calorie"]])
        floors = self.table("com.samsung.health.floors_climbed")
        self.learn_offsets(floors, "start_time", "time_offset")
        self.write("flights_climbed.csv", [H_START, H_END, "flights (count)"],
                   [span(r, "start_time", "end_time", "time_offset") + [str(round(float(r["floor"])))]
                    for r in floors if r["floor"] and float(r["floor"]) > 0])

    def energy(self):
        P = "com.samsung.shealth.calories_burned."
        cal = self.latest_per_day(self.table("com.samsung.shealth.calories_burned.details"), P + "day_time", P + "update_time")
        act, basal = [], []
        for d, r in cal.items():
            s0, e0, _ = self.day_bounds(d)
            if r[P + "active_calorie"] and float(r[P + "active_calorie"]) > 0:
                act.append([fmt_local(s0), fmt_local(e0), num(r[P + "active_calorie"])])
            if r[P + "rest_calorie"] and float(r[P + "rest_calorie"]) > 0:
                basal.append([fmt_local(s0), fmt_local(e0), num(r[P + "rest_calorie"])])
        self.write("active_energy.csv", [H_START, H_END, "calories (kcal)"], act)
        self.write("basal_energy.csv", [H_START, H_END, "basal energy burned (kcal)"], basal)

    def reference_only(self):
        self.note("Reference-only (no writable Apple Health type)")
        def span(r):
            o = parse_offset(r["time_offset"])
            return [self.iso(parse_ts(r["start_time"]), o), self.iso(parse_ts(r["end_time"]), o)]
        self.write("stress.csv", [H_START, H_END, "samsung stress score (0-100)", "min", "max"],
                   [span(r) + [r["score"], r["min"], r["max"]] for r in self.table("com.samsung.shealth.stress") if r["score"]], self.ref)
        self.write("skin_temperature.csv", [H_START, H_END, "skin temperature (C)", "baseline (C)", "min", "max"],
                   [span(r) + [r["temperature"], r["baseline"], r["min"], r["max"]]
                    for r in self.table("com.samsung.health.skin_temperature") if r["temperature"]], self.ref)

    # ---- validation + manifest
    def validate(self):
        self.note("Validation (independent re-read)")
        problems = 0
        for rel, header, _ in self.written:
            if rel.startswith("reference_only"):
                continue
            with open(os.path.join(self.out, rel), newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            assert rows[0] == header, rel
            seen, prev = set(), ""
            for r in rows[1:]:
                if len(r) != len(header):
                    problems += 1
                    self.note(f"  width problem in {rel}: {r}")
                    continue
                for c in (0, 1):
                    dt.datetime.strptime(r[c], "%Y-%m-%dT%H:%M:%S%z")
                if r[0] < prev:
                    problems += 1
                    self.note(f"  order problem in {rel} at {r[0]}")
                prev = r[0]
                k = (r[0], r[1], r[2] if header[2] in ("sleep", "activity") else header[2])
                if k in seen:
                    problems += 1
                    if problems <= 5:
                        self.note(f"  duplicate key in {rel}: {k}")
                seen.add(k)
        self.note(f"  {len(self.written)} files checked, {problems} duplicate-key/width/order problems")
        for k, v in sorted(self.dropped.items()):
            self.note(f"  dropped {v} row(s) from {k}")
        return problems

    def manifest(self):
        types = {
            "steps": ("Steps", "count"), "distance_walking_running": ("Walking + Running Distance", "m"),
            "heart_rate": ("Heart Rate", "count/min"), "heart_rate_variability": ("Heart Rate Variability (SDNN)", "ms"),
            "sleep": ("Sleep Analysis", "in bed / core / deep / rem / awake / asleep"),
            "workouts": ("Workouts", "activity, kcal, m"), "weight": ("Body Mass + Body Fat %", "kg, percent"),
            "height": ("Height", "m"), "oxygen_saturation": ("Blood Oxygen", "percent"),
            "respiratory_rate": ("Respiratory Rate", "count/min"), "blood_pressure": ("Blood Pressure", "mmHg"),
            "water": ("Water", "L"), "dietary_energy": ("Dietary Energy", "kcal"), "flights_climbed": ("Flights Climbed", "count"),
            "active_energy": ("Active Energy", "kcal"), "basal_energy": ("Resting Energy", "kcal"),
        }
        lines = ["# Apple Health import bundle", "",
                 f"Generated by convert_samsung_to_apple_health.py v{__version__} from `{os.path.basename(os.path.abspath(self.src))}`.",
                 "Every timestamp is ISO 8601 with the original local UTC offset, so Health CSV Importer should not ask for a timezone.", "",
                 "| File | Rows | Apple Health type | Units |", "|---|---:|---|---|"]
        total = 0
        for rel, _, n in self.written:
            if rel.startswith("reference_only"):
                continue
            key = re.sub(r"_\d{4}$", "", os.path.splitext(os.path.basename(rel))[0])
            t = types.get(key, ("", ""))
            lines.append(f"| `{rel}` | {n:,} | {t[0]} | {t[1]} |")
            total += n
        lines += [f"| **Total** | **{total:,}** | | |", "",
                  "Reference-only files (no writable Apple Health equivalent) are in `reference_only/`: " +
                  ", ".join(f"`{os.path.basename(r)}` ({n:,} rows)" for r, _, n in self.written if r.startswith("reference_only")), "",
                  "## Conversion log", "", "```", *self.lines, "```", ""]
        with open(os.path.join(self.out, "MANIFEST.md"), "w") as fh:
            fh.write("\n".join(lines))
        with open(os.path.join(self.out, "IMPORT_STEPS.txt"), "w") as fh:
            fh.write(IMPORT_STEPS)

    def run(self):
        os.makedirs(self.ref, exist_ok=True)
        self.note(f"convert_samsung_to_apple_health v{__version__}: {self.src} -> {self.out} (fallback zone {self.tz})")
        # learn per-day offsets from timestamped tables before daily totals need them
        self.heart_rate()
        self.hrv()
        self.sleep()
        self.workouts()
        self.body_and_vitals()
        self.steps_and_distance()
        self.energy()
        self.reference_only()
        problems = self.validate()
        self.manifest()
        return problems


IMPORT_STEPS = """HOW TO IMPORT (Health CSV Importer, iPhone)

1. Install "Health CSV Importer" by Lionheart Software from the App Store (free download; its Pro tier is
   needed for everything except weight).
2. Put this folder where the iPhone can reach it: iCloud Drive, AirDrop, or any Files location.
3. In Health CSV Importer: Import -> Browse -> pick a file. Headers carry the type and unit
   (e.g. "heart rate (count/min)"), so the column mapping is detected; confirm it.
   Timestamps include the UTC offset, so no timezone prompt should appear.
4. Suggested order, small first: weight -> blood_pressure, water, dietary_energy -> workouts -> flights_climbed
   -> active_energy, basal_energy -> steps, distance_walking_running -> heart_rate_variability, oxygen_saturation,
   respiratory_rate -> sleep_<year> -> heart_rate_<year> (largest; allow a minute or two each).
5. Check height.csv before importing it: Apple Health treats the latest sample as your current height.
6. The importer skips rows it has already imported, so re-running a file is safe.
7. Verify in Apple Health: Browse -> Activity -> Steps -> Y, and the Highlights year-over-year comparison.
   Imported entries show "CSV Import" as their source under Data Sources & Access.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert a Samsung Health data export into CSVs for Health CSV Importer (Apple Health).")
    ap.add_argument("export_dir", help="unzipped Samsung Health export folder (contains com.samsung.*.csv and jsons/)")
    ap.add_argument("-o", "--output", default=None, help="output folder (default: ./apple_health_import)")
    ap.add_argument("--timezone", default=None, help="IANA zone used only for days with no timestamped samples (default: this machine's zone)")
    ap.add_argument("--heart-rate-bin", type=int, default=10, metavar="MINUTES",
                    help="average continuous heart rate into bins of this many minutes (0 = keep every minute; default 10)")
    ap.add_argument("--no-split", action="store_true", help="do not split heart rate and sleep files by year")
    ap.add_argument("--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    src = os.path.abspath(a.export_dir)
    if not glob.glob(os.path.join(src, "com.samsung.*.csv")):
        ap.error(f"no com.samsung.*.csv files in {src}; point at the unzipped export folder")
    out = os.path.abspath(a.output or "apple_health_import")
    tz = ZoneInfo(a.timezone) if a.timezone else None
    problems = Converter(src, out, tz=tz, hr_bin_minutes=a.heart_rate_bin, split_by_year=not a.no_split).run()
    print(f"\nDone. Files in {out}; see MANIFEST.md and IMPORT_STEPS.txt there.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
