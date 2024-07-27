from math import floor
import os
from functools import cache
import fiona
from pathlib import Path
import logging
from datetime import datetime, UTC, timedelta
import argparse
import numpy as np
import piexif


# precision for storing decimal seconds
# i.e. 3283746 / PRECISION = 32.83...
PRECISION = 10000


def parse_gpx(gpx_path: Path) -> tuple[tuple, list]:
    """
    Parse a GPX file and return a tuple of times and coordinate arrays.
    Note that GPX times are encoded UTC but most cameras are typically set to user's local timezone.

    Parameters
    ----------
    gpx_path
        Path to the GPX file.
    Returns
    -------
    tuple[tuple, list]
        First item in the tuple is the array of times while the second
        is the array of coordinates (lon, lat).
    """
    if not gpx_path.exists():
        logging.info(f"Unable to find input GPX file: {gpx_path.absolute()}.")
        return tuple(), list()
    layers = fiona.listlayers(gpx_path)
    if "track_points" not in layers:
        logging.info(f"GPX file does not contain a `track_points` layer. Available layers: {' | '.join(layers)}.")
        return tuple(), list()
    with fiona.open(gpx_path, layer="track_points") as points:
        times, coords = list(), list()
        for point in points:
            props = point.properties
            times.append(datetime.strptime(props.get("time"), "%Y-%m-%dT%H:%M:%S%z").timestamp())
            coords.append((props.get("ele"),) + point.geometry.coordinates)
    return tuple(times), coords


def arg_parser() -> argparse.Namespace:
    """
    Typical argument parser for inputs. The mutually exclusive group is meant to address
    the occasional times when you travel to a different time zone or the camera clock drifted.
    It's happened to me, so I added the option.
    Still deciding if the photo's original datetime should be modified as well in the EXIF ;).

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("gpx", help="GPX file name to use as a geocoder.")
    parser.add_argument("images", help="Directory of image files to be geocoded.")
    parser.add_argument("ext", help="Image file format/extension, e.g. JPG|WEBP|TIF")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--hours", type=int, default=0, help="Camera datetime offset in hours")
    group.add_argument("--minutes", type=int, default=0, help="Camera datetime offset in minutes")
    group.add_argument("--seconds", type=int, default=0, help="Camera datetime offset in seconds")
    args = parser.parse_args()
    return args


def get_pattern(ext: str) -> str:
    """
    Get the glob pattern to match only piexif supported files.

    Parameters
    ----------
    ext
        Image format extension, one of JPG|WEBP|TIF

    Returns
    -------
    str
        Pattern to be fed into glob.
    """
    if ext.lower() in ["jpg", "jpeg"]:
        return "*.[jpJP]*"
    elif ext.lower() == "webp":
        return "*.[webWEB]*"
    elif ext.lower() in ("tif", "tiff"):
        return "*.[tifTIF]*"
    else:
        raise ValueError("Piexif supports only JPG|WEBP|TIF.")


@cache
def nearest_gpx_point(times: tuple, photo_time: float) -> int:
    """
    Determine the nearest timestamp from the GPX points and return the index.
    Parameters
    ----------
    times
        Array of GPX points times.
    photo_time
        EXIF DateTimeOriginal timestamp.

    Returns
    -------
    int
        Returns the index of the nearest GPX point.
    """
    times = np.asarray(times)
    i = np.searchsorted(times, photo_time)
    if photo_time == times[i] or photo_time >= times[i-1:i+1].mean():
        return i
    else:
        return i - 1


def to_degrees_minutes_seconds(dec: float, lon: bool) -> tuple[int, int, int, str]:
    """
    Convert decimal lon/lat to degrees/minutes/seconds and the hemisphere label.

    Parameters
    ----------
    dec
        Decimal value of lon/lat.
    lon
        Boolean flag to determine which hemisphere to consider, E/W or N/S.

    Returns
    -------
    tuple
        (degrees, minutes, seconds, hemisphere)
    """
    ref = "N"
    if dec < 0 and lon:
        ref = "W"
    elif dec < 0 and not lon:
        ref = "S"
    elif lon:
        ref = "E"
    dec = abs(dec)
    degrees = int(floor(dec))
    minutes = int(((dec % degrees) * 3600) // 60)
    seconds = int(floor(((dec % degrees) * 3600) % 60 * PRECISION))
    return degrees, minutes, seconds, ref


def build_gps_dict(elev: float, lon_dms: tuple, lat_dms: tuple) -> dict:
    """
    Build a GPS dictionary to be inserted in the EXIF.

    Parameters
    ----------
    elev
        Elevation in meters above mean sea level
    lon_dms
        Longitude tuple of DMS
    lat_dms
        Latitude tuple of DMS

    Returns
    -------
    dict
        Piexif encoded key-value dict.
    """
    gps = {
        piexif.GPSIFD.GPSLongitude: [(lon_dms[0], 1), (lon_dms[1], 1), (lon_dms[2], PRECISION)],
        piexif.GPSIFD.GPSLongitudeRef: lon_dms[3],
        piexif.GPSIFD.GPSLatitude: [(lat_dms[0], 1), (lat_dms[1], 1), (lat_dms[2], PRECISION)],
        piexif.GPSIFD.GPSLatitudeRef: lat_dms[3],
        piexif.GPSIFD.GPSAltitude: [(int(elev), 1)],
        piexif.GPSIFD.GPSAltitudeRef: 0
    }
    return gps


def main():
    args = arg_parser()
    print(args)
    if args.hours != 0:
        offset = args.hours * 3600
    elif args.minutes != 0:
        offset = args.minutes * 60
    else:
        offset = args.seconds
    pattern = get_pattern(args.ext)
    image_dir = Path(os.path.expanduser(args.images))
    if not image_dir.is_dir() and image_dir.is_file():
        images = [image_dir]
        logging.warning("Was expecting a directory of image files, but received a file, will attempt processing this file.")
    else:
        images = image_dir.glob(pattern)
    times, coords = parse_gpx(Path(os.path.expanduser(args.gpx)).absolute())
    for im in images:
        logging.info(im)
        exif = piexif.load(str(im))
        # careful consideration is needed as strptime is TZ naive and will generally default to local environment TZ
        # my camera does not include a TZ or UTC offset in DateTimeOriginal
        taken_at = (datetime.strptime(
            exif["Exif"][piexif.ExifIFD.DateTimeOriginal].decode(),
            "%Y:%m:%d %H:%M:%S"
        ).astimezone(UTC) + timedelta(seconds=offset)).timestamp()
        index = nearest_gpx_point(times, taken_at)
        elev, lon, lat = coords[index]
        lon_dms = to_degrees_minutes_seconds(lon, True)
        lat_dms = to_degrees_minutes_seconds(lat, False)
        exif["GPS"] = build_gps_dict(elev, lon_dms, lat_dms)
        exif_bytes = piexif.dump(exif)
        piexif.insert(exif_bytes, str(im))


if __name__ == "__main__":
    main()