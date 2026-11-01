"""Synthetic-export tests. No real health data is used: every table below is invented."""
import csv
import datetime as dt
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("conv", ROOT / "convert_samsung_to_apple_health.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

UTC = dt.timezone.utc


def ms(y, mo, d, h=0, mi=0, s=0):
    return int(dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC).timestamp() * 1000)


def write_table(folder, name, cols, rows):
    """Mimic Samsung's layout: BOM, a metadata first line, the header, then rows with a trailing comma."""
    path = folder / f"{name}.20260101000000.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write("﻿" + f"{name},7010053,{len(cols)}\n")
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(list(r) + [""])


def write_json(folder, table, name, obj):
    p = folder / "jsons" / table / "0"
    p.mkdir(parents=True, exist_ok=True)
    with open(p / name, "w") as fh:
        json.dump(obj, fh)


def build_export(folder):
    HR = "com.samsung.health.heart_rate."
    SL = "com.samsung.health.sleep."
    EX = "com.samsung.health.exercise."
    OX = "com.samsung.health.oxygen_saturation."
    BP = "com.samsung.health.blood_pressure."
    CB = "com.samsung.shealth.calories_burned."

    write_table(folder, "com.samsung.health.device_profile",
                ["deviceuuid", "name", "model", "manufacturer", "fixed_name"],
                [("COMB", "Combined", "Combined", "Combined", ""), ("WATCH", "Galaxy Watch", "SM-R860", "Samsung", "")])

    # --- steps: day A (BST) with timestamped bins, day B (GMT) with zero-epoch bins, day C with bins that do not add up
    bins_a = [{"mStartTime": ms(2025, 6, 9, 23) + i * 600000, "mStepCount": 0, "mDistance": 0.0, "mTimeUnit": 600000} for i in range(144)]
    bins_a[48].update(mStepCount=300, mDistance=200.0)   # 08:00 local
    bins_a[49].update(mStepCount=200, mDistance=150.0)   # 08:10 local -> same hour
    bins_a[90].update(mStepCount=1000, mDistance=800.0)  # 15:00 local
    bins_b = [{"mStartTime": 0, "mStepCount": 0, "mDistance": 0.0, "mTimeUnit": 600000} for _ in range(144)]
    bins_b[60]["mStepCount"] = 700                        # index 60 -> 10:00 local
    bins_c = [{"mStartTime": ms(2025, 3, 1) + i * 600000, "mStepCount": 0, "mDistance": 0.0, "mTimeUnit": 600000} for i in range(144)]
    bins_c[10]["mStepCount"] = 10                          # does not match the 50-step total -> daily row
    write_json(folder, "com.samsung.shealth.tracker.pedometer_day_summary", "A.binning_data.json", bins_a)
    write_json(folder, "com.samsung.shealth.tracker.pedometer_day_summary", "B.binning_data.json", bins_b)
    write_json(folder, "com.samsung.shealth.tracker.pedometer_day_summary", "C.binning_data.json", bins_c)
    write_table(folder, "com.samsung.shealth.tracker.pedometer_day_summary",
                ["step_count", "binning_data", "update_time", "deviceuuid", "distance", "datauuid", "day_time"],
                [("1500", "A.binning_data.json", "2025-06-10 23:00:00.000", "COMB", "1150.0", "A", "2025-06-10 00:00:00.000"),
                 ("100", "A.binning_data.json", "2025-06-10 08:30:00.000", "COMB", "70.0", "A0", "2025-06-10 00:00:00.000"),  # older revision
                 ("1400", "", "2025-06-10 23:00:00.000", "WATCH", "1000.0", "A1", "2025-06-10 00:00:00.000"),
                 ("700", "B.binning_data.json", "2025-01-20 23:00:00.000", "COMB", "500.0", "B", "2025-01-20 00:00:00.000"),
                 ("50", "C.binning_data.json", "2025-03-01 23:00:00.000", "COMB", "40.0", "C", "2025-03-01 00:00:00.000")])

    # --- heart rate: one continuous row with a binning file, one spot reading
    pts = [{"heart_rate": v, "start_time": ms(2025, 6, 10, 7) + i * 60000, "end_time": ms(2025, 6, 10, 7) + i * 60000 + 59000}
           for i, v in enumerate((60.0, 62.0, 64.0))]
    pts.append({"heart_rate": 80.0, "start_time": ms(2025, 6, 10, 7, 15), "end_time": ms(2025, 6, 10, 7, 15) + 59000})
    write_json(folder, "com.samsung.shealth.tracker.heart_rate", "HR1.binning_data.json", pts)
    write_table(folder, "com.samsung.shealth.tracker.heart_rate",
                [HR + "start_time", HR + "end_time", HR + "time_offset", HR + "binning_data", HR + "heart_rate", HR + "heart_beat_count"],
                [("2025-06-10 07:00:00.000", "2025-06-10 08:00:00.000", "UTC+0100", "HR1.binning_data.json", "66.0", "1"),
                 ("2025-01-20 10:30:00.000", "2025-01-20 10:30:00.000", "UTC+0000", "", "55.0", "1")])

    write_json(folder, "com.samsung.health.hrv", "V1.binning_data.json", [{"sdnn": 40.0, "rmssd": 30.0}, {"sdnn": 60.0, "rmssd": 31.0}])
    write_table(folder, "com.samsung.health.hrv", ["start_time", "binning_data", "time_offset", "end_time", "datauuid"],
                [("2025-06-10 01:00:00.000", "V1.binning_data.json", "UTC+0100", "2025-06-10 02:00:00.000", "V1"),
                 ("1970-01-01 00:00:00.000", "V1.binning_data.json", "UTC+0000", "1970-01-01 01:00:00.000", "V0")])

    write_table(folder, "com.samsung.shealth.sleep",
                [SL + "start_time", SL + "end_time", SL + "time_offset", SL + "datauuid", "has_sleep_data", "sleep_type"],
                [("2025-06-09 22:00:00.000", "2025-06-10 06:00:00.000", "UTC+0100", "S1", "0", "-1"),
                 ("2025-01-19 23:00:00.000", "2025-01-20 07:00:00.000", "UTC+0000", "S2", "0", "")])
    write_table(folder, "com.samsung.health.sleep_stage", ["start_time", "sleep_id", "stage", "time_offset", "end_time", "datauuid"],
                [("2025-06-09 22:00:00.000", "S1", "40001", "UTC+0100", "2025-06-09 22:30:00.000", "g1"),
                 ("2025-06-09 22:30:00.000", "S1", "40002", "UTC+0100", "2025-06-10 00:00:00.000", "g2"),
                 ("2025-06-10 00:00:00.000", "S1", "40003", "UTC+0100", "2025-06-10 01:00:00.000", "g3"),
                 ("2025-06-10 01:00:00.000", "S1", "40004", "UTC+0100", "2025-06-10 01:30:00.000", "g4"),
                 ("2025-06-10 01:30:00.000", "S1", "40009", "UTC+0100", "2025-06-10 02:00:00.000", "g5")])  # unknown code

    write_table(folder, "com.samsung.shealth.exercise",
                [EX + "start_time", EX + "end_time", EX + "exercise_type", EX + "calorie", EX + "distance", EX + "duration", EX + "time_offset", "title"],
                [("2025-06-10 12:00:00.000", "2025-06-10 12:30:00.000", "1001", "100.0", "2000.0", "1800000", "UTC+0100", ""),
                 ("2025-06-11 12:00:00.000", "", "99999", "50.0", "", "1800000", "UTC+0100", "")])
    # these tables share a sibling with a longer name; make sure exact-name matching holds
    write_table(folder, "com.samsung.shealth.exercise.program_summary", ["foo"], [("bar",)])

    write_table(folder, "com.samsung.health.weight", ["start_time", "weight", "body_fat", "time_offset"], [("2025-06-10 06:30:00.000", "70.5", "20.1", "UTC+0100")])
    write_table(folder, "com.samsung.health.height", ["start_time", "height", "time_offset"], [("2025-06-10 06:30:00.000", "175.0", "UTC+0100")])
    write_table(folder, "com.samsung.shealth.tracker.oxygen_saturation", [OX + "start_time", OX + "end_time", OX + "time_offset", OX + "spo2"],
                [("2025-06-09 23:00:00.000", "2025-06-10 05:00:00.000", "UTC+0100", "96.0")])
    write_table(folder, "com.samsung.health.respiratory_rate", ["start_time", "end_time", "time_offset", "average", "is_outlier"],
                [("2025-06-09 23:00:00.000", "2025-06-10 05:00:00.000", "UTC+0100", "14.5", "0"),
                 ("2025-06-10 23:00:00.000", "2025-06-11 05:00:00.000", "UTC+0100", "40.0", "1")])
    write_table(folder, "com.samsung.shealth.blood_pressure", [BP + "start_time", BP + "time_offset", BP + "systolic", BP + "diastolic"],
                [("2025-06-10 09:00:00.000", "UTC+0100", "120.0", "80.0")])
    write_table(folder, "com.samsung.health.water_intake", ["start_time", "amount", "time_offset"], [("2025-06-10 09:00:00.000", "250.0", "UTC+0100")])
    write_table(folder, "com.samsung.health.food_intake", ["start_time", "calorie", "time_offset"], [("2025-06-10 12:45:00.000", "500.0", "UTC+0100")])
    write_table(folder, "com.samsung.health.floors_climbed", ["start_time", "end_time", "floor", "time_offset"],
                [("2025-06-10 10:00:00.000", "2025-06-10 10:00:20.000", "2.0", "UTC+0100")])
    write_table(folder, "com.samsung.shealth.calories_burned.details",
                [CB + "day_time", CB + "update_time", CB + "active_calorie", CB + "rest_calorie", CB + "deviceuuid"],
                [("2025-06-10 00:00:00.000", "2025-06-10 23:00:00.000", "300.0", "1500.0", "PHONE"),
                 ("2025-06-10 00:00:00.000", "2025-06-10 08:00:00.000", "10.0", "1500.0", "PHONE")])
    write_table(folder, "com.samsung.shealth.stress", ["start_time", "end_time", "time_offset", "score", "min", "max"],
                [("2025-06-10 10:00:00.000", "2025-06-10 10:59:59.000", "UTC+0100", "40.0", "0.0", "100.0")])
    write_table(folder, "com.samsung.health.skin_temperature", ["start_time", "end_time", "time_offset", "temperature", "baseline", "min", "max"],
                [("2025-06-09 23:00:00.000", "2025-06-10 05:00:00.000", "UTC+0100", "34.5", "34.6", "33.0", "35.0")])


def read(out, name):
    with open(os.path.join(out, name), newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.src = pathlib.Path(cls.tmp.name) / "export"
        cls.src.mkdir()
        build_export(cls.src)
        cls.out = os.path.join(cls.tmp.name, "out")
        cls.problems = conv.Converter(str(cls.src), cls.out, tz=ZoneInfo("Europe/London"), log=lambda s: None).run()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_validation_clean(self):
        self.assertEqual(self.problems, 0)

    def test_steps_hourly_from_latest_combined_revision(self):
        rows = read(self.out, "steps.csv")
        self.assertEqual(rows[0], ["start datetime", "end datetime", "steps (count)"])
        self.assertEqual(rows[1:], [
            ["2025-01-20T10:00:00+00:00", "2025-01-20T10:59:59+00:00", "700"],   # zero-epoch bins placed by index
            ["2025-03-01T00:00:00+00:00", "2025-03-01T23:59:59+00:00", "50"],    # bins did not add up -> daily total
            ["2025-06-10T08:00:00+01:00", "2025-06-10T08:59:59+01:00", "500"],   # two 10-min bins summed into the hour
            ["2025-06-10T15:00:00+01:00", "2025-06-10T15:59:59+01:00", "1000"],
        ])
        dist = read(self.out, "distance_walking_running.csv")[1:]
        self.assertEqual([r[2] for r in dist], ["40.0", "350.0", "800.0"])

    def test_heart_rate_bins_and_offsets(self):
        rows = read(self.out, "heart_rate_2025.csv")[1:]
        self.assertEqual(rows, [
            ["2025-01-20T10:30:00+00:00", "2025-01-20T10:30:00+00:00", "55"],
            ["2025-06-10T08:00:00+01:00", "2025-06-10T08:02:59+01:00", "62"],
            ["2025-06-10T08:10:00+01:00", "2025-06-10T08:15:59+01:00", "80"],
        ])
        self.assertFalse(os.path.exists(os.path.join(self.out, "heart_rate.csv")))

    def test_hrv_mean_sdnn_and_epoch_zero_dropped(self):
        rows = read(self.out, "heart_rate_variability.csv")[1:]
        self.assertEqual(rows, [["2025-06-10T02:00:00+01:00", "2025-06-10T03:00:00+01:00", "50.0"]])

    def test_sleep_stages_in_bed_and_asleep_fallback(self):
        rows = read(self.out, "sleep_2025.csv")[1:]
        self.assertEqual([r[2] for r in rows], ["in bed", "asleep", "in bed", "awake", "core", "deep", "rem"])
        self.assertEqual(rows[2][:2], ["2025-06-09T23:00:00+01:00", "2025-06-10T07:00:00+01:00"])

    def test_workouts_mapping_and_duration_fallback(self):
        rows = read(self.out, "workouts.csv")[1:]
        self.assertEqual(rows[0], ["2025-06-10T13:00:00+01:00", "2025-06-10T13:30:00+01:00", "walking", "100.0", "2000.0"])
        self.assertEqual(rows[1], ["2025-06-11T13:00:00+01:00", "2025-06-11T13:30:00+01:00", "other", "50.0", ""])

    def test_body_vitals_nutrition(self):
        self.assertEqual(read(self.out, "weight.csv")[1], ["2025-06-10T07:30:00+01:00", "2025-06-10T07:30:00+01:00", "70.50", "20.1"])
        self.assertEqual(read(self.out, "height.csv")[1][2], "1.750")
        self.assertEqual(read(self.out, "oxygen_saturation.csv")[1][2], "96.0")
        self.assertEqual(len(read(self.out, "respiratory_rate.csv")), 2)   # outlier excluded
        self.assertEqual(read(self.out, "blood_pressure.csv")[1][2:], ["120", "80"])
        self.assertEqual(read(self.out, "water.csv")[1][2], "0.250")
        self.assertEqual(read(self.out, "dietary_energy.csv")[1][2], "500.0")
        self.assertEqual(read(self.out, "flights_climbed.csv")[1][2], "2")

    def test_energy_uses_latest_revision(self):
        self.assertEqual(read(self.out, "active_energy.csv")[1], ["2025-06-10T00:00:00+01:00", "2025-06-10T23:59:59+01:00", "300.0"])
        self.assertEqual(read(self.out, "basal_energy.csv")[1][2], "1500.0")

    def test_reference_only_and_manifest(self):
        self.assertEqual(len(read(self.out, "reference_only/stress.csv")), 2)
        self.assertTrue(os.path.exists(os.path.join(self.out, "MANIFEST.md")))
        self.assertTrue(os.path.exists(os.path.join(self.out, "IMPORT_STEPS.txt")))
        for name in os.listdir(self.out):
            if name.endswith(".csv"):
                for r in read(self.out, name)[1:]:
                    self.assertFalse(r[0].startswith("1970"), name)
                    dt.datetime.strptime(r[0], "%Y-%m-%dT%H:%M:%S%z")

    def test_partial_export_is_tolerated(self):
        with tempfile.TemporaryDirectory() as t:
            src = pathlib.Path(t) / "export"
            src.mkdir()
            write_table(src, "com.samsung.health.weight", ["start_time", "weight", "time_offset"], [("2025-06-10 06:30:00.000", "70.0", "UTC+0100")])
            out = os.path.join(t, "out")
            self.assertEqual(conv.Converter(str(src), out, tz=UTC, log=lambda s: None).run(), 0)
            self.assertEqual(len(read(out, "weight.csv")), 2)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as t:
            rc = conv.main([str(self.src), "-o", os.path.join(t, "o"), "--timezone", "Europe/London", "--no-split", "--heart-rate-bin", "0"])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(os.path.join(t, "o", "heart_rate.csv")))
            self.assertEqual(len(read(os.path.join(t, "o"), "heart_rate.csv")), 6)   # 4 per-minute points + 1 spot + header


if __name__ == "__main__":
    unittest.main()
