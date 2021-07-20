import csv
import gpxpy
from gpxpy.geo import get_course, distance, Location, LocationDelta
from datetime import datetime
import argparse
import sys, os
import logging
import pprint
import json
import re
from simplify import Simplify3D

RE_INT = re.compile(r"^[-+]?([1-9]\d*|0)$")
RE_FLOAT = re.compile(r"^[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?$")

skipme = ["seconds_elapsed", "sensor"]
untouchables = ["Metadata"]

highestQuality = True
url = "https://github.com/mhaberler/sensorlogger"


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
        (lat, lon, ele, dt) = p
        pt = gpxpy.gpx.GPXTrackPoint(lon, lat, elevation=ele, time=dt)
        gpx_segment.points.append(pt)

    gpx.refresh_bounds()
    metadata = j["Metadata"]
    gpx.creator = f"Sensor Logger, app version {metadata['appVersion']}"
    gpx.author_name = f"{metadata['device name']}, {metadata['platform']}, recorded {metadata['recording time']}"
    gpx.description = " ".join(sys.argv)
    gpx_track.name = gpx_fn

    xml = gpx.to_xml(version="1.0")
    with open(gpx_fn, "w") as f:
        f.write(xml)
    logging.debug(
        f"writing {gpx_fn}: retained samples: {len(pts)}, invalid samples={invalid}"
    )


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

    result = {}
    for filename in args.files:
        with open(filename, "rb") as fp:
            s = fp.read()
            js = json.loads(s)
            for j in js:
                sensor = j["sensor"]
                if not sensor in result:
                    result[sensor] = []
                c = prepare(j)
                if sensor == "Metadata":
                    result[sensor] = c
                else:
                    result[sensor].append(c)
            # pprint.pprint(result)
        if args.gpx:
            gpx_fn = os.path.splitext(filename)[0] + ".gpx"
            gen_gpx(args, gpx_fn, result)


if __name__ == "__main__":
    main()
