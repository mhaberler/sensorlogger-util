import gpxpy
from datetime import datetime
import argparse
import sys, os
import logging
import pprint
import json
import re
import zipfile
import csv
import codecs

from simplify import Simplify3D

RE_INT = re.compile(r"^[-+]?([1-9]\d*|0)$")
RE_FLOAT = re.compile(r"^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$")

skipme = ["seconds_elapsed", "sensor"]
untouchables = ["Metadata"]

highestQuality = True


def prepare(j):
    cleaned = {}
    for k, v in j.items():

        if k in skipme:
            continue

        if k in untouchables:
            return j

        if k == "time":
            ns = float(v[10:])
            secs = float(v[0:-9]) + ns * 1e-9
            cleaned[k] = secs
            continue

        if RE_INT.match(v):
            cleaned[k] = int(v)
            continue

        if RE_FLOAT.match(v):
            cleaned[k] = float(v)
            continue

        cleaned[k] = v
    return cleaned


def gen_gpx(args, gpx_fn, j):
    invalid = 0
    samples = 0
    gpx = gpxpy.gpx.GPX()

    # Create first track in our GPX:
    gpx_track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(gpx_track)

    # Create first segment in our GPX track:
    gpx_segment = gpxpy.gpx.GPXTrackSegment()
    gpx_track.segments.append(gpx_segment)

    points = []
    for row in j["Location"]:
        points.append(
            [
                row["longitude"],
                row["latitude"],
                row["altitude"],
                datetime.fromtimestamp(row["time"]),
                row["horizontalAccuracy"],
                row["verticalAccuracy"],
                row["speed"],
            ]
        )

    pts = points

    if args.tolerance > 0.0:
        s = Simplify3D()
        pts = s.simplify(
            points,
            tolerance=args.tolerance,
            highestQuality=highestQuality,
            returnMarkers=False,
        )
        logging.debug(
            f"simplify3d: {len(points)} -> {len(pts)} points with {args.tolerance=}"
        )

    for p in pts:
        (lat, lon, ele, dt, hdop, vdop, speed) = p
        pt = gpxpy.gpx.GPXTrackPoint(
            lon,
            lat,
            elevation=ele,
            time=dt,
            speed=speed,
            horizontal_dilution=hdop,
            vertical_dilution=vdop,
        )
        gpx_segment.points.append(pt)

    gpx.refresh_bounds()
    metadata = j["Metadata"]
    gpx.creator = f"Sensor Logger, app version {metadata['appVersion']}"
    gpx.author_name = f"{metadata['device name']}, {metadata['platform']}, recorded {metadata['recording time']}"
    gpx.description = " ".join(sys.argv)
    gpx_track.name = gpx_fn

    xml = gpx.to_xml(version="1.0")
    logging.debug(f"writing {gpx_fn}, invalid samples={invalid}")
    with open(gpx_fn, "w") as f:
        f.write(xml)


def main():
    ap = argparse.ArgumentParser(
        usage="%(prog)s ",
        description="clean a Sensor Logger JSON file, and optionally convert to gpx",
    )
    ap.add_argument("-d", "--debug", action="store_true", help="show detailed logging")
    ap.add_argument(
        "-m",
        "--merge",
        action="store_true",
        help="merge all objects in a single timeline",
    )
    ap.add_argument(
        "-i",
        "--iso",
        action="store_true",
        help="use ISO timestamps (default seconds since epoch)",
    )
    ap.add_argument(
        "-g", "--gpx", action="store_true", help="save GPX file as (basename).gpx"
    )
    ap.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="save reformatted JSON file as (basename)_fmt.json",
    )

    ap.add_argument("files", nargs="*")
    ap.add_argument(
        "--tolerance",
        action="store",
        dest="tolerance",
        default=-1.0,
        type=float,
        help="tolerance value for simplify (see https://github.com/mhaberler/simplify.py)",
    )
    args, extra = ap.parse_known_args()

    level = logging.WARNING
    if args.debug:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(funcName)s:%(lineno)s %(message)s")

    for filename in args.files:
        result = {}

        if filename.endswith(".json"):
            with open(filename, "rb") as fp:
                s = fp.read()
                js = json.loads(s)
                for j in js:
                    sensor = j["sensor"]
                    if not sensor in result:
                        result[sensor] = []
                    c = prepare(j)
                    result[sensor].append(c)
                for k, v in result.items():
                    logging.debug(f"sensor: {k} {len(v)} values")

        if filename.endswith(".zip"):
            try:
                with zipfile.ZipFile(filename) as zf:
                    for info in zf.infolist():
                        try:
                            sensor = info.filename.rsplit(".", 1)[0]
                            reader = csv.DictReader(
                                codecs.iterdecode(zf.open(info.filename, "r"), "utf-8")
                            )
                            rows = list(reader)
                            logging.debug(
                                f"read {filename}:member={info.filename}, {len(rows)} values"
                            )
                            l = [prepare(c) for c in rows]
                            if len(l):
                                result[sensor] = l

                        except KeyError:
                            logging.error(
                                f"zip file {filename}: no such member {info.filename}"
                            )
                            continue
            except zipfile.BadZipFile as e:
                logging.error(f"{filename}: {e}")

        # fixup the Metadata record
        if "Metadata" in result and len(result["Metadata"]) == 1:
            result["Metadata"] = result["Metadata"][0]

        if args.json:
            json_fn = os.path.splitext(filename)[0] + "_reformat.json"
            logging.debug(f"writing {json_fn}")

            with open(json_fn, "w") as f:
                f.write(json.dumps(result, indent=4))

        if args.gpx:
            if not "Location" in result:
                logging.error(
                    f"error: can't create GPX from {filename} - no Location records"
                )
                sys.exit(1)

            gpx_fn = os.path.splitext(filename)[0] + ".gpx"
            gen_gpx(args, gpx_fn, result)


if __name__ == "__main__":
    main()
