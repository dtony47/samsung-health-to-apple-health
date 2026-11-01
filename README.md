# Samsung Health → Apple Health

Convert a Samsung Health data export into CSV files that [Health CSV Importer](https://apps.apple.com/app/health-csv-importer/id1275959806) writes straight into Apple Health, with the original timestamps, offsets and totals intact.

Built by **Elaman Group** after moving a Galaxy Watch owner's three and a half years of history onto an iPhone and finding that nothing off the shelf handled the export cleanly. Everything runs on your own computer; no health data leaves it.

## Why this exists

- Apple Health has no import feature, and Samsung Health cannot sync to it.
- Samsung's "Download personal data" export is a folder of sixty-plus CSVs plus tens of thousands of JSON fragments, with timestamps stored in UTC, several revisions of the same day, and a format that drifts between app versions.
- Health CSV Importer is the one iPhone app that reliably writes arbitrary CSVs into Apple Health, but it needs clean, typed input.

This script is the missing middle layer. It was validated end to end on a real export: 161,011 samples written, with step, distance and workout totals matching the source exactly and the year-over-year figures in Apple Health matching the converted files.

## Quick start

Requirements: Python 3.10 or newer, nothing else.

1. On the Android phone: Samsung Health → Settings → **Download personal data**. Unzip the result; you get a folder named like `samsunghealth_<user>_<timestamp>` containing `com.samsung.*.csv` files and a `jsons/` directory.
2. Run the converter:

   ```bash
   python3 convert_samsung_to_apple_health.py /path/to/samsunghealth_user_20260101120000 -o apple_health_import
   ```

3. Read `apple_health_import/MANIFEST.md` (what was produced, the conversion log) and `IMPORT_STEPS.txt` (how to import on the iPhone).
4. Copy the folder to the iPhone (iCloud Drive or AirDrop), install Health CSV Importer, and import the files in the suggested order. Headers already carry the Apple type and unit, so the app maps columns automatically, and timestamps carry their UTC offset so no timezone prompt appears.

Options:

| Flag | Default | Meaning |
|---|---|---|
| `-o, --output DIR` | `./apple_health_import` | Where to write the CSVs |
| `--timezone ZONE` | this machine's zone | IANA zone used only for daily totals on days that have no timestamped samples |
| `--heart-rate-bin N` | `10` | Average continuous heart rate into N-minute samples; `0` keeps every minute |
| `--no-split` | off | Keep heart rate and sleep in one file each instead of one per year |

## What gets converted

| Output file | Apple Health type | Source and notes |
|---|---|---|
| `steps.csv`, `distance_walking_running.csv` | Steps, Walking + Running Distance | Hourly totals rebuilt from the Combined device's 10-minute bins; falls back to one daily total if the bins don't add up |
| `heart_rate_<year>.csv` | Heart Rate | 10-minute averages of Samsung's per-minute continuous data, plus spot readings as recorded |
| `heart_rate_variability.csv` | Heart Rate Variability (SDNN) | Mean SDNN per Samsung window; Apple's HRV metric is SDNN, so RMSSD is not relabelled |
| `sleep_<year>.csv` | Sleep Analysis | Stages mapped Awake/Light→Core/Deep/REM, one In Bed row per session, sessions without stages written as Asleep |
| `workouts.csv` | Workouts | Samsung exercise codes mapped to importer activity names, with energy and distance |
| `weight.csv`, `height.csv` | Body Mass, Body Fat %, Height | |
| `oxygen_saturation.csv`, `respiratory_rate.csv`, `blood_pressure.csv` | Blood Oxygen, Respiratory Rate, Blood Pressure | Respiratory rows Samsung flags as outliers are left out |
| `active_energy.csv`, `basal_energy.csv` | Active Energy, Resting Energy | One total per day, latest revision |
| `flights_climbed.csv`, `water.csv`, `dietary_energy.csv` | Flights Climbed, Water, Dietary Energy | |

Kept as **reference only** (no writable Apple Health type): stress score, skin temperature. Not converted at all: ECG, sleep apnea, sleep scores, snoring, AGEs index, badges, GPS routes and per-workout heart-rate traces.

## How it handles the awkward parts

- **Time.** Samsung stores `start_time`/`end_time` in UTC and the local offset in `time_offset` (`UTC+0100`, `UTC-0500` while travelling). Every output timestamp is ISO 8601 in that original offset, never today's timezone. Daily totals borrow the offset most of that day's timestamped samples used.
- **Revisions.** Samsung keeps several versions of a day summary; the one with the latest `update_time` wins. The "Combined" device is detected from `device_profile`, with a fallback to the highest single-device total.
- **Format drift.** Rows shorter or longer than the header, bins with a zero epoch, and tables that share a name prefix (`exercise` vs `exercise.program_summary`) are all handled, because each of these broke an earlier converter.
- **Duplicates.** Overlapping heart-rate rows from two watches are merged per bin; exact duplicate rows are dropped and counted; the importer's own dedup key (start, end, type) is checked before writing.
- **Verification.** Every output file is re-read independently: header, row width, date parsing, chronological order and duplicate keys. The run exits non-zero if anything fails.

Check `height.csv` before importing it. Apple Health treats the most recent height sample as your current height, and Samsung exports sometimes contain mis-entered values.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite builds a small synthetic export (no real data) covering timestamped and zero-epoch step bins, day revisions, heart-rate binning across offsets, sleep stage mapping, unknown codes, outlier filtering, epoch-zero rows and partial exports.

## Contributing

Issues and pull requests are welcome, especially new Samsung tables or export-format changes. Please never attach a real export to an issue; a few anonymised rows and the header lines are enough.

## Licence

MIT, © 2026 Elaman Group. Health CSV Importer is a product of Lionheart Software and is not affiliated with this project.
