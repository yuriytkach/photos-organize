#!/usr/bin/python3

"""Organize Photos

Inspect directory and organize photos and videos
"""

import sys
import argparse
import os
import time
from time import strftime
import shutil
from tqdm import tqdm
from PIL import Image
from PIL import ExifTags
from datetime import datetime
from os.path import isfile, join
from geopy.geocoders import Nominatim


class CustomFormatter(argparse.RawDescriptionHelpFormatter,
                      argparse.ArgumentDefaultsHelpFormatter):
    pass


cache_loc = {}


class FileInfo:
    def __init__(self, full_path):
        self.full_path = full_path
        self.name = os.path.basename(full_path)

        self.errors = []

        rez, err = self.extract_exif()
        if err:
            self.errors.append(err)
        self.exif = rez

        rez, err = self.extract_date_from_exif()
        if err:
            self.errors.append(err)
        self.exif_mod_date = rez

        rez, err = self.extract_file_datetime()
        if err:
            self.errors.append(err)
        self.file_mod_date = rez

        if self.exif:
            rez, err = extract_location_from_exif(self.exif)
            if err:
                self.errors.append(err)
            self.location = rez
        else:
            self.location = None

    def has_errors(self):
        return len(self.errors) > 0

    def get_mod_date(self):
        return self.exif_mod_date if self.exif_mod_date else self.file_mod_date

    def format_mod_date(self):
        return self.get_mod_date().strftime("%Y-%m-%d") if self.get_mod_date() else "None"

    def is_processable(self):
        return self.get_mod_date() is not None

    def extract_exif(self):
        if self.full_path.lower().endswith(('.jpg', '.jpeg')):
            try:
                img = Image.open(self.full_path)
            except Exception as err:
                return None, err
            else:
                return {
                    ExifTags.TAGS[k]: v
                    for k, v in img._getexif().items()
                    if k in ExifTags.TAGS
                }, None
        else:
            return None, None

    def extract_file_datetime(self):
        try:
            stat = os.stat(self.full_path)
        except Exception as err:
            return None, err
        else:
            tt = stat.st_mtime
            return datetime.fromtimestamp(tt), None

    def extract_date_from_exif(self):
        if self.exif and "DateTime" in self.exif:
            try:
                return datetime.strptime(self.exif["DateTime"], '%Y:%m:%d %H:%M:%S'), None
            except Exception as err:
                return None, err
        else:
            return None, None

    def get_location_place(self):
        if self.location:
            addr = self.location.raw["address"]

            place = find_place(addr, ["theme_park", "museum", "beach", "suburb"])

            city_places = ["village", "town", "city"]
            if "suburb" in addr and place != addr["suburb"]:
                city_places.insert(0, "suburb")

            city = find_place(addr, city_places)

            if not place and not city:
                return self.location.address
            else:
                if city:
                    city_str = city + '-' if place else city
                else:
                    city_str = ''
                place_str = place if place else ''

                loc = f"{city_str}{place_str}".replace("/", "-").replace(".", "-").replace(":", "-")
                return loc
        else:
            return "Unknown"


def parse_args(args):
    """Parse arguments."""
    parser = argparse.ArgumentParser(
        description=sys.modules[__name__].__doc__,
        formatter_class=CustomFormatter)

    g = parser.add_argument_group("photos settings")

    g.add_argument("-d", "--dir",
                   action="store",
                   required=True,
                   help="Directory to scan")

    g.add_argument("-f", "--force", "--no-confirmation",
                   action="store_true",
                   default=True,
                   help="Perform files movement without confirmation")

    g.add_argument("--dry-run",
                   action="store_true",
                   help="Perform dry run without changes")

    return parser.parse_args(args)


def retrieve_file_info(directory, options):
    only_files = [f for f in os.listdir(directory) if isfile(join(directory, f))]
    files = []
    for file in tqdm(only_files):
        file_info = FileInfo(join(directory, file))
        files.append(file_info)

    print(f"Processed files: {len(files)}")
    with_errors = list(filter(lambda f: f.has_errors(), files))
    print(f"With errors: {len(with_errors)}")
    for file_info in with_errors:
        print(f"{file_info.name} - {file_info.errors}")

    processable = list(filter(lambda f: f.is_processable(), files))

    fixed = fix_locations(processable)

    print(f"Fixed processable files: {len(fixed)}")
    if options.force or confirm():
        move_files(fixed, directory, options)


def fix_locations(processable):
    processable.sort(key=lambda f: f.get_mod_date())

    for i, f in enumerate(processable):
        if not f.location:
            try:
                find_location_around(processable, i)
            except Exception as err:
                print(f"Error on {i}: {err}")

    return processable


def find_location_around(files, i):
    if i > 0:
        before_datetime = files[i-1].get_mod_date()
        loc = files[i-1].location
        diff = files[i].get_mod_date() - before_datetime
        check_and_update_location(diff, files, i, loc)

    if not files[i].location and i < len(files)-1:
        after_datetime, loc = find_next_with_loc(files, i+1)
        if after_datetime:
            diff = after_datetime - files[i].get_mod_date()
            check_and_update_location(diff, files, i, loc)


def find_next_with_loc(files, start):
    for x in range(start, len(files)):
        if files[x].location:
            return files[x].get_mod_date(), files[x].location
    return None, None


def check_and_update_location(diff, files, i, loc):
    mins = divmod(diff.total_seconds(), 60)[0]
    if mins < 30:
        files[i].location = loc


def move_files(files, directory, options):
    groups = {}
    for f in files:
        f_date = f.format_mod_date()
        if f_date not in groups:
            groups[f_date] = {}

        f_loc = f.get_location_place()
        if f_loc not in groups[f_date]:
            groups[f_date][f_loc] = []

        groups[f_date][f_loc].append(f)

    if options.dry_run:
        print("Dry run, so no movements are done")

    for key_date in tqdm(groups):
        sub_dir_date = join(directory, key_date)

        if not options.dry_run and not os.path.exists(sub_dir_date):
            os.mkdir(sub_dir_date)

        for key_loc in tqdm(groups[key_date], leave=False):
            sub_dir_loc = join(sub_dir_date, key_loc)

            if not options.dry_run and not os.path.exists(sub_dir_loc):
                os.mkdir(sub_dir_loc)

            for f in tqdm(groups[key_date][key_loc], leave=False):
                if not options.dry_run:
                    shutil.move(f.full_path, join(sub_dir_loc, f.name))


def confirm():
    """
    Ask user to enter Y or N (case-insensitive).
    :return: True if the answer is Y.
    :rtype: bool
    """
    answer = ""
    while answer not in ["y", "n"]:
        answer = input("Do you want to continue [Y/N]? ").lower()
    return answer == "y"


def save_cache_location(coords, location):
    key = create_cache_loc_key(coords)
    cache_loc[key] = location


def find_cache_location(coords):
    key = create_cache_loc_key(coords)
    return cache_loc[key] if key in cache_loc else None


def create_cache_loc_key(coords):
    lat = round(coords["lat"], 2)
    lon = round(coords["lon"], 2)
    key = f"{lat}-{lon}"
    return key


def extract_location_from_exif(exif):
    geotags = get_geotagging(exif)
    if geotags:
        try:
            coords = get_coordinates(geotags)
            if coords["lat"] and coords["lon"]:
                cached_location = find_cache_location(coords)
                if cached_location:
                    return cached_location, None
                else:
                    location = find_geo_location(coords)
                    save_cache_location(coords, location)
                    return location, None
            else:
                return None, None
        except Exception as err:
            return None, err
    else:
        return None, None


def find_geo_location(coords):
    geolocator = Nominatim(user_agent="PhotoGeo")
    location = geolocator.reverse(f"{coords['lat']}, {coords['lon']}")
    time.sleep(1)
    return location


def find_place(addr, place_names):
    for p in place_names:
        if p in addr:
            return addr[p]
    return None


def get_decimal_from_dms(dms, ref):
    degrees = dms[0][0] / dms[0][1]
    minutes = dms[1][0] / dms[1][1] / 60.0
    seconds = dms[2][0] / dms[2][1] / 3600.0

    if ref in ['S', 'W']:
        degrees = -degrees
        minutes = -minutes
        seconds = -seconds

    return round(degrees + minutes + seconds, 5)


def get_coordinates(geotags):
    if 'GPSLatitude' in geotags and 'GPSLatitudeRef' in geotags:
        lat = get_decimal_from_dms(geotags['GPSLatitude'], geotags['GPSLatitudeRef'])
    else:
        lat = None

    if 'GPSLongitude' in geotags and 'GPSLongitudeRef' in geotags:
        lon = get_decimal_from_dms(geotags['GPSLongitude'], geotags['GPSLongitudeRef'])
    else:
        lon = None
    return {"lat": lat, "lon": lon}


def get_geotagging(exif):
    if exif and 'GPSInfo' in exif:
        geotagging = {}
        for (key, val) in ExifTags.GPSTAGS.items():
            if key in exif['GPSInfo']:
                geotagging[val] = exif['GPSInfo'][key]
        return geotagging
    return None


def main(argv):
    try:
        options = parse_args(argv[1:])
        if options.dry_run:
            print("DRY RUN")
            print("-------")

        directory = os.path.expanduser(options.dir)
        print(f"Processing {directory}")
        retrieve_file_info(directory, options)

        print("Finished")
    except Exception as err:
        print(err)


if __name__ == "__main__":
    main(sys.argv)