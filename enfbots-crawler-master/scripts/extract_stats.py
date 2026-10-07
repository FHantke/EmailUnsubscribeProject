from pathlib import Path
import re
import datetime

#   15   Total websites validated: 0

files = Path("WORKSPACE/logs_5crawl/").glob("*.log")

total_time_pattern = re.compile("Total time: ([ ,a-zA-Z\d:.]+)")
total_translations_pattern = re.compile("Total translations: (\d+)")
total_pages_loaded_pattern = re.compile("Total pages loaded: (\d+)")
total_websites_validated_pattern = re.compile("Total websites validated: (\d+)")
total_classifications_pattern = re.compile("Total classifications: (\d+)")
total_time_translated_pattern = re.compile("Total time translated: ([\d:.]+)")
total_errors_classifying_pattern = re.compile("Total errors when classifying: (\d+)")
validate_crawl_pattern = re.compile("Doing a cached crawl.")

total_time = datetime.timedelta()
total_translations = 0
total_time_translated = datetime.timedelta()
total_classifications = 0
total_pages_loaded = 0
total_errors_classifying = 0
total_websites_visited = 0
total_websites_validated = 0

unfinished = []

for path in sorted(files):
    print("looking at " + str(path))
    time = datetime.timedelta()
    time_translated = datetime.timedelta()
    translations = 0
    pages_loaded = 0
    classifications = 0
    errors_classifying = 0
    validated = 0
    found_anything = False

    lines = open(path, "r").readlines()

    for line in lines[:-12]:
        # The last 12 lines are the accumulated statistics
        time_match = re.search(total_time_pattern, line)
        time_translated_match = re.search(total_time_translated_pattern, line)
        translations_match = re.search(total_translations_pattern, line)
        total_pages_loaded_match = re.search(total_pages_loaded_pattern, line)
        total_classifications_match = re.search(total_classifications_pattern, line)
        total_errors_classifying_match = re.search(total_errors_classifying_pattern, line)
        total_websites_validated_match = re.search(validate_crawl_pattern, line)

        if time_match and time_match.group(1) != "0:00:00":
            print(time_match.group(1) + " is it")
            if "day," in str(time_match.group(1)):
                ltime = datetime.datetime.strptime(time_match.group(1), "%j day, %H:%M:%S.%f")
            elif "days, " in str(time_match.group(1)):
                ltime = datetime.datetime.strptime(time_match.group(1), "%j days, %H:%M:%S.%f")
            else:
                ltime = datetime.datetime.strptime(time_match.group(1), "%H:%M:%S.%f")
            time += ltime - datetime.datetime(1900, 1, 1)
            total_websites_visited += 1
            found_anything = True

        if time_translated_match and not "0:00:00" in line:
            ltime_translated = datetime.datetime.strptime(
                time_translated_match.group(1), "%H:%M:%S.%f"
            )
            time_translated += ltime_translated - datetime.datetime(1900, 1, 1)

        if translations_match:
            translations += int(translations_match.group(1))

        if total_pages_loaded_match:
            pages_loaded += int(total_pages_loaded_match.group(1))

        if total_classifications_match:
            classifications += int(total_classifications_match.group(1))

        if total_errors_classifying_match:
            errors_classifying += int(total_errors_classifying_match.group(1))

        if total_websites_validated_match:
            validated += 1

    if not found_anything:
        print(f"Found nothing in: {path}")
        unfinished.append(path)
    else:
        print(f"Total time for {path}: {str(time)}")
        print(f"Total translations for {path}: {str(translations)}")
        print(f"Total time translated for {path}: {str(time_translated)}")
        print(f"Total pages loaded for {path}: {str(pages_loaded)}")
        print(f"Total classifications for {path}: {str(classifications)}")
        print(f"Total errors classifying for {path}: {str(errors_classifying)}")
        print(f"Total websites validated {path}: {str(validated)}")

    total_time += time
    total_translations += translations
    total_time_translated += time_translated
    total_pages_loaded += pages_loaded
    total_classifications += classifications
    total_errors_classifying += errors_classifying
    total_websites_validated += validated

    # When debugging:
    # break

# print unfinished crawls
print("Unfinished:")
for u in unfinished:
    print("\t" + str(u))

print(f"Total time: {total_time}")
print(f"Total translations: {total_translations}")
print(f"Total time translated: {total_time_translated}")
print(f"Total pages loaded: {total_pages_loaded}")
print(f"Total classifications: {total_classifications}")
print(f"Total errors classifying: {total_errors_classifying}")

print(f"Total websites visited: {total_websites_visited}")
print(f"Total websites validated: {total_websites_validated}")
