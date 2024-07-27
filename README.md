Geotagger can assign coordinates to photos using a GPX file. In my case, I use a Garmin watch to track my GPS based activity and I download the GPX file from Garmin Connect.

Usage:
```
python3 geocoder.py -h

usage: geocoder.py [-h] [--hours HOURS | --minutes MINUTES | --seconds SECONDS] gpx images ext

positional arguments:
  gpx                GPX file name to use as a geocoder.
  images             Directory of image files to be geocoded.
  ext                Image file format/extension, e.g. JPG|WEBP|TIF

options:
  -h, --help         show this help message and exit
  --hours HOURS      Camera datetime offset in +/- hours
  --minutes MINUTES  Camera datetime offset in +/- minutes
  --seconds SECONDS  Camera datetime offset in +/- seconds
```

The script relies on [piexif](https://pypi.org/project/piexif/) so only JPG|WEBP|TIF are supported.