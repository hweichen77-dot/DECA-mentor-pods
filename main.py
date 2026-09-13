from pathlib import Path
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict, deque

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
INPUT_CSV = SCRIPT_DIR / "MentorAndMenteeResponses.csv"
CLUSTER_XLSX = SCRIPT_DIR / "WrittenEventClusters.xlsx"
PAST_CSV = SCRIPT_DIR / "PreviousYearRegistrationData.csv"
LEVELS_XLSX = SCRIPT_DIR / "ExpectedExperiencedNoviceMentee.xlsx"
OUTPUT_XLSX = SCRIPT_DIR / "MentorPodSorting.xlsx"
ATTENDANCE_XLSX = SCRIPT_DIR / "MentorPodAttendance.xlsx"
ATTENDANCE_COLUMNS = ["Mentor Pod #", "Mentor Name(s)", "Email", "First Name", "Last Name", "Event", "Status", "Level"]
ATTENDANCE_STATUS = "Compete"

DEFAULT_MAX_SIZE = 7

PLACEHOLDER_ANSWERS = {"", "n/a", "na", "n a", "no", "none", "nan", "-", "n\\a"}
YES_ANSWERS = {"yes", "y", "true"}


def normalize_email(value):
    if not isinstance(value, str):
        return ""
    cleaned = value.strip().lower().replace(" ", "")
    return cleaned.replace("(at)", "@").replace("[at]", "@")


def normalize_text(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def name_fingerprint(value):
    parts = re.findall(r"[a-z']+", normalize_text(value))
    return tuple(sorted(parts))


def event_abbreviation(value):
    if not isinstance(value, str):
        return ""
    inside_parentheses = re.search(r"\(([^)]+)\)", value)
    if inside_parentheses:
        code = re.sub(r"[^A-Za-z0-9]", "", inside_parentheses.group(1)).upper()
        if code:
            return code
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def parse_years_in_deca(value):
    if pd.isna(value):
        return float("nan")
    digits = re.search(r"\d+", str(value))
    return float(digits.group()) if digits else float("nan")


def squash_header(header):
    return re.sub(r"[^a-z0-9]", "", str(header).lower())


def find_column(columns, *fragments, default=None):
    for column in columns:
        lowered = str(column).lower()
        if all(fragment in lowered for fragment in fragments):
            return column
    return default


def find_question(columns, squashed, loose):
    for column in columns:
        if squash_header(column) == squashed:
            return column
    for column in columns:
        if loose in str(column).lower():
            return column
    return None


def find_mentor_flag_column(columns):
    column = find_question(columns, "areyouamentor", "are you a mentor")
    if column is None:
        raise KeyError("The form export has no 'Are you a Mentor?' column.")
    return column


def find_co_president_column(columns):
    return find_question(columns, "areyouacopresident", "co-president")


def answered_yes(series):
    return series.astype(str).str.strip().str.lower().isin(YES_ANSWERS)


def find_written_event_columns(columns, category_column):
    found = []
    for column in columns:
        if column == category_column:
            continue
        lowered = str(column).lower()
        if lowered.startswith("select written") and "category" not in lowered:
            found.append(column)
    if not found:
        raise KeyError("The form export has no 'Select Written' branch columns.")
    return found


def map_categories_to_branch_columns(frame, category_column, written_columns):
    strongest = {}
    for column in written_columns:
        answered = frame.loc[frame[column].notna(), category_column].dropna()
        if answered.empty:
            continue
        counts = answered.value_counts()
        category, hits = counts.index[0], int(counts.iloc[0])
        if category not in strongest or hits > strongest[category][1]:
            strongest[category] = (column, hits)
    return {category: column for category, (column, _) in strongest.items()}


def resolve_written_event(row, category_column, written_columns, category_to_column):
    preferred = category_to_column.get(row[category_column])
    if preferred is not None:
        value = row.get(preferred)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for column in written_columns:
        value = row.get(column)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def find_written_partner_columns(columns, category_column):
    columns = list(columns)
    start = columns.index(category_column)
    tail = columns[start:]
    name_column = find_column(tail, "partner", "full team") or find_column(tail, "partner", "name")
    email_column = find_column(tail, "partner", "email")
    return name_column, email_column


def split_partner_emails(value):
    if not isinstance(value, str):
        return []
    pieces = re.split(r"[,;\s]+", value)
    return [address for address in (normalize_email(piece) for piece in pieces) if "@" in address]


def split_partner_names(value):
    if not isinstance(value, str):
        return []
    fingerprints = []
    for piece in re.split(r"[,;\n]+|\s+and\s+|\s*&\s*", value):
        cleaned = normalize_text(piece)
        if not cleaned or cleaned in PLACEHOLDER_ANSWERS:
            continue
        fingerprint = name_fingerprint(cleaned)
        if len(fingerprint) >= 2:
            fingerprints.append(fingerprint)
    return fingerprints


def load_cluster_lookup(path):
    if not path.exists():
        return {}
    sheet = pd.read_excel(path)
    lookup = {}
    for _, row in sheet.iterrows():
        cluster = str(row["Cluster"]).strip()
        for event in re.split(r"[\n;]+", str(row["Events"])):
            code = event_abbreviation(event.strip())
            if event.strip() and code:
                lookup[code] = cluster
    return lookup


def cluster_of(event_code, category, lookup):
    if not event_code:
        return ""
    if event_code in lookup:
        return lookup[event_code]
    lowered = normalize_text(category)
    if not lowered or "not do a written" in lowered:
        return ""
    return str(category).strip()


def past_events_from_frame(frame):
    columns = list(frame.columns)
    email_column = find_column(columns, "email address", default="Email Address")
    first_name_column = find_column(columns, "first name", default="First Name")
    last_name_column = find_column(columns, "last name", default="Last Name")
    category_column = find_column(columns, "select written event category")
    if category_column is None:
        raise KeyError("The past year export has no 'Select Written Event Category' column.")
    written_columns = find_written_event_columns(columns, category_column)
    category_to_column = map_categories_to_branch_columns(frame, category_column, written_columns)

    by_email = defaultdict(set)
    by_name = defaultdict(set)
    for _, row in frame.iterrows():
        event = resolve_written_event(row, category_column, written_columns, category_to_column)
        if not event:
            continue
        email = normalize_email(row[email_column])
        name_key = name_fingerprint(f"{row[first_name_column]} {row[last_name_column]}")
        if email:
            by_email[email].add(event)
        if len(name_key) >= 2:
            by_name[name_key].add(event)
    return dict(by_email), dict(by_name)


def load_past_events(path):
    if not path.exists():
        return {}, {}
    frame = pd.read_csv(path)
    frame.columns = frame.columns.str.strip()
    return past_events_from_frame(frame)


def load_levels(path):
    if not path.exists():
        return {}
    sheet = pd.read_excel(path)
    email_column = find_column(sheet.columns, "email", default="Email")
    level_column = find_column(sheet.columns, "level", default="Level")
    levels = {}
    for email, level in zip(sheet[email_column].map(normalize_email), sheet[level_column]):
        if email and isinstance(level, str) and level.strip():
            levels[email] = level.strip()
    return levels


def mentee_level(email, years, levels):
    if email in levels:
        return levels[email]
    if not pd.isna(years) and years >= 3:
        return "Experienced"
    return "Novice"


def past_events_for(row, by_email, by_name):
    if row["mentee_email"] in by_email:
        return sorted(by_email[row["mentee_email"]]), "email"
    if row["mentee_name_key"] in by_name:
        return sorted(by_name[row["mentee_name_key"]]), "name"
    return [], ""


def ask_settings():
    answer = input("Enable overflow, filling each pod to the max before starting the next? [y/N]: ")
    overflow = answer.strip().lower() in YES_ANSWERS
    while True:
        answer = input(f"Max pod size [{DEFAULT_MAX_SIZE}]: ").strip()
        if not answer:
            return overflow, DEFAULT_MAX_SIZE
        if answer.isdigit() and int(answer) >= 2:
            return overflow, int(answer)
        print("Type a whole number of 2 or more.")


def build_teams(mentees, mentors, everyone, max_size=DEFAULT_MAX_SIZE):
    index_by_email = {}
    index_by_name = {}
    for index, row in everyone.iterrows():
        if row["mentee_email"]:
            index_by_email.setdefault(row["mentee_email"], index)
        if len(row["mentee_name_key"]) >= 2:
            index_by_name.setdefault(row["mentee_name_key"], index)
    for index, row in everyone.iterrows():
        if len(row["email_name_key"]) >= 2:
            index_by_name.setdefault(row["email_name_key"], index)

    mentee_set = set(mentees.index)
    mentor_set = set(mentors.index)
    neighbours = defaultdict(set)
    mentor_links = defaultdict(set)
    conflicts = set()
    officer_partners = []
    missing = []

    def claims_of(index, row):
        found_people = []
        for address in row["partner_emails"]:
            found = index_by_email.get(address)
            if found is None:
                missing.append((index, address))
            else:
                found_people.append(found)
        for key in row["partner_names"]:
            found = index_by_name.get(key)
            if found is None:
                if key != row["mentee_name_key"] and key != row["email_name_key"]:
                    missing.append((index, " ".join(key)))
            else:
                found_people.append(found)
        return [other for other in found_people if other != index]

    for index, row in mentees.iterrows():
        for other in claims_of(index, row):
            if other in mentor_set:
                mentor_links[other].add(index)
            elif other not in mentee_set:
                officer_partners.append((index, other))
            elif mentees.at[other, "event_code"] != row["event_code"]:
                conflicts.add((min(index, other), max(index, other)))
            else:
                neighbours[index].add(other)
                neighbours[other].add(index)

    for index, row in mentors.iterrows():
        for other in claims_of(index, row):
            if other in mentee_set:
                mentor_links[index].add(other)

    teams = []
    seen = set()
    for index in mentees.index:
        if index in seen:
            continue
        team = []
        queue = deque([index])
        seen.add(index)
        while queue:
            current = queue.popleft()
            team.append(current)
            for other in neighbours[current]:
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
        team.sort()
        for start in range(0, len(team), max_size):
            teams.append(team[start:start + max_size])

    teams.sort(key=lambda team: (-len(team), team[0]))
    return teams, sorted(conflicts), dict(mentor_links), sorted(set(officer_partners)), missing


def clears_seniority(mentor_experience, needed_experience):
    if pd.isna(needed_experience) or pd.isna(mentor_experience):
        return True
    return mentor_experience >= needed_experience


def pod_size(pod):
    return sum(len(team) for team in pod["pinned"] + pod["teams"])


def team_experience(team, mentees):
    return pd.to_numeric(mentees.loc[team, "years_number"], errors="coerce").max()


def rebalance(cluster_pods, mentees, mentors, max_size):
    if len(cluster_pods) < 2:
        return
    ideal = sum(pod_size(pod) for pod in cluster_pods) / len(cluster_pods)

    def fits(pod, team):
        if pod["mentor"] is None:
            return True
        return clears_seniority(mentors.at[pod["mentor"], "years_number"], team_experience(team, mentees))

    def spread_cost(sizes):
        return sum((size - ideal) ** 2 for size in sizes)

    while True:
        sizes = [pod_size(pod) for pod in cluster_pods]
        ceiling = max(max_size, max(sizes))
        current_cost = spread_cost(sizes)
        best_move = None
        for source_slot, source in enumerate(cluster_pods):
            for position, team in enumerate(source["teams"]):
                for destination_slot, destination in enumerate(cluster_pods):
                    if destination is source:
                        continue
                    trial = list(sizes)
                    trial[source_slot] -= len(team)
                    trial[destination_slot] += len(team)
                    if max(trial) > ceiling:
                        continue
                    if fits(source, team) and not fits(destination, team):
                        continue
                    cost = spread_cost(trial)
                    event = mentees.at[team[0], "event_code"]
                    keeps_block = 0 if event in pod_events(destination, mentees, mentors) else 1
                    if cost < current_cost - 1e-9 and (best_move is None or (cost, keeps_block) < best_move[:2]):
                        best_move = (cost, keeps_block, source, position, destination)
        if best_move is None:
            break
        _, _, source, position, destination = best_move
        destination["teams"].append(source["teams"].pop(position))


def pod_events(pod, mentees, mentors):
    held = {mentees.at[member, "event_code"] for team in pod["pinned"] + pod["teams"] for member in team}
    if pod["mentor"] is not None:
        held.update(mentors.at[pod["mentor"], "past_codes"])
    return held


def place_team(team, candidate_pods, mentees, mentors, max_size, ideal, overflow):
    needed = team_experience(team, mentees)
    event = mentees.at[team[0], "event_code"]

    def ranking(pod):
        mentor = pod["mentor"]
        mentor_years = float("nan") if mentor is None else mentors.at[mentor, "years_number"]
        over_cap = pod_size(pod) + len(team) > max_size
        outranked = not clears_seniority(mentor_years, needed)
        new_event = event not in pod_events(pod, mentees, mentors)
        if overflow:
            return (over_cap, outranked, new_event, pod["order"])
        return (over_cap, outranked, new_event, pod_size(pod) + len(team) > ideal, pod_size(pod), pod["order"])

    chosen = min(candidate_pods, key=ranking)
    chosen["teams"].append(team)


def build_pods(teams, mentees, mentors, all_links, max_size=DEFAULT_MAX_SIZE, overflow=False):
    team_of = {member: team for team in teams for member in team}
    teams_by_cluster = defaultdict(list)
    for team in teams:
        teams_by_cluster[mentees.at[team[0], "cluster"]].append(team)
    clusters = sorted(cluster for cluster in teams_by_cluster if cluster)

    mentor_links = {}
    for mentor_index, linked in all_links.items():
        eligible = {mentee for mentee in linked
                    if mentees.at[mentee, "cluster"] == mentors.at[mentor_index, "cluster"]}
        if eligible:
            mentor_links[mentor_index] = eligible

    def mentor_cluster(mentor_index):
        return mentors.at[mentor_index, "cluster"]

    def mentor_rank(mentor_index):
        years = mentors.at[mentor_index, "years_number"]
        return (
            0 if mentor_links.get(mentor_index) else 1,
            -(-1.0 if pd.isna(years) else float(years)),
            str(mentors.at[mentor_index, "last_name"]),
            str(mentors.at[mentor_index, "first_name"]),
        )

    mentors_by_cluster = defaultdict(list)
    for mentor_index in sorted(mentors.index, key=mentor_rank):
        mentors_by_cluster[mentor_cluster(mentor_index)].append(mentor_index)

    people = {cluster: sum(len(team) for team in teams_by_cluster[cluster]) for cluster in clusters}
    need = {cluster: max(1, -(-people[cluster] // max_size)) for cluster in clusters}
    if overflow:
        pod_count = dict(need)
    else:
        pod_count = {cluster: max(need[cluster], min(len(mentors_by_cluster[cluster]), people[cluster]))
                     for cluster in clusters}
        while True:
            short = [cluster for cluster in clusters if pod_count[cluster] > len(mentors_by_cluster[cluster])]
            spare = [cluster for cluster in clusters if pod_count[cluster] > need[cluster]
                     and len(mentors_by_cluster[cluster]) >= pod_count[cluster]]
            if not short or not spare:
                break
            if sum(pod_count.values()) <= len(mentors.index):
                break
            giver = min(spare, key=lambda cluster: (people[cluster] / pod_count[cluster], cluster))
            pod_count[giver] -= 1

    leaders = {}
    pool = []
    for cluster, ranked in mentors_by_cluster.items():
        if cluster in clusters:
            leaders[cluster] = ranked[:pod_count[cluster]]
            pool.extend(ranked[pod_count[cluster]:])
        else:
            pool.extend(ranked)
    pool.sort(key=lambda mentor: (1 if mentors.at[mentor, "cluster"] else 0, mentor_rank(mentor)))
    for cluster in clusters:
        leaders.setdefault(cluster, [])

    borrowed = []
    while pool:
        short = [cluster for cluster in clusters if len(leaders[cluster]) < pod_count[cluster]]
        if not short:
            break
        neediest = max(short, key=lambda cluster: people[cluster] / max(1, len(leaders[cluster])))
        mentor = pool.pop(0)
        leaders[neediest].append(mentor)
        borrowed.append((mentor, neediest))
    idle_mentors = list(pool)
    unseated = set()

    pods = []
    claimed = {}
    contested = []
    for cluster in clusters:
        while len(leaders[cluster]) < pod_count[cluster]:
            leaders[cluster].append(None)
        for mentor in leaders[cluster]:
            pod = {"mentor": mentor, "cluster": cluster, "pinned": [], "teams": [], "order": len(pods)}
            for mentee in sorted(mentor_links.get(mentor, ()) if mentor is not None else ()):
                team = team_of[mentee]
                if mentees.at[team[0], "cluster"] != cluster:
                    unseated.add(mentor)
                    continue
                if id(team) in claimed:
                    if claimed[id(team)] is not pod:
                        contested.append((mentor, mentee, claimed[id(team)]["mentor"]))
                    continue
                claimed[id(team)] = pod
                pod["pinned"].append(team)
            pods.append(pod)

    leading = {pod["mentor"] for pod in pods if pod["mentor"] is not None}
    unseated = sorted(unseated | {mentor for mentor in all_links if mentor not in leading or mentor not in mentor_links})

    for cluster in clusters:
        cluster_pods = [pod for pod in pods if pod["cluster"] == cluster]
        remaining = [team for team in teams_by_cluster[cluster] if id(team) not in claimed]
        ideal = -(-people[cluster] // len(cluster_pods))
        event_headcount = Counter()
        for team in remaining:
            event_headcount[mentees.at[team[0], "event_code"]] += len(team)
        for team in sorted(remaining, key=lambda team: (
            -event_headcount[mentees.at[team[0], "event_code"]],
            mentees.at[team[0], "event_code"],
            -len(team),
            team[0],
        )):
            place_team(team, cluster_pods, mentees, mentors, max_size, ideal, overflow)
            claimed[id(team)] = cluster_pods[0]
        if not overflow:
            rebalance(cluster_pods, mentees, mentors, max_size)

    for team in sorted(teams_by_cluster.get("", []), key=lambda team: (-len(team), team[0])):
        if id(team) in claimed:
            continue
        if not pods:
            pods.append({"mentor": None, "cluster": "", "pinned": [], "teams": [], "order": 0})
        place_team(team, pods, mentees, mentors, max_size, max_size - 1, overflow)

    for pod in pods:
        pod["members"] = sorted(member for team in pod["pinned"] + pod["teams"] for member in team)
        pod["seeded"] = sorted(member for team in pod["pinned"] for member in team)
    return pods, borrowed, idle_mentors, contested, unseated


def open_when_possible(path):
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif os.name == "nt":
            os.startfile(str(path))
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as problem:
        print(f"Could not open {path} automatically ({problem}).")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    overflow, max_size = ask_settings()
    print(f"Max pod size {max_size}, overflow {'on' if overflow else 'off'}")

    print("Reading:", INPUT_CSV)
    if not INPUT_CSV.exists():
        raise FileNotFoundError(f"Can't find {INPUT_CSV}")

    frame = pd.read_csv(INPUT_CSV)
    frame.columns = frame.columns.str.strip()
    columns = list(frame.columns)

    timestamp_column = find_column(columns, "timestamp", default="Timestamp")
    email_column = find_column(columns, "email address", default="Email Address")
    first_name_column = find_column(columns, "first name", default="First Name")
    last_name_column = find_column(columns, "last name", default="Last Name")
    years_column = find_column(columns, "year in deca", default="Year in DECA")
    mentor_flag_column = find_mentor_flag_column(columns)
    co_president_column = find_co_president_column(columns)
    category_column = find_column(columns, "select written event category")
    if category_column is None:
        raise KeyError("The form export has no 'Select Written Event Category' column.")
    written_columns = find_written_event_columns(columns, category_column)
    partner_name_column, partner_email_column = find_written_partner_columns(columns, category_column)

    print(f"Written event branches in use: {len(written_columns)}")
    print(f"Written event teammate columns: {partner_name_column!r}, {partner_email_column!r}")
    if co_president_column is None:
        print("No 'Are you a Co-President?' column found, so nobody is skipped as a co-president.")

    cluster_lookup = load_cluster_lookup(CLUSTER_XLSX)
    if cluster_lookup:
        print(f"Cluster sheet: {CLUSTER_XLSX.name}, {len(cluster_lookup)} events in {len(set(cluster_lookup.values()))} clusters")
    else:
        print(f"No cluster sheet at {CLUSTER_XLSX.name}, so the form's written event category stands in for the cluster.")

    category_to_column = map_categories_to_branch_columns(frame, category_column, written_columns)

    frame["first_name"] = frame[first_name_column].fillna("").astype(str).str.strip()
    frame["last_name"] = frame[last_name_column].fillna("").astype(str).str.strip()
    frame["full_name"] = (frame["last_name"] + ", " + frame["first_name"]).str.strip(", ")
    frame["mentee_name_key"] = (frame["first_name"] + " " + frame["last_name"]).map(name_fingerprint)
    frame["email_name_key"] = (
        frame[email_column].map(normalize_email)
        .str.split("@").str[0].str.replace(r"[._]", " ", regex=True).map(name_fingerprint)
    )
    frame["mentee_email"] = frame[email_column].map(normalize_email)
    frame["years_number"] = frame[years_column].map(parse_years_in_deca)

    frame["event_name"] = frame.apply(
        lambda row: resolve_written_event(row, category_column, written_columns, category_to_column),
        axis=1,
    )
    frame["event_code"] = frame["event_name"].map(event_abbreviation)
    frame["cluster"] = [
        cluster_of(code, category, cluster_lookup)
        for code, category in zip(frame["event_code"], frame[category_column])
    ]

    if partner_email_column:
        frame["partner_emails"] = frame[partner_email_column].map(split_partner_emails)
    else:
        frame["partner_emails"] = [[] for _ in range(len(frame))]
    if partner_name_column:
        frame["partner_names"] = frame[partner_name_column].map(split_partner_names)
    else:
        frame["partner_names"] = [[] for _ in range(len(frame))]

    raw_rows = len(frame)
    frame = frame[(frame["mentee_email"] != "") | (frame["full_name"] != "")]
    frame = frame[frame[email_column].astype(str).str.strip() != email_column]
    frame = frame[~frame.index.isin(
        frame[frame["mentee_email"] != ""].sort_values(timestamp_column, kind="stable")
        .duplicated("mentee_email", keep="last").pipe(lambda d: d[d].index)
    )]
    if len(frame) != raw_rows:
        print(f"Dropped {raw_rows - len(frame)} blank or repeat rows ({raw_rows} -> {len(frame)})")

    mentor_answers = frame[mentor_flag_column].astype(str).str.strip().str.lower()
    print("Mentor question answers:", dict(Counter(mentor_answers)))
    is_mentor = answered_yes(frame[mentor_flag_column])
    is_co_president = (
        answered_yes(frame[co_president_column]) if co_president_column
        else pd.Series(False, index=frame.index)
    )
    officers = frame[is_co_president].copy()
    mentors = frame[is_mentor & ~is_co_president].copy()
    mentees = frame[~is_mentor & ~is_co_president].copy()

    past_by_email, past_by_name = load_past_events(PAST_CSV)
    mentee_headcount = Counter(mentees["cluster"])
    matched_how = []
    past_names = []
    past_codes = []
    past_clusters = []
    for _, row in mentors.iterrows():
        events, how = past_events_for(row, past_by_email, past_by_name)
        matched_how.append(how)
        past_names.append("; ".join(events))
        codes = [event_abbreviation(event) for event in events]
        past_codes.append(frozenset(codes))
        eligible = {cluster_of(code, "", cluster_lookup) for code in codes} - {""}
        past_clusters.append(max(eligible, key=lambda cluster: (mentee_headcount[cluster], cluster)) if eligible else "")
    mentors["past_matched"] = matched_how
    mentors["past_events"] = past_names
    mentors["past_codes"] = past_codes
    mentors["cluster"] = past_clusters

    blank_events = int((frame["event_name"] == "").sum())
    print(f"Co-presidents skipped: {len(officers)}")
    for name in sorted(officers["full_name"]):
        print(f"  {name}")
    print(f"Mentors who answered Yes: {len(mentors)}")
    print(f"Mentees: {len(mentees)}")
    print(f"Responses with a written event: {len(frame) - blank_events}/{len(frame)}")
    if past_by_email:
        print(f"Past year data: {PAST_CSV.name}, {len(past_by_email)} people with a written event")
        how = Counter(mentors["past_matched"])
        print(f"Mentors matched to a past written event: {how.get('email', 0)} by email, {how.get('name', 0)} by name, {how.get('', 0)} unmatched")
        for _, row in mentors[mentors["past_matched"] == "name"].iterrows():
            print(f"  {row['full_name']} matched by name only, {row['mentee_email']} is not in the past year data")
        for _, row in mentors[mentors["past_matched"] == ""].iterrows():
            print(f"  {row['full_name']} has no past written event on record, so they can lead any cluster")
    else:
        print(f"No past year data at {PAST_CSV.name}, so mentors are placed by this year's written event.")
        mentors["cluster"] = mentors["event_name"].map(lambda event: cluster_of(event_abbreviation(event), "", cluster_lookup))
        mentors["past_codes"] = mentors["event_code"].map(lambda code: frozenset({code} - {""}))
    unknown_cluster = sorted(set(frame.loc[(frame["event_code"] != "") & (frame["cluster"] == ""), "event_name"]))
    if unknown_cluster:
        print(f"Written events with no cluster in the sheet or the form: {unknown_cluster}")
    print("Note: the form never asks for school grade, so seniority uses Year in DECA.")

    teams, conflicts, mentor_links, officer_partners, missing = build_teams(mentees, mentors, frame, max_size)
    team_sizes = defaultdict(int)
    for team in teams:
        team_sizes[len(team)] += 1
    print("Teams by size:", dict(sorted(team_sizes.items())))

    if conflicts:
        print(f"Teammates who named each other but picked different written events: {len(conflicts)}")
        for left, right in conflicts:
            print(f"  {mentees.at[left, 'full_name']} ({mentees.at[left, 'event_name']})"
                  f"  vs  {mentees.at[right, 'full_name']} ({mentees.at[right, 'event_name']})")

    if mentor_links:
        pairs = sorted((mentors.at[m, "full_name"], mentees.at[mentee, "full_name"])
                       for m, linked in mentor_links.items() for mentee in linked)
        print(f"Mentors whose written event teammate is a mentee: {len(pairs)}")
        for mentor_name, mentee_name in pairs:
            print(f"  {mentor_name} competes with {mentee_name}")
    if officer_partners:
        pairs = {(mentees.at[a, "full_name"], frame.at[b, "full_name"]) for a, b in officer_partners}
        print(f"Mentees whose written event teammate is a co-president, sorted on their own: {len(pairs)}")
        for mentee_name, officer_name in sorted(pairs):
            print(f"  {mentee_name} named {officer_name}")
    if missing:
        wanted = {(frame.at[index, "full_name"], text) for index, text in missing}
        print(f"Teammates named by someone but matching no response: {len(wanted)}")
        for person_name, text in sorted(wanted):
            print(f"  {person_name} named {text}")

    pods, borrowed, idle_mentors, contested, unseated = build_pods(teams, mentees, mentors, mentor_links, max_size, overflow)
    if unseated:
        print(f"Mentors whose teammate is sorted without them, cluster too small or not one they have done: {len(unseated)}")
        for mentor in unseated:
            print(f"  {mentors.at[mentor, 'full_name']}")
    if contested:
        print(f"Teams named by two mentors, kept with the first: {len(contested)}")
        for mentor, mentee, winner in contested:
            print(f"  {mentees.at[mentee, 'full_name']} named by {mentors.at[mentor, 'full_name']}"
                  f" stays with {mentors.at[winner, 'full_name']}")

    def pod_key(pod):
        mentor = pod["mentor"]
        if mentor is None:
            return (pod["cluster"], "~", "", pod["order"])
        return (pod["cluster"], str(mentors.at[mentor, "last_name"]), str(mentors.at[mentor, "first_name"]), pod["order"])

    pods = [pod for pod in pods if pod["members"]]
    pods.sort(key=pod_key)
    for pod_number, pod in enumerate(pods, start=1):
        pod["number"] = pod_number

    rows = []
    cross_cluster = []
    outranked = []
    mentorless = []

    for pod in pods:
        pod_number = pod["number"]
        mentor_index = pod["mentor"]
        if mentor_index is None:
            mentor_first = mentor_last = mentor_event = mentor_years = mentor_past = ""
            mentorless.append(pod_number)
        else:
            mentor_first = mentors.at[mentor_index, "first_name"]
            mentor_last = mentors.at[mentor_index, "last_name"]
            mentor_event = mentors.at[mentor_index, "event_name"]
            mentor_past = mentors.at[mentor_index, "past_events"]
            mentor_years = mentors.at[mentor_index, years_column]
            if mentors.at[mentor_index, "cluster"] not in ("", pod["cluster"]):
                cross_cluster.append(pod_number)
            if not clears_seniority(mentors.at[mentor_index, "years_number"], team_experience(pod["members"], mentees)):
                outranked.append(pod_number)

        for member in pod["members"]:
            person = mentees.loc[member]
            rows.append({
                "Pod": pod_number,
                "Mentor First Name": mentor_first,
                "Mentor Last Name": mentor_last,
                "Mentor Year in DECA": mentor_years,
                "Mentor Event": mentor_event,
                "Mentor Past Event": mentor_past,
                "Cluster": pod["cluster"],
                "Event": person["event_name"],
                "Mentee First Name": person["first_name"],
                "Mentee Last Name": person["last_name"],
                "Years in DECA": person[years_column],
                "Email": person[email_column],
                "Timestamp": person[timestamp_column],
                "Mentor's Teammate": "Yes" if member in pod["seeded"] else "",
            })

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(["Pod", "Mentee Last Name", "Mentee First Name"])

    sizes = Counter(len(pod["members"]) for pod in pods)
    print(f"\nPods built: {len(pods)}")
    print("Pod sizes:", dict(sorted(sizes.items())))
    under = [pod for pod in pods if len(pod["members"]) < max_size - 1]
    if under:
        print(f"Pods under {max_size - 1}: {len(under)}, smallest {min(len(pod['members']) for pod in under)}")
    over = [pod["number"] for pod in pods if len(pod["members"]) > max_size]
    if over:
        print(f"Pods over {max_size}: {over}")
    seeded_pods = sum(1 for pod in pods if pod["seeded"])
    print(f"Pods holding the mentor's own teammates: {seeded_pods}")
    for pod in pods:
        spread = Counter(mentees.at[member, "event_code"] for member in pod["members"])
        if len(spread) > 1:
            print(f"  pod {pod['number']} ({pod['cluster']}): "
                  + ", ".join(f"{code} x{count}" for code, count in spread.most_common()))
    if cross_cluster:
        print(f"Pods whose mentor has not done that cluster before: {len(cross_cluster)} {cross_cluster}")
    if outranked:
        print(f"Pods where a mentee has more years in DECA than the mentor: {len(outranked)} {outranked}")
    if mentorless:
        print(f"Pods with no mentor available: {len(mentorless)} {mentorless}")
    print(f"Mentors used: {len(pods) - len(mentorless)} of {len(mentors)}")
    if idle_mentors:
        print("Mentors without a pod: " + ", ".join(sorted(mentors.at[m, "full_name"] for m in idle_mentors)))

    result.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
    print(f"Wrote {len(result)} rows to {OUTPUT_XLSX}")

    levels = load_levels(LEVELS_XLSX)
    if not levels:
        print(f"No level sheet at {LEVELS_XLSX.name}, so Level is blank except first years.")
    attendance_rows = []
    guessed = []
    for pod in pods:
        mentor_index = pod["mentor"]
        mentor_name = "" if mentor_index is None else (
            f"{mentors.at[mentor_index, 'first_name']} {mentors.at[mentor_index, 'last_name']}".strip()
        )
        if mentor_index is not None:
            attendance_rows.append({
                "Mentor Pod #": pod["number"],
                "Mentor Name(s)": mentor_name,
                "Email": mentors.at[mentor_index, email_column],
                "First Name": mentors.at[mentor_index, "first_name"],
                "Last Name": mentors.at[mentor_index, "last_name"],
                "Event": mentors.at[mentor_index, "event_name"],
                "Status": "",
                "Level": "Experienced",
            })
        for member in sorted(pod["members"], key=lambda m: (mentees.at[m, "last_name"], mentees.at[m, "first_name"])):
            person = mentees.loc[member]
            email = normalize_email(person[email_column])
            if email not in levels and person["years_number"] != 1:
                guessed.append(person)
            attendance_rows.append({
                "Mentor Pod #": pod["number"],
                "Mentor Name(s)": mentor_name,
                "Email": person[email_column],
                "First Name": person["first_name"],
                "Last Name": person["last_name"],
                "Event": person["event_name"],
                "Status": ATTENDANCE_STATUS,
                "Level": mentee_level(email, person["years_number"], levels),
            })
    attendance = pd.DataFrame(attendance_rows, columns=ATTENDANCE_COLUMNS)
    if guessed:
        print(f"Returning mentees missing from {LEVELS_XLSX.name}, Level set from Year in DECA: {len(guessed)}")
        for person in guessed:
            print(f"  {person['full_name']} {person[email_column]} {person[years_column]} -> "
                  f"{mentee_level(normalize_email(person[email_column]), person['years_number'], levels)}")
    attendance.to_excel(ATTENDANCE_XLSX, index=False, engine="openpyxl")
    print(f"Wrote {len(attendance)} rows to {ATTENDANCE_XLSX}")
    if "--no-open" not in argv:
        open_when_possible(OUTPUT_XLSX)


if __name__ == "__main__":
    main()
